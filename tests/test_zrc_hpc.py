"""CPU-only migration and submission checks; no MACE/GPU calculations."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import numpy as np
from ase.calculators.calculator import Calculator, all_changes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_zrc_hpc as hpc
from zrc_md_engine import load_checkpoint, atomic_json
from hpc_fixtures import ARCHIVE, prepare_bundle

class Harmonic(Calculator):
    implemented_properties = ["energy", "forces", "stress"]
    def __init__(self, positions):
        super().__init__()
        self.reference = positions.copy()
    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        delta = self.atoms.positions - self.reference
        self.results = {"energy": float(.1 * np.sum(delta**2)), "forces": -.2 * delta, "stress": np.zeros(6)}

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic_hpc_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = prepare_bundle(self.root, "zrc-round1-remaining", 8, 3000, 2)
        self.records = self.manifest["remaining"]
        self.env = {"synthetic_cpu_test": True}
        versions = patch("importlib.metadata.version", return_value="synthetic_test_version")
        versions.start(); self.addCleanup(versions.stop)
        self.patch = patch.object(hpc, "ROOT", self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
    def campaign(self, name="first", records=None, env=None):
        return hpc.IsolatedCampaign(self.root / name, records or self.records[:1], "test", env or self.env)
    def test_initial_state_preserves_positions_momenta_rng(self):
        c = self.campaign(); record = self.records[0]
        a, rng, _ = load_checkpoint(self.root / record["checkpoint_path"])
        actual, actual_rng = c.stage_start(c.queue["jobs"][0], "production")
        np.testing.assert_array_equal(a.positions, actual.positions)
        np.testing.assert_array_equal(a.get_momenta(), actual.get_momenta())
        np.testing.assert_array_equal(a.cell.array, actual.cell.array)
        self.assertEqual(rng.bit_generator.state, actual_rng.bit_generator.state)
        self.assertEqual(actual.get_number_of_degrees_of_freedom(), 3*len(actual)-3)
    def test_workers_do_not_share_queues(self):
        a = self.campaign("a", self.records[:1]); b = self.campaign("b", self.records[1:])
        a.queue["jobs"][0]["production"]["status"] = "passed"; a.save()
        self.assertEqual(hpc.read_json(b.queue_path)["jobs"][0]["production"]["status"], "pending")
        self.assertNotEqual(a.queue["jobs"][0]["id"],b.queue["jobs"][0]["id"])
    def test_environment_change_cannot_resume(self):
        self.campaign()
        with self.assertRaisesRegex(RuntimeError,"different bundle/environment/task"):
            self.campaign(env={"changed": True})
    def test_changed_packaged_checkpoint_is_rejected(self):
        path = self.root / self.records[0]["checkpoint_path"]
        path.write_bytes(path.read_bytes()+b"changed")
        with self.assertRaisesRegex(RuntimeError,"Changed packaged source"):
            self.campaign()
    def test_missing_certificate_prevents_production_dispatch(self):
        with patch.object(hpc.IsolatedCampaign,"run_job") as mocked:
            with self.assertRaises(FileNotFoundError): hpc.produce(8,0,self.env)
            mocked.assert_not_called()
    def test_certificate_artifact_tamper_is_rejected(self):
        folder=self.root / "outputs/validation/8"; folder.mkdir(parents=True)
        (folder / "artifact").write_text("original")
        cert={"status":"passed", "manifest_sha256":hpc.digest(self.root / "manifest.json"),
              "environment_sha256":hpc.identity(self.env),"gates":{"warm_8":{"status":"passed"},"high_8":{"status":"passed"}},
              "artifacts":{"artifact":hpc.digest(folder / "artifact")}}
        atomic_json(folder / "ready.json",cert)
        self.assertEqual(hpc.verify_certificate(8,self.env),cert)
        (folder / "artifact").write_text("changed")
        with self.assertRaisesRegex(RuntimeError,"artifact changed"): hpc.verify_certificate(8,self.env)
    def test_global_stop_prevents_start(self):
        c=self.campaign(); (self.root / "STOP").write_text("User stop")
        with self.assertRaises(hpc.YieldRun): hpc.assert_running_allowed(c)
    def test_restart_check_actually_interrupts_and_restores_rng(self):
        c=self.campaign(); job=c.queue["jobs"][0]
        atoms,_,_=load_checkpoint(self.root / self.records[0]["checkpoint_path"])
        c.calculator=Mock(return_value=Harmonic(atoms.positions))
        hpc.restart_check(c,job,{"selected_dt_fs":.5,"selected_dtype":"float32"})
        out=c.out / "restart" / job["id"]
        self.assertEqual(hpc.read_json(out / "interruption.json")["time_fs"],50)
        report=hpc.read_json(out / "review.json")
        self.assertEqual(report["status"],"passed")
        self.assertTrue(report["identical_rng_state"])
        self.assertLessEqual(report["max_position_difference_A"],1e-12)
        before=(out / "resumed/frames.extxyz").read_bytes()
        hpc.restart_check(c,job,{"selected_dt_fs":.5,"selected_dtype":"float32"})
        self.assertEqual(before,(out / "resumed/frames.extxyz").read_bytes())

class SubmissionTests(unittest.TestCase):
    def test_submission_dependencies_and_duplicate_protection(self):
        bash=Path(r"C:/Program Files/Git/bin/bash.exe")
        if not bash.exists(): self.skipTest("Git Bash unavailable")
        with tempfile.TemporaryDirectory(prefix="synthetic_slurm_") as tmp:
            root=Path(tmp); binary=root / "bin"; binary.mkdir()
            source=ARCHIVE / "zrc-round1-remaining"
            shutil.copyfile(source / "submit_all.sh",root / "submit_all.sh")
            (root / "test-input").write_text("synthetic")
            (root / "SHA256SUMS").write_text(hpc.digest(root / "test-input")+"  test-input\n",newline="\n")
            def script(name,content):
                p=binary / name;p.write_text("#!/usr/bin/env bash\n"+content,newline="\n");p.chmod(0o755)
            script("fake-python","exit 0\n")
            script("flock","exit 0\n")
            # Override only test helper outputs; never modify HOME or use real sbatch.
            script("realpath",'if [[ "$1" == */WORK ]]; then pwd; else /usr/bin/realpath "$@"; fi\n')
            script("squeue",'if [[ -n ${TEST_ACTIVE:-} ]]; then echo "$TEST_ACTIVE"; fi\n')
            script("sbatch","""n=1000
