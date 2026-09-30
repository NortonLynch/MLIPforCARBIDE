"""Sequential, restartable ZrC MACE campaign with bounded retries and gates."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import traceback

import numpy as np
from ase.constraints import FixCom
from ase.io import read, write, iread
from ase.md.velocitydistribution import thermalize_momenta

from zrc_md_engine import (NumericalFailure, YieldRun, atomic_json, load_checkpoint,
                           run_segment, save_checkpoint)
from zrc_md_review import review_segment

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/experiments/zrc_mace_round1.json"


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def job_id(n, t, v, seed):
    return f"zrc{n}_T{t:04d}_v{round(v*100):03d}_s{seed}"


@contextmanager
def worker_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another campaign worker holds the lock") from exc
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Campaign:
    def __init__(self, config_path, output=None):
        self.config_path = Path(config_path).resolve()
        self.cfg = read_json(self.config_path)
        self.out = Path(output).resolve() if output else ROOT / self.cfg["output_dir"]
        self.queue_path = self.out / "queue.json"
        self.calc = None
        self.calc_dtype = None
        self.deadline = None
        self.active = None
        self.stop_file = self.out / "STOP"
        self.queue = read_json(self.queue_path) if self.queue_path.exists() else None

    def initialize(self):
        self.out.mkdir(parents=True, exist_ok=True)
        if self.queue is not None:
            if self.queue["config_sha256"] != digest(self.config_path):
                raise RuntimeError("Campaign config differs from immutable run snapshot")
            return
        if not all(self.cfg["authorization"][key] for key in ["user_approved", "pilot", "production"]):
            raise RuntimeError("The campaign does not authorize both requested stages")
        atomic_json(self.out / "config.snapshot.json", self.cfg)
        self.queue = {"campaign_id": self.cfg["campaign_id"], "created_utc": utc(),
                      "config_sha256": digest(self.config_path), "status": "initialized",
                      "jobs": [], "gates": {}, "physical_validated": False}
        matrix = self.cfg["matrix"]
        base = read(ROOT / self.cfg["structures"]["base_path"], format="vasp")
        for t in matrix["temperatures_K"]:
            for n in matrix["sizes_atoms"]:
                for v in sorted(matrix["volume_scales"], key=lambda v: (abs(v-1), v)):
                    for seed in matrix["seeds"]:
                        ident = job_id(n, t, v, seed)
                        family = f"zrc{n}_v{round(v*100):03d}_s{seed}_heating"
                        atoms = base.repeat(self.cfg["structures"]["repeat_conventional"][str(n)])
                        atoms = atoms[[i for symbol in ["Zr", "C"] for i, atom in enumerate(atoms) if atom.symbol == symbol]]
                        atoms.set_cell(atoms.cell*v**(1/3), scale_atoms=True)
                        assert len(atoms) == n and np.all(atoms.pbc)
                        directory = self.out / "jobs" / ident
                        directory.mkdir(parents=True, exist_ok=True)
                        write(directory / "initial.POSCAR", atoms, format="vasp", direct=True, sort=False)
                        index = matrix["temperatures_K"].index(t)
                        previous = job_id(n, matrix["temperatures_K"][index-1], v, seed) if index else None
                        job = {"id": ident, "atoms": n, "temperature_K": t, "volume_scale": v,
                               "seed": seed, "source_group": family, "parent_pilot_job": previous,
                               "input_sha256": digest(directory / "initial.POSCAR"),
                               "pilot": {"status": "pending", "attempts": []},
                               "production": {"status": "pending", "attempts": []}}
                        self.queue["jobs"].append(job)
                        atomic_json(directory / "job.json", job)
        if len(self.queue["jobs"]) != matrix["expected_jobs"]:
            raise ValueError("Unexpected campaign size")
        policy = {"static_precision_comparison": "relative E/N versus ideal same-composition reference; forces/stress on warm snapshot",
                  "relative_energy_precision_meV_atom": 0.1,
                  "force_component_RMS_precision_eV_A": 0.001,
                  "force_component_max_precision_eV_A": 0.003,
                  "stress_component_max_precision_GPa": 0.01,
                  "nve_drift_limit_meV_atom_ps": self.cfg["validation"]["nve"]["absolute_drift_screen_meV_atom_ps"],
                  "finite_explosive_temperature_guard_K": "max(100000,30*target_T)",
                  "rule": "Never relax thresholds to force a pass. NVT log warnings do not establish equilibration.",
                  "frozen_before_first_MD": True}
        atomic_json(self.out / "validation-policy.json", policy)
        self.save()

    def save(self):
        self.queue["updated_utc"] = utc()
        atomic_json(self.queue_path, self.queue)
        self.report()

    def report(self):
        by_size = {}
        for n in self.cfg["matrix"]["sizes_atoms"]:
            jobs = [j for j in self.queue["jobs"] if j["atoms"] == n]
            by_size[str(n)] = {stage: dict(Counter(j[stage]["status"] for j in jobs)) for stage in ["pilot", "production"]}
        summary = {"campaign_id": self.cfg["campaign_id"], "updated_utc": utc(),
                   "status": self.queue["status"], "total_combinations": len(self.queue["jobs"]),
                   "by_size": by_size,
                   "pilot_passed": sum(j["pilot"]["status"] == "passed" for j in self.queue["jobs"]),
                   "production_passed": sum(j["production"]["status"] == "passed" for j in self.queue["jobs"]),
                   "gates": {key: {k: v for k, v in value.items() if k in ["status", "selected_dt_fs", "selected_dtype", "errors"]}
                             for key, value in self.queue["gates"].items()},
                   "physical_validated": False, "equilibrium_certified": False}
        atomic_json(self.out / "summary.json", summary)
        lines = ["# MACE 首轮 MD 实时进度", "", f"更新时间（UTC）：{summary['updated_utc']}", "",
                 f"状态：{summary['status']}。短测通过 {summary['pilot_passed']}/162；5 ps 平衡 + 10 ps 采样完成并数值审查通过 {summary['production_passed']}/162。", "",
                 "| 原子数 | 短测状态 | 生产段状态 |", "| --- | --- | --- |"]
        for n, counts in by_size.items():
            lines.append(f"| {n} | {counts['pilot']} | {counts['production']} |")
        lines += ["", "每个组合覆盖指定温度、体积和速度种子。passed 仅表示数值完成；不认证热平衡、DFT 精度、相态或扩散系数。",
                  "", "当前运行细节见 runtime.json；所有尝试、自动审查和检查点保存在 jobs/ 与 gates/。"]
        (self.out / "progress.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        return summary

    def progress(self, detail):
        atomic_json(self.out / "runtime.json", {"pid": os.getpid(), "updated_utc": utc(),
                    "active": self.active, **detail})

    def calculator(self, dtype):
        if self.calc is None or self.calc_dtype != dtype:
            import gc
            import torch
            from mace.calculators import MACECalculator
            self.calc = None
            gc.collect()
            torch.cuda.empty_cache()
            self.calc = MACECalculator(model_paths=str(ROOT/self.cfg["model"]["path"]),
                                       device="cuda", default_dtype=dtype, head=self.cfg["model"]["head"])
            self.calc_dtype = dtype
        return self.calc

    def spec(self, job, stage, duration_fs, dt, dtype, ensemble="NVT", **extra):
        md = self.cfg["md"]
        return {"job_id": job["id"], "source_group": job["source_group"], "atoms": job["atoms"],
                "target_temperature_K": job["temperature_K"], "stage": stage, "ensemble": ensemble,
                "expected_duration_fs": duration_fs, "time_step_fs": dt, "dtype": dtype,
                "model_sha256": self.cfg["model"]["sha256"], "head": self.cfg["model"]["head"],
                "versions": {name: importlib.metadata.version(name) for name in ["mace-torch", "torch", "ase", "numpy"]},
                "log_interval_fs": md["log_fs"], "checkpoint_interval_fs": md["checkpoint_fs"],
                "frame_interval_fs": md["frame_fs"], "friction_per_fs": md["friction_per_fs"],
                "nve_drift_limit_meV_atom_ps": self.cfg["validation"]["nve"]["absolute_drift_screen_meV_atom_ps"], **extra}

    def segment(self, atoms, rng, directory, spec):
        review_path = directory / "review.json"
        if review_path.exists():
            review = read_json(review_path)
            if review["hard_pass"]:
                result, result_rng, metadata = load_checkpoint(directory / "checkpoint.npz")
                signature = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
                if metadata["spec_sha256"] != signature:
                    raise RuntimeError("Reviewed segment parameters do not match this invocation")
                for name, expected_hash in review.get("file_sha256", {}).items():
                    if digest(directory/name) != expected_hash:
                        raise RuntimeError("Reviewed segment files changed: " + name)
                return result, result_rng, review
            raise NumericalFailure("Previously completed segment failed its review")
        result, result_rng = run_segment(atoms, rng, self.calculator(spec["dtype"]), directory, spec,
                                          progress=self.progress, deadline=self.deadline, stop_file=self.stop_file)
        review = review_segment(directory, spec)
        frame_times = []
        try:
            for frame in iread(directory/"frames.extxyz", format="extxyz"):
                assert len(frame) == spec["atoms"] and np.all(frame.pbc)
                assert frame.get_chemical_symbols().count("Zr") == spec["atoms"]//2
                assert frame.get_chemical_symbols().count("C") == spec["atoms"]//2
                assert np.isfinite(frame.positions).all() and np.isfinite(frame.get_momenta()).all()
                assert np.isfinite(frame.arrays["model_forces"]).all()
                assert frame.info["label_source"] == "MACE_prediction_NOT_DFT"
                assert frame.info["stage"] == spec["stage"]
                assert np.allclose(frame.cell, result.cell)
                frame_times.append(float(frame.info["time_fs"]))
            expected_times = list(np.arange(0, spec["expected_duration_fs"]+1e-8, spec["frame_interval_fs"]))
            if not np.isclose(expected_times[-1], spec["expected_duration_fs"]):
                expected_times.append(spec["expected_duration_fs"])
            assert len(frame_times) == len(expected_times) and np.allclose(frame_times, expected_times)
            review["trajectory_integrity_passed"] = True
            review["frame_count"] = len(frame_times)
        except Exception as exc:
            review["trajectory_integrity_passed"] = False
            review["hard_pass"] = review["completed_numerically"] = False
            review["errors"].append(f"Trajectory integrity failed: {type(exc).__name__}: {exc}")
        review["file_sha256"] = {name: digest(directory/name) for name in ["log.jsonl", "frames.extxyz", "checkpoint.npz"]}
        atomic_json(review_path, review)
        if not review["hard_pass"]:
            raise NumericalFailure("Segment review failed: " + "; ".join(review["errors"]))
        return result, result_rng, review

    def lookup(self, ident):
        return next(j for j in self.queue["jobs"] if j["id"] == ident)

    def stage_start(self, job, phase):
        saved = self.out / "jobs" / job["id"] / f"{phase}-initial.npz"
        if saved.exists():
            return load_checkpoint(saved)[:2]
        if phase == "production":
            source = self.out / job["pilot"]["final_checkpoint"]
            atoms, rng, _ = load_checkpoint(source)
        elif job["parent_pilot_job"]:
            source = self.out / self.lookup(job["parent_pilot_job"])["pilot"]["final_checkpoint"]
            atoms, rng, _ = load_checkpoint(source)
        else:
            source = self.out / "jobs" / job["id"] / "initial.POSCAR"
            if digest(source) != job["input_sha256"]:
                raise RuntimeError("Initial structure changed")
            atoms = read(source, format="vasp")
            atoms.set_constraint(FixCom())
            rng = np.random.default_rng(np.random.SeedSequence([job["seed"], job["atoms"], round(job["volume_scale"]*100)]))
            thermalize_momenta(atoms, temperature_K=300, rng=rng)
        save_checkpoint(saved, atoms, rng, {"source": str(source), "source_sha256": digest(source),
                                            "job_id": job["id"], "phase": phase, "created_utc": utc()})
        return atoms, rng

    def allowed_attempts(self, job, phase):
        attempts = self.cfg["md"]["attempts"]
        kinds = ["warm", "high"] if phase == "production" else ["warm"]
        gates = [self.queue["gates"].get(f"{kind}_{job['atoms']}") for kind in kinds]
        gates = [g for g in gates if g and g["status"] == "passed"]
        if gates and (phase == "production" or job["temperature_K"] > 3000):
            max_dt = min(g["selected_dt_fs"] for g in gates)
            needs_double = any(g["selected_dtype"] == "float64" for g in gates)
            attempts = [a for a in attempts if a["timestep_fs"] <= max_dt
                        and (not needs_double or a["dtype"] == "float64")]
        return attempts

    def run_job(self, job, phase):
        state = job[phase]
        if state["status"] in ["passed", "blocked_review"]:
            return
        initial, initial_rng = self.stage_start(job, phase)
        options = self.allowed_attempts(job, phase)
        state["status"] = "running"
        self.save()
        for index, option in enumerate(options):
            if index < len(state["attempts"]) and state["attempts"][index]["status"] == "failed":
                continue
            if index == len(state["attempts"]):
                state["attempts"].append({"status": "running", "parameters": option, "started_utc": utc()})
            attempt = state["attempts"][index]
            if attempt["status"] == "interrupted":
                attempt["status"] = "running"
                attempt.setdefault("resume_events", []).append({"utc": utc()})
            directory = self.out / "jobs" / job["id"] / phase / f"attempt-{index+1:02d}"
            directory.mkdir(parents=True, exist_ok=True)
            dt, dtype = option["timestep_fs"], option["dtype"]
            self.active = {"job_id": job["id"], "phase": phase, "attempt": index+1, **option}
            self.save()
            try:
                atoms, rng = initial, initial_rng
                if phase == "pilot":
                    parent_t = self.lookup(job["parent_pilot_job"])["temperature_K"] if job["parent_pilot_job"] else 300
                    if parent_t < job["temperature_K"]:
                        ramp_fs = (job["temperature_K"]-parent_t)/self.cfg["md"]["ramp_K_per_ps"]*1000
                        ramp_fs = round(ramp_fs/dt)*dt
                        spec = self.spec(job, "ramp", ramp_fs, dt, dtype, ramp_start_K=parent_t)
                        atoms, rng, _ = self.segment(atoms, rng, directory/"ramp", spec)
                    stages = [("pilot", self.cfg["md"]["pilot_ps"])]
                else:
                    stages = [("equilibration", self.cfg["md"]["equilibration_ps"]),
                              ("sampling", self.cfg["md"]["sampling_ps"])]
                for stage, duration in stages:
                    spec = self.spec(job, stage, duration*1000, dt, dtype)
                    atoms, rng, review = self.segment(atoms, rng, directory/stage, spec)
                state.update(status="passed", completed_utc=utc(),
                             final_checkpoint=str((directory/stages[-1][0]/"checkpoint.npz").relative_to(self.out)),
                             accepted_parameters=option,
                             last_review=str((directory/stages[-1][0]/"review.json").relative_to(self.out)))
                attempt.update(status="passed", completed_utc=utc())
                print(json.dumps({"event": "job_passed", "job": job["id"], "phase": phase, "parameters": option}), flush=True)
                self.save()
                return
            except YieldRun:
                self.save()
                raise
            except Exception as exc:
                numerical = isinstance(exc, (NumericalFailure, FloatingPointError))
                failed_utc = utc()
                error = f"{type(exc).__name__}: {exc}"
                attempt.update(status="failed" if numerical else "interrupted",
                               completed_utc=failed_utc, error=error)
                record = directory / f"failure-{time.time_ns()}.json"
                failure = {"error": error, "traceback": traceback.format_exc(),
                           "utc": failed_utc, "kind": "numerical" if numerical else "infrastructure"}
                atomic_json(record, failure)
                if not (directory / "failure.json").exists():
                    atomic_json(directory / "failure.json", failure)
                attempt.setdefault("failure_events", []).append({
                    "utc": failed_utc, "kind": failure["kind"], "error": error,
                    "record": str(record.relative_to(self.out))})
                self.save()
                # Input/I/O/programming errors need repair, not a numerical-parameter retry.
                if not numerical:
                    raise
        state["status"] = "blocked_review"
        self.save()

    def precision_check(self, job, atoms, directory):
        target = directory / "static-precision.json"
        if target.exists():
            return read_json(target)
        reference = read(self.out/"jobs"/job["id"]/"initial.POSCAR", format="vasp")
        values = {}
        for dtype in ["float32", "float64"]:
            calc = self.calculator(dtype)
            current = atoms.copy()
            current.calc = calc
            ref = reference.copy()
            ref.calc = calc
            values[dtype] = {"energy_eV_atom": current.get_potential_energy()/len(current),
                             "reference_energy_eV_atom": ref.get_potential_energy()/len(ref),
                             "relative_energy_eV_atom": (current.get_potential_energy()-ref.get_potential_energy())/len(current),
                             "forces": current.get_forces(apply_constraint=False), "stress": current.get_stress()}
            current.calc = None
            ref.calc = None
        force_delta = values["float32"]["forces"]-values["float64"]["forces"]
        result = {"relative_energy_delta_meV_atom": float(abs(values["float32"]["relative_energy_eV_atom"]-values["float64"]["relative_energy_eV_atom"])*1000),
                  "force_component_RMS_eV_A": float(np.sqrt(np.mean(force_delta**2))),
                  "force_component_max_eV_A": float(np.abs(force_delta).max()),
                  "stress_component_max_GPa": float(np.abs(values["float32"]["stress"]-values["float64"]["stress"]).max()*160.21766208)}
        result["energy_diagnostics"] = {dtype: {key: float(value) for key, value in item.items()
                                                       if key in ["energy_eV_atom", "reference_energy_eV_atom", "relative_energy_eV_atom"]}
                                         for dtype, item in values.items()}
        result["float32_pass"] = all([result["relative_energy_delta_meV_atom"] <= .1,
                                       result["force_component_RMS_eV_A"] <= .001,
                                       result["force_component_max_eV_A"] <= .003,
                                       result["stress_component_max_GPa"] <= .01])
        atomic_json(target, result)
        return result

    def run_gate(self, n, kind):
        key = f"{kind}_{n}"
        state = self.queue["gates"].setdefault(key, {"status": "pending"})
        if state["status"] in ["passed", "blocked_review"]:
            return
        temperature = 3000 if kind == "warm" else 6000
        job = self.lookup(job_id(n, temperature, 1.0, 17))
        if job["pilot"]["status"] != "passed":
            return
        directory = self.out / "gates" / key
        directory.mkdir(parents=True, exist_ok=True)
        self.active = {"gate": key, "phase": "precision_and_NVE"}
        state["status"] = "running"
        self.save()
        self.progress({"segment": str(directory), "step": 0, "steps": None})
        source = self.out / job["pilot"]["final_checkpoint"]
        atoms, rng, _ = load_checkpoint(source)
        state["initial_checkpoint"] = str(source.relative_to(self.out))
        state["initial_sha256"] = digest(source)
        precision = self.precision_check(job, atoms, directory)
        state["static_precision"] = precision
        dtypes = ["float32", "float64"] if precision["float32_pass"] else ["float64"]
        errors = []
        for dtype in dtypes:
            results = {}
            for dt in self.cfg["validation"]["nve"]["timesteps_fs"]:
                name = f"nve_{dtype}_dt{str(dt).replace('.', 'p')}"
                spec = self.spec(job, "nve", self.cfg["validation"]["nve"]["duration_ps"]*1000, dt, dtype, ensemble="NVE")
                try:
                    _, _, review = self.segment(atoms, rng, directory/name, spec)
                    results[dt] = review
                except NumericalFailure as exc:
                    errors.append(f"{dtype}, {dt} fs: {exc}")
                    results[dt] = {"hard_pass": False}
            # Always calculate both branches. Prefer the tested 0.5 fs only when both pass.
            if results.get(.25, {}).get("hard_pass"):
                selected = .5 if results.get(.5, {}).get("hard_pass") and dtype == "float32" else .25
                state.update(status="passed", selected_dt_fs=selected, selected_dtype=dtype,
                             completed_utc=utc(), errors=errors,
                             qualification="numerical_screen_only_not_physical_validation")
                self.save()
                return
        state.update(status="blocked_review", errors=errors)
        self.save()

    def finish_requested_job(self):
        """Honor a persistent user limit without dispatching another job."""
        request_path = self.out / "FINISH_CURRENT_JOB.json"
        if not request_path.exists():
            return False
        request = read_json(request_path)
        if request.get("phase") != "production" or request.get("allow_remaining_matrix") is not False:
            raise RuntimeError("Invalid finish-current-job request; refusing to dispatch")
        matches = [job for job in self.queue["jobs"] if job["id"] == request.get("job_id")]
        if len(matches) != 1:
            raise RuntimeError("Finish-current-job target is missing or ambiguous")
        if not all(job["pilot"]["status"] == "passed" for job in self.queue["jobs"]):
            raise RuntimeError("Finish-current-job production requires all pilots passed")
        if any(self.queue["gates"].get(f"{kind}_{n}", {}).get("status") != "passed"
               for n in self.cfg["matrix"]["sizes_atoms"] for kind in ["warm", "high"]):
            raise RuntimeError("Finish-current-job production gates are not passed")
        job = matches[0]
        self.run_job(job, "production")
        completion = {**request, "stopped_utc": utc(), "target_status": job["production"]["status"]}
        atomic_json(self.out / "finish-current-job-result.json", completion)
        self.stop_file.write_text("User requested local stop after " + job["id"] +
                                  "; remaining work reserved for cluster.\n", encoding="utf-8")
        self.queue["status"] = "stopped_by_marker"
        self.queue["stop_after_job"] = completion
        self.save()
        return True

    def run(self, max_wall_seconds=None):
        self.initialize()
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        if digest(ROOT/self.cfg["model"]["path"]) != self.cfg["model"]["sha256"]:
            raise RuntimeError("Model identity mismatch")
        if importlib.metadata.version("mace-torch") != self.cfg["model"]["mace_torch_version"]:
            raise RuntimeError("MACE package version changed")
        torch.set_num_threads(4)
        self.deadline = time.monotonic()+max_wall_seconds if max_wall_seconds else None
        self.queue["status"] = "running"
        self.save()
        atomic_json(self.out/"worker.json", {"pid": os.getpid(), "started_utc": utc(),
                    "script": str(Path(__file__).resolve()), "config": str(self.config_path),
                    "gpu": torch.cuda.get_device_name(0), "versions": {name: importlib.metadata.version(name) for name in ["mace-torch", "torch", "ase", "numpy"]}})
        try:
            if self.finish_requested_job():
                return
            for job in self.queue["jobs"]:
                if job["pilot"]["status"] == "passed":
                    continue
                parent = job["parent_pilot_job"]
                if parent and self.lookup(parent)["pilot"]["status"] != "passed":
                    continue
                if job["temperature_K"] > 3000:
                    self.run_gate(job["atoms"], "warm")
                    if self.queue["gates"].get(f"warm_{job['atoms']}", {}).get("status") != "passed":
                        continue
                self.run_job(job, "pilot")
            # All declared pilots must pass before production begins.
            if not all(j["pilot"]["status"] == "passed" for j in self.queue["jobs"]):
                self.queue["status"] = "needs_review"
                self.save()
                return
            for n in self.cfg["matrix"]["sizes_atoms"]:
                self.run_gate(n, "warm")
                self.run_gate(n, "high")
            if any(self.queue["gates"].get(f"{kind}_{n}", {}).get("status") != "passed"
                   for n in self.cfg["matrix"]["sizes_atoms"] for kind in ["warm", "high"]):
                self.queue["status"] = "needs_review"
                self.save()
                return
            for job in self.queue["jobs"]:
                if any(self.queue["gates"].get(f"{kind}_{job['atoms']}", {}).get("status") != "passed" for kind in ["warm", "high"]):
                    continue
                self.run_job(job, "production")
            self.queue["status"] = "complete_numerical" if all(j["production"]["status"] == "passed" for j in self.queue["jobs"]) else "needs_review"
            self.save()
        except YieldRun:
            self.queue["status"] = "stopped_by_marker" if self.stop_file.exists() else "yielded_checkpointed"
            self.save()
        except Exception:
            self.queue["status"] = "worker_error"
            atomic_json(self.out/"worker-error.json", {"utc": utc(), "active": self.active, "traceback": traceback.format_exc()})
            self.save()
            raise
        finally:
            self.progress({"worker_exited": True, "status": self.queue["status"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "status", "run"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args()
    campaign = Campaign(args.config, args.output)
    if args.command == "status":
        if not campaign.queue:
            print(json.dumps({"status": "not_initialized"}))
            return
        summary = read_json(campaign.out/"summary.json")
        runtime = campaign.out/"runtime.json"
        if runtime.exists():
            summary["runtime"] = read_json(runtime)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    with worker_lock(campaign.out):
        if args.command == "init":
            campaign.initialize()
            print(json.dumps(campaign.report(), ensure_ascii=False))
        else:
            campaign.run(args.max_wall_seconds)


if __name__ == "__main__":
    main()
