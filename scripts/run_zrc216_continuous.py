"""216-atom continuous production: preserve failed attempts; never resume partial MD."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback
from collections import Counter
import run_zrc_hpc as old
from run_zrc_md_campaign import digest, read_json, worker_lock, utc
from zrc_md_engine import atomic_json, load_checkpoint, NumericalFailure, YieldRun

ROOT = Path(__file__).resolve().parents[1]

def manifest():
    return read_json(ROOT / 'manifest.json')

def verify_files():
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        wanted, name = line.split('  ', 1)
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or digest(path) != wanted:
            raise RuntimeError('Bundle file mismatch: ' + name)

def verify_numeric_authorization(environment=None):
    m = manifest()
    evidence = ROOT / 'provenance/previous-validation-216'
    q = read_json(evidence / 'queue.json')
    source_env = read_json(evidence / 'environment.json')
    if old.identity(source_env) != q['hpc_contract']['environment_sha256']:
        raise RuntimeError('Source environment mismatch')
    if environment is not None and old.identity(environment) != old.identity(source_env):
        raise RuntimeError('GPU environment changed from the validated V100 environment')
    if digest(ROOT / 'provenance/previous-manifest.json') != q['hpc_contract']['manifest_sha256']:
        raise RuntimeError('Source numerical-gate provenance mismatch')
    for key in ['warm_216', 'high_216']:
        gate = q['gates'][key]
        if gate['status'] != 'passed' or gate['selected_dtype'] != 'float32' or gate['selected_dt_fs'] != .5:
            raise RuntimeError('Expected validated float32 / 0.5 fs gates')
        static = read_json(evidence / 'gates' / key / 'static-precision.json')
        if not (static['relative_energy_delta_meV_atom'] <= .1
                and static['force_component_RMS_eV_A'] <= .001
                and static['force_component_max_eV_A'] <= .003
                and static['stress_component_max_GPa'] <= .01):
            raise RuntimeError('Static precision gate not passed')
        for dt in ['0p5', '0p25']:
            directory = evidence / 'gates' / key / ('nve_float32_dt' + dt)
            review = read_json(directory / 'review.json')
            if (not review['hard_pass'] or not review['trajectory_integrity_passed']
                    or review['metrics']['observed_duration_fs'] != 1000
                    or review['metrics']['nve']['absolute_linear_drift_meV_atom_ps'] > 1.0):
                raise RuntimeError('NVE gate not passed')
            for name, wanted in review['file_sha256'].items():
                if digest(directory / name) != wanted:
                    raise RuntimeError('NVE evidence file changed')
    return q['gates']

class ContinuousCampaign(old.IsolatedCampaign):
    def segment(self, atoms, rng, directory, spec):
        # Inputs may come from the original accepted pilot, never from a partial production.
        if (Path(directory) / 'checkpoint.npz').exists():
            raise RuntimeError('Continuous mode refuses to load an existing production checkpoint')
        return super().segment(atoms, rng, directory, spec)

    def spec(self, job, *args, **kwargs):
        value = super().spec(job, *args, **kwargs)
        value.update(execution_protocol='continuous_216_v1', production_resume_allowed=False)
        return value

def verify_completed(directory, state):
    if state['manifest_sha256'] != digest(ROOT / 'manifest.json'):
        raise RuntimeError('Task identity mismatch')
    if state['status'] != 'passed' or not state['attempts']:
        raise RuntimeError('Task not passed')
    attempt = state['attempts'][-1]
    if attempt['status'] != 'passed':
        raise RuntimeError('Last attempt not passed')
    run = directory / attempt['directory']
    record = next(r for r in manifest()['remaining'] if r['id'] == state['job_id'])
    cqueue = read_json(run / 'queue.json')
    contract = cqueue['hpc_contract']
    if contract['manifest_sha256'] != state['manifest_sha256'] or contract['environment_sha256'] != state['environment_sha256']:
        raise RuntimeError('Run environment or bundle mismatch')
    expected_rng = None
    # Both segments must be successful within this same newly-created process attempt.
    result = []
    for stage, duration in [('equilibration',5000), ('sampling',10000)]:
        folder = run / 'jobs' / state['job_id'] / 'production' / stage
        review = read_json(folder / 'review.json')
        if not review['hard_pass'] or not review['trajectory_integrity_passed']:
            raise RuntimeError('Production review failed')
        if review['metrics']['observed_duration_fs'] != duration:
            raise RuntimeError('Production duration mismatch')
        for name, wanted in review['file_sha256'].items():
            if digest(folder / name) != wanted:
                raise RuntimeError('Production artifact changed: ' + str(folder / name))
        result.append(folder)
    return result[-1] / 'frames.extxyz'

def record_resources(run, started):
    value = {'elapsed_seconds': time.monotonic()-started,
             'scope': 'PyTorch allocator only; excludes CUDA context and other processes'}
    torch = sys.modules.get('torch')
    if torch is not None and torch.cuda.is_available():
        value.update(peak_allocated_MiB=torch.cuda.max_memory_allocated()/1024**2,
                     peak_reserved_MiB=torch.cuda.max_memory_reserved()/1024**2,
                     gpu=torch.cuda.get_device_name(0))
    atomic_json(run / 'resources.json', value)

def produce(index, environment):
    m = manifest()
    if not 0 <= index < len(m['remaining']):
        raise ValueError('Index out of range')
    gates = verify_numeric_authorization(environment)
    record = m['remaining'][index]
    directory = ROOT / 'outputs/production' / record['id']
    with worker_lock(directory):
        if (ROOT / 'STOP').exists() or (directory / 'STOP').exists():
            raise YieldRun('User STOP: no production started')
        state_path = directory / 'task.json'
        contract = {'job_id': record['id'], 'manifest_sha256': digest(ROOT / 'manifest.json'),
                    'environment_sha256': old.identity(environment)}
        if state_path.exists():
            state = read_json(state_path)
            if any(state.get(k) != v for k,v in contract.items()):
                raise RuntimeError('Cannot mix bundle or environment identities')
            if state['status'] == 'passed':
                verify_completed(directory, state)
                print('Already passed; no repeated MD', flush=True)
                return
            if state['status'] == 'blocked_review':
                raise NumericalFailure('Prior numerical failure requires review; not reset by resubmission')
            if state['attempts'] and state['attempts'][-1]['status'] == 'running':
                state['attempts'][-1].update(status='process_ended_without_completion', identified_utc=utc())
        else:
            state = {**contract, 'status':'pending', 'attempts':[], 'production_resume_allowed':False}
        if len(state['attempts']) >= m['execution_policy']['max_full_attempts']:
            raise RuntimeError('Full-attempt limit reached; review infrastructure failures')
        count = len(state['attempts']) + 1
        name = f'run-{count:04d}'
        run = directory / name
        if run.exists():
            raise RuntimeError('Untracked attempt directory exists; preserve and review')
        attempt = {'directory':name, 'status':'running', 'started_utc':utc(),
                   'source_pilot_sha256':record['checkpoint_sha256'],
                   'timestep_fs':.5, 'dtype':'float32', 'same_process_stages':True}
        state['attempts'].append(attempt); state['status']='running'; atomic_json(state_path,state)
        started=time.monotonic()
        try:
            c = ContinuousCampaign(run, [record], 'continuous_production', environment, gates)
            c.configure_signals()
            job=c.queue['jobs'][0]
            # Always read the immutable pilot state; do not call stage_start on a past run.
            atoms,rng,_=load_checkpoint(ROOT / record['checkpoint_path'])
            for stage, duration in [('equilibration',5000), ('sampling',10000)]:
                if (directory / 'STOP').exists():
                    raise YieldRun('Task STOP')
                spec=c.spec(job,stage,duration,.5,'float32')
                folder=run/'jobs'/record['id']/'production'/stage
                atoms,rng,_=c.segment(atoms,rng,folder,spec)
            job['production'].update(status='passed', completed_utc=utc(),
                                     final_checkpoint=str((folder/'checkpoint.npz').relative_to(run)),
                                     accepted_parameters={'timestep_fs':.5,'dtype':'float32'})
            c.queue['status']='passed'; c.save()
            attempt.update(status='passed', completed_utc=utc());state['status']='passed'
            atomic_json(state_path,state)
            verify_completed(directory,state)
            print(json.dumps({'event':'continuous_production_passed','job_id':record['id']}),flush=True)
        except BaseException as exc:
            status = 'blocked_review' if isinstance(exc,(NumericalFailure,FloatingPointError)) else 'interrupted_restart_from_pilot'
            attempt.update(status=status, stopped_utc=utc(), error=f'{type(exc).__name__}: {exc}')
            state['status']=status
            atomic_json(run/f'failure-{time.time_ns()}.json',{'utc':utc(),'traceback':traceback.format_exc(),'resume_allowed':False})
            atomic_json(state_path,state)
            raise
        finally:
            record_resources(run,started)

def collect():
    m=manifest();counts=Counter();tasks=[];candidates=[]
    verify_numeric_authorization()
    for record in m['remaining']:
        directory=ROOT/'outputs/production'/record['id'];p=directory/'task.json';status='not_started';error=None
        if p.exists():
            state=read_json(p);status=state['status']
            if state.get('manifest_sha256')!=digest(ROOT/'manifest.json'):status='identity_mismatch'
            if status=='passed':
                try:
                    frames=verify_completed(directory,state)
                    candidates.append({'job_id':record['id'],'source_group':record['job']['source_group'],
                                       'frames':frames.relative_to(ROOT).as_posix(),'label_source':'MACE_prediction_NOT_DFT'})
                except Exception as exc:status='artifact_review_failed';error=str(exc)
        counts[status]+=1;tasks.append({'job_id':record['id'],'status':status,'error':error})
    result={'counts':dict(counts),'expected_216':54,'previously_completed_8_and_64':108,
            'production_completed_total':108+counts['passed'],
            'status':'all_production_completed_under_recorded_protocols' if counts['passed']==54 else 'incomplete_or_needs_review',
            'restart_equivalence_certified_for_216':False,'physical_validated':False,'tasks':tasks}
    atomic_json(ROOT/'outputs/summary.json',result);atomic_json(ROOT/'outputs/candidate-trajectories.json',candidates)
    print(json.dumps({k:v for k,v in result.items() if k!='tasks'},indent=2))
    return 0 if counts['passed']==54 else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['preflight','produce','collect']);parser.add_argument('--index',type=int)
    args=parser.parse_args();verify_files()
    if args.mode=='collect':return collect()
    if len(manifest()['remaining'])!=54 or any(r['job']['atoms']!=216 for r in manifest()['remaining']):
        raise RuntimeError('Unexpected task matrix')
    if args.mode=='preflight':
        old.check_environment(False);verify_numeric_authorization()
        print('54 continuous 216-atom tasks. Source numerical gates verified; partial production will NOT resume.')
        return 0
    env=old.check_environment(True)
    produce(args.index if args.index is not None else int(os.environ['SLURM_ARRAY_TASK_ID']),env)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except YieldRun as exc:print(str(exc),file=sys.stderr);raise SystemExit(75)