[[ ! -f mock-count ]] || n=$(cat mock-count)
n=$((n+1))
echo "$n" > mock-count
printf '%s\n' "$*" >> mock-calls
echo "$n"
""")
            env=os.environ.copy();env["MACE_PYTHON"]=(binary / "fake-python").as_posix()
            prefix=binary.as_posix()
            def invoke(extra="",active=None):
                e=env.copy()
                if active: e["TEST_ACTIVE"]=active
                return subprocess.run([str(bash),"-c",f'export PATH="$(cygpath -u "{prefix}"):$PATH"; bash submit_all.sh {extra}'],cwd=root,env=e,capture_output=True,text=True)
            result=invoke()
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            calls=(root / "mock-calls").read_text().splitlines()
            self.assertEqual(len(calls),7)
            self.assertIn("--array=0-44%2",calls[1]);self.assertIn("--dependency=afterok:1001",calls[1])
            self.assertIn("--array=0-44%2",calls[3]);self.assertIn("--dependency=afterok:1003",calls[3])
            self.assertIn("--array=0-53%4",calls[5]);self.assertIn("--dependency=afterok:1005",calls[5])
            self.assertIn("--dependency=afterany:1001:1002:1003:1004:1005:1006",calls[6])
            self.assertNotIn("--gres",calls[6])
            self.assertNotEqual(invoke().returncode,0)
            self.assertNotEqual(invoke("--resume",active="1002").returncode,0)
            self.assertEqual(len((root / "mock-calls").read_text().splitlines()),7)
            resumed=invoke("--resume")
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)

if __name__ == "__main__": unittest.main()
