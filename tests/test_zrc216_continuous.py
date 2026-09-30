"""CPU/synthetic checks for the explicit no-resume production protocol."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_zrc216_continuous as new
from zrc_md_engine import atomic_json,load_checkpoint,NumericalFailure
from hpc_fixtures import ARCHIVE, prepare_bundle

class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='continuous_test_');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        m=prepare_bundle(self.root,'zrc216-continuous',216,300,1)
        self.record=m['remaining'][0]
        self.env={'synthetic_test':True};self.gates={}
        for target,name,value in [(new,'ROOT',self.root),(new.old,'ROOT',self.root)]:
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        for p in [patch.object(new,'verify_numeric_authorization',return_value=self.gates),
                  patch.object(new.ContinuousCampaign,'configure_signals'),
                  patch('importlib.metadata.version',return_value='synthetic_test')]:
            p.start();self.addCleanup(p.stop)
        self.calls=[];self.fail_stage=None;self.numerical=False
    def fake_segment(self,c,atoms,rng,directory,spec):
        self.calls.append((spec['stage'],atoms.positions.copy(),rng.bit_generator.state))
        directory.mkdir(parents=True)
        (directory/'checkpoint.npz').write_bytes(b'synthetic checkpoint: never load this')
        if spec['stage']==self.fail_stage:
            self.fail_stage=None
            if self.numerical:raise NumericalFailure('synthetic numerical failure')
            raise OSError('synthetic infrastructure interruption')
        frame=directory/'frames.extxyz';frame.write_text('synthetic test only')
        review={'hard_pass':True,'trajectory_integrity_passed':True,
                'metrics':{'observed_duration_fs':spec['expected_duration_fs']},
                'file_sha256':{'frames.extxyz':new.digest(frame),'checkpoint.npz':new.digest(directory/'checkpoint.npz')}}
        atomic_json(directory/'review.json',review)
        moved=atoms.copy();moved.positions+=.001
        rng.random()
        return moved,rng,review
    def run_task(self):
        test=self
        with patch.object(new.ContinuousCampaign,'segment',lambda c,*a,**k:test.fake_segment(c,*a,**k)):
            new.produce(0,self.env)
    def test_in_memory_handoff_complete_skip(self):
        self.run_task()
        self.assertEqual([r[0] for r in self.calls],['equilibration','sampling'])
        np.testing.assert_allclose(self.calls[1][1],self.calls[0][1]+.001)
        self.assertNotEqual(self.calls[0][2],self.calls[1][2])
        self.run_task();self.assertEqual(len(self.calls),2)
    def test_interruption_restarts_entire_task_and_preserves_old_attempt(self):
        self.fail_stage='sampling'
        with self.assertRaises(OSError):self.run_task()
        d=self.root/'outputs/production'/self.record['id']
        old_cp=d/'run-0001/jobs'/self.record['id']/'production/equilibration/checkpoint.npz'
        saved=old_cp.read_bytes()
        self.run_task()
        self.assertEqual([r[0] for r in self.calls],['equilibration','sampling','equilibration','sampling'])
        np.testing.assert_array_equal(self.calls[0][1],self.calls[2][1])
        self.assertEqual(self.calls[0][2],self.calls[2][2])
        self.assertEqual(old_cp.read_bytes(),saved)
        q=new.read_json(d/'task.json');self.assertEqual(len(q['attempts']),2)
        self.assertEqual(q['attempts'][0]['status'],'interrupted_restart_from_pilot')
        self.assertEqual(q['status'],'passed')
    def test_numerical_failure_stays_blocked(self):
        self.fail_stage='equilibration';self.numerical=True
        with self.assertRaises(NumericalFailure):self.run_task()
        with self.assertRaises(NumericalFailure):self.run_task()
        self.assertEqual(len(self.calls),1)
    def test_existing_production_checkpoint_cannot_resume(self):
        p=self.root/'old';p.mkdir();(p/'checkpoint.npz').write_bytes(b'old')
        with self.assertRaisesRegex(RuntimeError,'refuses'):
            new.ContinuousCampaign.segment(None,None,None,p,{})
    def test_user_stop_blocks_start(self):
        (self.root/'STOP').write_text('user')
        with self.assertRaises(new.YieldRun):self.run_task()
        self.assertEqual(self.calls,[])

class SubmissionTests(unittest.TestCase):
    def test_only_54_production_tasks_and_overlap_protection(self):
        bash=Path('C:/Program Files/Git/bin/bash.exe')
        if not bash.exists():self.skipTest('Git Bash missing')
        with tempfile.TemporaryDirectory(prefix='continuous_slurm_') as tmp:
            root=Path(tmp);binary=root/'bin';binary.mkdir();(root/'provenance').mkdir()
            shutil.copyfile(ARCHIVE/'zrc216-continuous/submit_all.sh',root/'submit_all.sh')
            (root/'provenance/previous-jobs.tsv').write_text('batch\tvalidate\t216\t15326760\n',newline='\n')
            scripts={'fake-python':'exit 0\n','flock':'exit 0\n',
                     'realpath':'if [[ "$1" == */WORK ]]; then pwd; else /usr/bin/realpath "$@"; fi\n',
                     'squeue':'echo "${TEST_ACTIVE:-}"\n',
                     'sbatch':'printf "%s\\n" "$*" >> mock-calls\n[[ ${TEST_REJECT:-0} == 0 ]] || exit 1\necho 20000001\n'}
            for name,body in scripts.items():
                p=binary/name;p.write_text('#!/usr/bin/env bash\n'+body,newline='\n');p.chmod(0o755)
            def invoke(args='',active='',reject='0'):
                env=os.environ.copy();env['MACE_PYTHON']=(binary/'fake-python').as_posix();env['TEST_ACTIVE']=active;env['TEST_REJECT']=reject
                return subprocess.run([str(bash),'-c',f'export PATH="$(cygpath -u "{binary.as_posix()}"):$PATH"; bash submit_all.sh {args}'],cwd=root,env=env,text=True,capture_output=True)
            self.assertEqual(invoke('--plan').returncode,0);self.assertFalse((root/'mock-calls').exists())
            self.assertNotEqual(invoke(active='15326760').returncode,0);self.assertFalse((root/'mock-calls').exists())
            self.assertNotEqual(invoke(reject='1').returncode,0);self.assertFalse((root/'submissions/jobs.tsv').exists())
            result=invoke();self.assertEqual(result.returncode,0,result.stderr)
            calls=(root/'mock-calls').read_text().splitlines();self.assertEqual(len(calls),2)
            self.assertIn('--array=0-53%4',calls[-1]);self.assertIn('--gres=gpu:1',calls[-1]);self.assertNotIn('--dependency',calls[-1])
            self.assertNotEqual(invoke().returncode,0)
            self.assertNotEqual(invoke('--retry-from-start',active='20000001').returncode,0)
            self.assertEqual(invoke('--retry-from-start').returncode,0)

if __name__=='__main__':unittest.main()
