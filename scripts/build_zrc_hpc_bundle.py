"""Build portable remaining-task inputs from accepted local checkpoints."""
from pathlib import Path
import hashlib
import json
import shutil
import tarfile
from collections import Counter
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hpc/zrc-round1-remaining"
SOURCE = ROOT / "experiments/zrc_mace_round1"

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))

def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

def build():
    queue = read(SOURCE / "queue.json")
    assert (SOURCE / "STOP").exists() and read(SOURCE / "runtime.json")["worker_exited"]
    assert len(queue["jobs"]) == 162 and all(j["pilot"]["status"] == "passed" for j in queue["jobs"])
    assert len(queue["gates"]) == 6 and all(g["status"] == "passed" for g in queue["gates"].values())
    remaining = [j for j in queue["jobs"] if j["production"]["status"] != "passed"]
    completed = [j for j in queue["jobs"] if j["production"]["status"] == "passed"]
    assert len(completed) == 18 and len(remaining) == 144
    assert all(j["production"]["status"] == "pending" and not j["production"]["attempts"] for j in remaining)
    assert Counter(j["atoms"] for j in remaining) == {8: 45, 64: 45, 216: 54}
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ["run_zrc_hpc.py", "run_zrc_md_campaign.py", "zrc_md_engine.py", "zrc_md_review.py"]:
        copy(ROOT / "scripts" / name, OUT / "scripts" / name)
    copy(ROOT / "configs/experiments/zrc_mace_round1.json", OUT / "configs/experiments/zrc_mace_round1.json")
    copy(ROOT / "models/mace-mh-1.model", OUT / "models/mace-mh-1.model")
    for name in ["summary.json", "queue.json", "validation-policy.json", "finish-current-job-result.json"]:
        copy(SOURCE / name, OUT / "provenance" / ("local-" + name))
    # Preserve the completed static HPC acceptance, independently of the old setup folder.
    review = ROOT / "hpc/reviews/15325225"
    if review.exists():
        for name in ["review.json", "review.md"]:
            copy(review / name, OUT / "provenance" / ("hpc-15325225-" + name))
    setup = ROOT / "hpc/zrc-ase-v100-setup"
    for name in ["gpu-15325225.json", "mace-check-15325225.out"]:
        if (setup / name).exists():
            copy(setup / name, OUT / "provenance" / name)
    hpc_versions = read(OUT / "provenance/gpu-15325225.json")["versions"]
    records = []
    for j in remaining:
        # queue paths are Windows-origin strings; normalize explicitly for the source reader.
        cp = SOURCE / Path(j["pilot"]["final_checkpoint"].replace("\\", "/"))
        report = read(cp.with_name("review.json"))
        assert report["hard_pass"] and report["trajectory_integrity_passed"]
        assert sha(cp) == report["file_sha256"]["checkpoint.npz"]
        initial = SOURCE / "jobs" / j["id"] / "initial.POSCAR"
        assert sha(initial) == j["input_sha256"]
        with np.load(cp, allow_pickle=False) as data:
            meta = json.loads(str(data["metadata"]))
            assert meta["spec"]["job_id"] == j["id"] and meta["spec"]["stage"] == "pilot"
            assert meta["step"] * meta["spec"]["time_step_fs"] == 500
            assert len(data["numbers"]) == j["atoms"] and "rng_state" in meta
            assert np.isfinite(data["positions"]).all() and np.isfinite(data["momenta"]).all()
        rel = Path("inputs") / j["id"]
        copy(cp, OUT / rel / "pilot.npz")
        copy(initial, OUT / rel / "initial.POSCAR")
        copy(cp.with_name("review.json"), OUT / rel / "pilot-review.json")
        job = {k: j[k] for k in ["id", "atoms", "temperature_K", "volume_scale", "seed", "source_group", "parent_pilot_job", "input_sha256"]}
        job["pilot"] = {"status": "passed", "accepted_parameters": j["pilot"]["accepted_parameters"],
                        "completed_utc": j["pilot"]["completed_utc"]}
        records.append({"id": j["id"], "job": job, "checkpoint_path": (rel / "pilot.npz").as_posix(),
                        "checkpoint_sha256": sha(cp), "initial_path": (rel / "initial.POSCAR").as_posix(),
                        "initial_sha256": sha(initial), "source_review_sha256": sha(cp.with_name("review.json")),
                        "migration_semantics": "new_production_branch_from_own_accepted_pilot_with_exact_state_and_rng"})
    excluded = []
    for j in completed:
        cp = SOURCE / Path(j["production"]["final_checkpoint"].replace("\\", "/"))
        for stage in [cp.parent.parent / "equilibration", cp.parent]:
            report = read(stage / "review.json")
            assert report["hard_pass"] and report["trajectory_integrity_passed"]
            for name, wanted in report["file_sha256"].items():
                assert sha(stage / name) == wanted
        excluded.append({"id": j["id"], "status": "passed_locally_excluded_from_submission", "final_checkpoint_sha256": sha(cp)})
    value = {"schema_version": 1, "campaign_id": "zrc-round1-hpc-remaining-144",
             "model_sha256": sha(OUT / "models/mace-mh-1.model"), "hpc_versions": hpc_versions,
             "remaining": records, "excluded_completed": excluded,
             "source_queue_sha256": sha(SOURCE / "queue.json"),
             "restart_check": {"duration_fs": 100.0, "interrupt_fs": 50.0,
                               "position_atol_A": 1e-6, "momentum_atol_ASE": 1e-5,
                               "rng_must_match_exactly": True,
                               "thresholds_fixed_before_hpc_execution": True},
             "physical_validated": False}
    (OUT / "manifest.json").write_text(json.dumps(value,indent=2),encoding="utf-8",newline="\n")
    table = ["array_size\tarray_index\tjob_id\tatoms\ttemperature_K\tvolume_scale\tseed"]
    for n in [8,64,216]:
        for index, record in enumerate(r for r in records if r["job"]["atoms"] == n):
            j = record["job"]
            table.append(f"{n}\t{index}\t{j['id']}\t{n}\t{j['temperature_K']}\t{j['volume_scale']}\t{j['seed']}")
    (OUT / "tasks.tsv").write_text("\n".join(table)+"\n",encoding="utf-8",newline="\n")
    allowed = [p for p in OUT.rglob("*") if p.is_file() and p.name != "SHA256SUMS"
               and p.relative_to(OUT).parts[0] not in ["outputs", "logs", "submissions", "__pycache__"]
               and "__pycache__" not in p.parts]
    (OUT / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(OUT).as_posix()}\n" for p in sorted(allowed)),encoding="utf-8",newline="\n")
    archive = ROOT / "hpc/zrc-round1-remaining.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        for p in sorted(allowed + [OUT / "SHA256SUMS"]):
            info = tar.gettarinfo(str(p),arcname="zrc-round1-remaining/"+p.relative_to(OUT).as_posix())
            info.mode = 0o755 if p.suffix == ".sh" else 0o644
            with p.open("rb") as stream:
                tar.addfile(info,stream)
    archive.with_suffix(".tgz.sha256").write_text(f"{sha(archive)}  {archive.name}\n",encoding="utf-8",newline="\n")
    print(json.dumps({"tasks":len(records), "excluded":len(excluded), "files":len(allowed)+1,
                      "archive_bytes":archive.stat().st_size, "sha256":sha(archive)},indent=2))

if __name__ == "__main__":
    build()
