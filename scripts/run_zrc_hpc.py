"""Isolated Slurm workers for the authorized remaining ZrC production matrix."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import sys
import time
import traceback
from collections import Counter
import numpy as np
from run_zrc_md_campaign import Campaign, digest, read_json, utc, worker_lock
from zrc_md_engine import YieldRun, NumericalFailure, atomic_json, load_checkpoint, run_segment

ROOT = Path(__file__).resolve().parents[1]

def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def manifest():
    return read_json(ROOT / "manifest.json")

def check_environment(require_gpu=False):
    expected = manifest()["hpc_versions"]
    versions = {name: metadata.version(name) for name in expected}
    if versions != expected:
        raise RuntimeError("Environment versions differ from accepted job 15325225: " + str(versions))
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Expected Python 3.12")
    result = {"packages": dict(sorted((d.metadata["Name"].lower(), d.version)
                                     for d in metadata.distributions() if d.metadata["Name"])),
              "python": sys.version, "libc": platform.libc_ver()}
    if require_gpu:
        import torch
        if not torch.cuda.is_available() or torch.version.cuda != "11.8":
            raise RuntimeError("Expected working CUDA 11.8")
        if torch.cuda.get_device_capability(0) != (7, 0) or "V100" not in torch.cuda.get_device_name(0):
            raise RuntimeError("Expected allocated V100 GPU")
        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        result.update(gpu=torch.cuda.get_device_name(0), capability=[7, 0], cuda=torch.version.cuda)
    return result

class StopFiles:
    def __init__(self, directory):
        self.local = directory / "STOP"
    def __fspath__(self):
        return str(ROOT / "STOP" if (ROOT / "STOP").exists() else self.local)

class IsolatedCampaign(Campaign):
    def __init__(self, directory, records, role, environment, gates=None):
        super().__init__(ROOT / "configs/experiments/zrc_mace_round1.json", directory)
        self.bundle = manifest()
        self.environment = environment
        self.contract = {"manifest_sha256": digest(ROOT / "manifest.json"),
                         "environment_sha256": identity(environment), "role": role,
                         "jobs": [r["id"] for r in records]}
        self.records = {r["id"]: r for r in records}
        self.stop_file = StopFiles(self.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.active = None
        if self.queue_path.exists():
            self.queue = read_json(self.queue_path)
            if self.queue.get("hpc_contract") != self.contract:
                raise RuntimeError("Existing worker output belongs to a different bundle/environment/task")
        else:
            jobs = []
            for record in records:
                job = copy.deepcopy(record["job"])
                job["pilot"]["final_checkpoint"] = f"jobs/{job['id']}/pilot-source/checkpoint.npz"
                job["production"] = {"status": "pending", "attempts": []}
                jobs.append(job)
            self.queue = {"campaign_id": self.bundle["campaign_id"], "status": "initialized",
                          "jobs": jobs, "gates": copy.deepcopy(gates or {}),
                          "hpc_contract": self.contract, "physical_validated": False}
            self.save()
        for record in records:
            for kind, destination in [("checkpoint", self.out / "jobs" / record["id"] / "pilot-source/checkpoint.npz"),
                                      ("initial", self.out / "jobs" / record["id"] / "initial.POSCAR")]:
                source = ROOT / record[kind + "_path"]
                wanted = record[kind + "_sha256"]
                if digest(source) != wanted:
                    raise RuntimeError("Changed packaged source: " + str(source))
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copyfile(source, destination)
                if digest(destination) != wanted:
                    raise RuntimeError("Changed worker initial state: " + str(destination))
        atomic_json(self.out / "environment.json", environment)

    def report(self):
        counts = dict(Counter(j["production"]["status"] for j in self.queue["jobs"]))
        result = {"status": self.queue["status"], "production": counts,
                  "gates": self.queue["gates"], "physical_validated": False}
        atomic_json(self.out / "summary.json", result)
        return result

    def spec(self, job, *args, **kwargs):
        value = super().spec(job, *args, **kwargs)
        value.update(hpc_bundle_sha256=self.contract["manifest_sha256"],
                     hpc_environment_sha256=self.contract["environment_sha256"],
                     initial_pilot_sha256=self.records[job["id"]]["checkpoint_sha256"])
        return value

    def segment(self, atoms, rng, directory, spec):
        assert_running_allowed(self)
        return super().segment(atoms, rng, directory, spec)

    def stage_start(self, job, phase):
        saved = self.out / "jobs" / job["id"] / f"{phase}-initial.npz"
        source = self.out / job["pilot"]["final_checkpoint"]
        if saved.exists():
            _, _, info = load_checkpoint(saved)
            if info.get("source_sha256") != digest(source):
                raise RuntimeError("Production initial state provenance changed")
        return super().stage_start(job, phase)

    def configure_signals(self):
        local = self.out / "STOP"
        # Only our scheduler signal marker is automatically cleared on explicit resubmission.
        if local.exists() and local.read_text(encoding="utf-8") == "SLURM_SIGNAL_CHECKPOINT\n":
            local.unlink()
        def stop(signum, frame):
            if not local.exists():
                local.write_text("SLURM_SIGNAL_CHECKPOINT\n", encoding="utf-8")
        for name in ["SIGUSR1", "SIGTERM"]:
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), stop)


def assert_running_allowed(campaign):
    if Path(campaign.stop_file).exists():
        raise YieldRun("STOP marker: no new stage may start")


def verify_certificate(size, environment):
    path = ROOT / "outputs/validation" / str(size) / "ready.json"
    cert = read_json(path)
    if cert["status"] != "passed" or cert["manifest_sha256"] != digest(ROOT / "manifest.json"):
        raise RuntimeError("Missing or mismatched validation certificate")
    if cert["environment_sha256"] != identity(environment):
        raise RuntimeError("Validation environment differs from production environment")
    if set(cert["gates"]) != {f"warm_{size}", f"high_{size}"}:
        raise RuntimeError("Incomplete gate certificate")
    if any(g["status"] != "passed" for g in cert["gates"].values()):
        raise RuntimeError("Unpassed numerical gate")
    for name, wanted in cert["artifacts"].items():
        if digest(path.parent / name) != wanted:
            raise RuntimeError("Validation artifact changed: " + name)
    return cert


def restart_check(campaign, job, gate):
    directory = campaign.out / "restart" / job["id"]
    directory.mkdir(parents=True, exist_ok=True)
    atoms, rng, _ = load_checkpoint(campaign.out / job["pilot"]["final_checkpoint"])
    policy = campaign.bundle["restart_check"]
    spec = campaign.spec(job, "migration_restart", policy["duration_fs"],
                         gate["selected_dt_fs"], gate["selected_dtype"])
    assert_running_allowed(campaign)
    full, full_rng, _ = campaign.segment(atoms, rng, directory / "uninterrupted", spec)
    split_dir = directory / "resumed"
    proof = directory / "interruption.json"
    if not proof.exists() and (split_dir / "checkpoint.npz").exists():
        _, _, saved = load_checkpoint(split_dir / "checkpoint.npz")
        saved_time = saved["step"] * spec["time_step_fs"]
        if policy["interrupt_fs"] <= saved_time < policy["duration_fs"]:
            atomic_json(proof, {"time_fs": saved_time,
                               "checkpoint_sha256": digest(split_dir / "checkpoint.npz"),
                               "recovered_committed_interruption": True})
    if not proof.exists():
        # This branch must show an actual committed interruption before acceptance.
        def interrupt(detail):
            campaign.progress(detail)
            if detail["time_fs"] >= policy["interrupt_fs"]:
                atomic_json(proof, {"time_fs": detail["time_fs"],
                                   "checkpoint_sha256": digest(split_dir / "checkpoint.npz")})
                raise YieldRun("Intentional restart verification")
        try:
            run_segment(atoms, rng, campaign.calculator(spec["dtype"]), split_dir, spec,
                        progress=interrupt, stop_file=campaign.stop_file)
        except YieldRun:
            if not proof.exists():
                raise
        if not proof.exists():
            raise RuntimeError("No genuine checkpoint interruption was exercised")
    if read_json(proof)["time_fs"] >= policy["duration_fs"]:
        raise RuntimeError("Restart exercise did not interrupt inside the segment")
    assert_running_allowed(campaign)
    resumed, resumed_rng, _ = campaign.segment(atoms, rng, split_dir, spec)
    pos = float(np.max(np.abs(full.positions - resumed.positions)))
    mom = float(np.max(np.abs(full.get_momenta() - resumed.get_momenta())))
    same_rng = full_rng.bit_generator.state == resumed_rng.bit_generator.state
    passed = pos <= policy["position_atol_A"] and mom <= policy["momentum_atol_ASE"] and same_rng
    report = {"status": "passed" if passed else "blocked_review", "max_position_difference_A": pos,
              "max_momentum_difference_ASE": mom, "identical_rng_state": same_rng, "policy": policy,
              "physical_validated": False}
    atomic_json(directory / "review.json", report)
    if not passed:
        raise NumericalFailure("Restart comparison failed; no threshold relaxation is permitted")


def validate(size, environment):
    bundle = manifest()
    records = [r for r in bundle["remaining"] if r["job"]["atoms"] == size
               and r["job"]["temperature_K"] in (3000, 6000)
               and r["job"]["volume_scale"] == 1.0 and r["job"]["seed"] == 17]
    if len(records) != 2:
        raise RuntimeError("Expected warm/high validation source states")
    directory = ROOT / "outputs/validation" / str(size)
    with worker_lock(directory):
        if (directory / "ready.json").exists():
            verify_certificate(size, environment)
            print("Validation already passed and artifacts verified", flush=True)
            return
        c = IsolatedCampaign(directory, records, "validation", environment)
        c.configure_signals()
        try:
            for kind in ["warm", "high"]:
                assert_running_allowed(c)
                c.run_gate(size, kind)
                gate = c.queue["gates"][f"{kind}_{size}"]
                if gate["status"] != "passed":
                    raise NumericalFailure(f"{kind}_{size} blocked")
                job = c.lookup(f"zrc{size}_T{3000 if kind == 'warm' else 6000:04d}_v100_s17")
                restart_check(c, job, gate)
            artifacts = {p.relative_to(directory).as_posix(): digest(p)
                         for folder in [directory / "gates", directory / "restart"]
                         for p in sorted(folder.rglob("*")) if p.is_file()}
            cert = {"status": "passed", "utc": utc(), "manifest_sha256": digest(ROOT / "manifest.json"),
                    "environment_sha256": identity(environment), "gates": c.queue["gates"],
                    "artifacts": artifacts, "physical_validated": False}
            atomic_json(directory / "ready.json", cert)
            c.queue["status"] = "passed"
            c.save()
        except Exception as exc:
            c.queue["status"] = "interrupted" if isinstance(exc, YieldRun) else "needs_review"
            c.save()
            atomic_json(directory / f"failure-{time.time_ns()}.json", {"utc": utc(), "traceback": traceback.format_exc()})
            raise


def produce(size, index, environment):
    group = [r for r in manifest()["remaining"] if r["job"]["atoms"] == size]
    if not 0 <= index < len(group):
        raise ValueError("Array index out of range")
    cert = verify_certificate(size, environment)
    record = group[index]
    directory = ROOT / "outputs/production" / record["id"]
    with worker_lock(directory):
        c = IsolatedCampaign(directory, [record], "production", environment, cert["gates"])
        c.configure_signals()
        try:
            assert_running_allowed(c)
            job = c.queue["jobs"][0]
            if c.queue["gates"] != cert["gates"]:
                raise RuntimeError("Production gate selection changed")
            if job["production"]["status"] == "passed":
                attempt = len(job["production"]["attempts"])
                for stage in ["equilibration", "sampling"]:
                    path = c.out / "jobs" / job["id"] / "production" / f"attempt-{attempt:02d}" / stage
                    review = read_json(path / "review.json")
                    if not review["hard_pass"] or not review["trajectory_integrity_passed"]:
                        raise RuntimeError("Previously completed production review did not pass")
                    for name, wanted in review["file_sha256"].items():
                        if digest(path / name) != wanted:
                            raise RuntimeError("Previously passed production output changed")
                print("Already completed; no repeat MD", flush=True)
                return
            c.run_job(job, "production")
            c.queue["status"] = job["production"]["status"]
            c.save()
            if job["production"]["status"] != "passed":
                raise NumericalFailure("Bounded retries exhausted")
        except Exception as exc:
            if isinstance(exc, YieldRun):
                c.queue["status"] = "interrupted"
                c.save()
            atomic_json(directory / f"worker-error-{time.time_ns()}.json", {"utc": utc(), "traceback": traceback.format_exc()})
            raise


def collect():
    bundle = manifest()
    counts = Counter()
    tasks = []
    candidates = []
    certificates = {}
    gate_status = {}
    for size in [8, 64, 216]:
        try:
            environment = read_json(ROOT / "outputs/validation" / str(size) / "environment.json")
            certificates[size] = verify_certificate(size, environment)
            gate_status[str(size)] = "passed"
        except Exception as exc:
            gate_status[str(size)] = "not_ready_or_review_failed: " + str(exc)
    for record in bundle["remaining"]:
        ident = record["id"]
        directory = ROOT / "outputs/production" / ident
        status = "not_started"
        path = directory / "queue.json"
        if path.exists():
            q = read_json(path)
            status = q["jobs"][0]["production"]["status"]
            if q.get("hpc_contract", {}).get("manifest_sha256") != digest(ROOT / "manifest.json"):
                status = "identity_mismatch"
            if status == "passed":
                cp = directory / q["jobs"][0]["production"]["final_checkpoint"]
                try:
                    cert = certificates[record["job"]["atoms"]]
                    if (q["hpc_contract"]["environment_sha256"] != cert["environment_sha256"]
                            or q["gates"] != cert["gates"]):
                        raise ValueError("Production no longer matches its validation certificate")
                    for stage in [cp.parent.parent / "equilibration", cp.parent]:
                        review = read_json(stage / "review.json")
                        if not review["hard_pass"] or not review["trajectory_integrity_passed"]:
                            raise ValueError("Review did not pass")
                        for name, wanted in review["file_sha256"].items():
                            if digest(stage / name) != wanted:
                                raise ValueError("Artifact hash changed")
                    candidates.append({"job_id": ident, "source_group": record["job"]["source_group"],
                                       "frames": (cp.parent / "frames.extxyz").relative_to(ROOT).as_posix(),
                                       "label_source": "MACE_prediction_NOT_DFT"})
                except Exception:
                    status = "artifact_review_failed"
        counts[status] += 1
        tasks.append({"job_id": ident, "status": status})
    result = {"validation_status_by_size": gate_status, "local_production_passed": 18, "hpc_status_counts": dict(counts),
              "production_passed_total": 18 + counts["passed"], "expected_total": 162,
              "status": "all_production_numerically_completed" if counts["passed"] == 144 else "incomplete_or_needs_review",
              "tasks": tasks, "physical_validated": False, "equilibrium_certified": False}
    out = ROOT / "outputs"
    atomic_json(out / "summary.json", result)
    atomic_json(out / "candidate-trajectories.json", candidates)
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}, indent=2))
    return 0 if counts["passed"] == 144 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "validate", "produce", "collect"])
    parser.add_argument("--size", type=int, choices=[8, 64, 216])
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    if args.mode == "collect":
        return collect()
    if args.mode == "preflight":
        bundle = manifest()
        if Counter(r["job"]["atoms"] for r in bundle["remaining"]) != {8: 45, 64: 45, 216: 54}:
            raise RuntimeError("Unexpected remaining task matrix")
        if len({r["id"] for r in bundle["remaining"]}) != 144:
            raise RuntimeError("Duplicate remaining tasks")
        check_environment(False)
        print("Environment versions match accepted static check; 144 production tasks, 3 validation jobs.")
        return 0
    if (ROOT / "STOP").exists():
        raise RuntimeError("Bundle STOP marker exists")
    environment = check_environment(True)
    if digest(ROOT / "models/mace-mh-1.model") != manifest()["model_sha256"]:
        raise RuntimeError("Model checksum mismatch")
    if args.mode == "validate":
        validate(args.size, environment)
    else:
        index = args.index if args.index is not None else int(os.environ["SLURM_ARRAY_TASK_ID"])
        produce(args.size, index, environment)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except YieldRun as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(75)
