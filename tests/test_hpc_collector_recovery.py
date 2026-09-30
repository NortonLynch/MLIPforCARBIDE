"""Mock-only regression checks; never calls a real scheduler."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = Path("C:/Program Files/Git/bin/bash.exe")

@unittest.skipUnless(BASH.exists(), "Git Bash unavailable")
@unittest.skipUnless((ROOT / "hpc/submit_review_only.sh").exists(),
                     "Retired collector-only script removed in the 2026-09-24 cleanup; historical checks are in hpc/reviews/collector-submission")
class CollectorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="collector_recovery_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "submissions").mkdir()
        shutil.copyfile(ROOT / "hpc/submit_review_only.sh", self.root / "submit_review_only.sh")
        (self.root / "manifest.json").write_text("{}")
        (self.root / "worker.sh").write_text("# synthetic test worker")
        sums = "".join(hashlib.sha256((self.root/n).read_bytes()).hexdigest()+"  "+n+"\n"
                       for n in ["manifest.json", "worker.sh"])
        (self.root / "SHA256SUMS").write_text(sums, newline="\n")
        self.lines = [f"batch1\t{role}\t{size}\t{15326756+i}\n" for i,(role,size) in enumerate(
            [(r,s) for s in [8,64,216] for r in ["validate","production"]])]
        self.ledger = self.root / "submissions/jobs.tsv"
        self.ledger.write_text("".join(self.lines), newline="\n")
        for name,code in {
            "flock":"exit 0\n",
            "sbatch":'printf "%s\\n" "$*" >> mock-calls\nif [[ ${TEST_REJECT:-0} == 1 ]]; then echo "Memory specification can not be satisfied" >&2; exit 1; fi\necho 15326762\n'
        }.items():
            p=self.bin/name
            p.write_text("#!/usr/bin/env bash\n"+code,newline="\n")
            p.chmod(0o755)
    def invoke(self, reject=False):
        env=os.environ.copy()
        env["TEST_REJECT"]="1" if reject else "0"
        prefix=self.bin.as_posix()
        return subprocess.run([str(BASH),"-c",f'export PATH="$(cygpath -u "{prefix}"):$PATH"; bash submit_review_only.sh'],cwd=self.root,env=env,text=True,capture_output=True)
    def test_failed_submit_preserves_ledger_then_only_collector_and_no_duplicates(self):
        original=self.ledger.read_bytes()
        result=self.invoke(True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Existing MD jobs and ledger are unchanged",result.stderr)
        self.assertEqual(self.ledger.read_bytes(),original)
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        calls=(self.root/"mock-calls").read_text().splitlines()
        self.assertEqual(len(calls),2)
        self.assertIn("--dependency=afterany:15326756:15326757:15326758:15326759:15326760:15326761",calls[-1])
        self.assertNotIn("--mem",calls[-1])
        self.assertNotIn("--gres",calls[-1])
        self.assertNotIn("--array",calls[-1])
        self.assertTrue(calls[-1].endswith("worker.sh collect"))
        self.assertTrue(self.ledger.read_text().endswith("batch1\tcollect\tall\t15326762\n"))
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(len((self.root/"mock-calls").read_text().splitlines()),2)
    def test_incomplete_ledger_does_not_submit(self):
        self.ledger.write_text("".join(self.lines[:-1]),newline="\n")
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertFalse((self.root/"mock-calls").exists())

if __name__ == "__main__": unittest.main()
