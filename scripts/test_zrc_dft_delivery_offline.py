"""Offline behavior checks using mocked Slurm/MPI/VASP, never the real executables."""
from pathlib import Path
import shutil,subprocess,os,json,hashlib,time
ROOT=Path(__file__).resolve().parents[1];BASH=r'C:\Program Files\Git\bin\bash.exe'
SCRATCH=ROOT/'tmp'/f'zrc-dft600-k67-offline-tests-{time.time_ns()}'
assert SCRATCH.resolve().is_relative_to((ROOT/'tmp').resolve())
if SCRATCH.exists():raise RuntimeError('Test scratch already exists; preserve it for inspection.')
base=SCRATCH/'bundle';shutil.copytree(ROOT/'dft/jobs/05_md_kmesh600',base)
mock=SCRATCH/'mock-bin';mock.mkdir();results=[]
def put(p,s):p.write_text(s,encoding='utf-8',newline='\n')
put(mock/'sbatch','''#!/bin/bash
printf '%s\\n' "$@" >> "$MOCK_CALLS"
if [[ ${MOCK_SBATCH_FAIL:-0} == 1 ]]; then echo 'simulated rejection' >&2; exit 1; fi
printf '90001\\n'
''')
put(mock/'mpirun','''#!/bin/bash
[[ $1 == -np && $2 == 56 ]] || exit 98
shift 2
exec "$@"
''')
put(mock/'vasp_std','''#!/bin/bash
if [[ ${MOCK_BAD_SCF:-0} == 1 ]]; then
    printf 'General timing and accounting\\n' > OUTCAR
else
    printf 'aborting loop because EDIFF is reached\\nGeneral timing and accounting\\n' > OUTCAR
fi
printf '<modeling></modeling>\\n' > vasprun.xml
printf 'OFFLINE MOCK ONLY; not a scientific calculation\\n'
''')
put(mock/'squeue','''#!/bin/bash
if [[ ${MOCK_ACTIVE:-0} == 1 ]]; then printf '90001\\n'; fi
''')
env=os.environ.copy();env['MOCK_CALLS']=str(SCRATCH/'sbatch-calls.txt').replace('\\','/');env['MOCK_DIR']=str(mock).replace('\\','/')
def run(script,args='',extra=None,rc=0):
 e=env.copy();e.update(extra or {})
 command='export PATH="$(cygpath -u "$MOCK_DIR"):$PATH"; module() { :; }; export -f module; bash '+script+' '+args
 r=subprocess.run([BASH,'--noprofile','--norc','-c',command],cwd=base,env=e,capture_output=True,text=True,encoding="utf-8",errors="replace")
 if r.returncode!=rc:raise AssertionError((script,args,r.returncode,r.stdout,r.stderr))
 return r
for p in list(base.glob('*.sh'))+list(base.glob('*.slurm')):
 r=subprocess.run([BASH,'-n',str(p)],capture_output=True,text=True,encoding="utf-8",errors="replace");assert r.returncode==0,r.stderr
results.append('Bash syntax of all five launch/return scripts')
run('submit_all.sh','--dry-run');assert not (base/'submissions').exists();assert not (SCRATCH/'sbatch-calls.txt').exists()
results.append('Dry run makes no submission or submission-state files')
run('submit_all.sh',extra={'MOCK_SBATCH_FAIL':'1'},rc=1);assert not (base/'submissions/all-job-id.txt').exists()
results.append('Scheduler rejection does not record a submitted array')
run('submit_all.sh');assert (base/'submissions/all-job-id.txt').read_text().strip()=='90001'
calls=(SCRATCH/'sbatch-calls.txt').read_text();assert '--partition=cnall' in calls and '--array=0-35%4' in calls and '--ntasks=56' in calls and 'cnmix' not in calls
before=(SCRATCH/'sbatch-calls.txt').read_bytes();run('submit_all.sh',rc=2);assert before==(SCRATCH/'sbatch-calls.txt').read_bytes()
results.append('One cnall 36-task array; duplicate full submission blocked')
run('submit_all.sh',extra={'DFT_TASKS':'1,35','DFT_PARALLEL':'2'})
assert '--array=1,35%2' in (SCRATCH/'sbatch-calls.txt').read_text()
run('submit_all.sh',extra={'DFT_TASKS':'1,1'},rc=2)
run('submit_all.sh',extra={'DFT_TASKS':'36'},rc=2)
run('submit_all.sh',extra={'DFT_PARALLEL':'0'},rc=2)
results.append('Explicit indexed retry accepted; duplicate/out-of-range indices and invalid concurrency rejected')
worker={'SLURM_JOB_ID':'90100','SLURM_ARRAY_JOB_ID':'90001','SLURM_NTASKS':'56'}
run('run_one.sh','0',worker)
tasks=(base/'jobs.list').read_text().splitlines();run0=base/tasks[0]/'runs/90001_0'
assert 'EXECUTION_COMPLETE_REVIEW_PENDING' in (run0/'run-status.tsv').read_text()
original=(run0/'OUTCAR').read_bytes();run('run_one.sh','0',worker,rc=1);assert (run0/'OUTCAR').read_bytes()==original
results.append('Successful execution is review-pending, and existing attempt cannot be overwritten')
run('run_one.sh','1',dict(worker,MOCK_BAD_SCF='1'),rc=3)
run1=base/tasks[1]/'runs/90001_1';assert 'FAILED' in (run1/'run-status.tsv').read_text() and (run1/'OUTCAR').exists()
results.append('VASP exit zero with unconverged SCF is failed; original output retained')
run('run_one.sh','1',dict(worker,SLURM_JOB_ID='90200',SLURM_ARRAY_JOB_ID='90002'))
assert (base/tasks[1]/'runs/90002_1/OUTCAR').exists() and (run1/'OUTCAR').exists()
results.append('A resubmitted task uses a new attempt directory without overwriting failure evidence')
run('package_results.sh',extra={'MOCK_ACTIVE':'1'},rc=2)
assert not list(SCRATCH.glob('*results*.tgz'))
run('package_results.sh');assert len(list(SCRATCH.glob('*results*.tgz')))==1
results.append('Return package refused while queued, succeeds once the mock queue is empty')
report={'scope':'Offline mocks only; NO real Slurm submission and NO real VASP calculation','passed':True,'checks':results,'bundle_manifest_sha256':hashlib.sha256((base/'manifest.json').read_bytes()).hexdigest()}
dest=ROOT/'hpc/reviews/dft600-k67-delivery';dest.mkdir(parents=True,exist_ok=True)
(dest/'offline-tests.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
