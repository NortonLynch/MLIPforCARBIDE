"""Package only the 54 missing 216-atom tasks, under an explicit continuous protocol."""
from pathlib import Path
import json,hashlib,shutil,tarfile
from itertools import product
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'hpc/zrc-round1-remaining'
OUT=ROOT/'hpc/zrc216-continuous'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def cp(a,b):b.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a,b)
def build():
 old=read(OLD/'manifest.json');summary=read(OLD/'outputs/summary.json')
 assert summary['hpc_status_counts']=={'not_started':54,'passed':90}
 missing={r['job_id'] for r in summary['tasks'] if r['status']!='passed'}
 records=[r for r in old['remaining'] if r['id'] in missing]
 assert len(records)==54 and all(r['job']['atoms']==216 for r in records)
 assert {(r['job']['temperature_K'],r['job']['volume_scale'],r['job']['seed']) for r in records}==set(product([300,1500,3000,4500,5250,6000],[.95,1,1.05],[17,42,2026]))
 for record in records:
  for key in ['checkpoint','initial']:
   p=OLD/record[key+'_path'];assert sha(p)==record[key+'_sha256'];cp(p,OUT/record[key+'_path'])
  folder=Path(record['checkpoint_path']).parent
  cp(OLD/folder/'pilot-review.json',OUT/folder/'pilot-review.json')
 for name in ['run_zrc_hpc.py','run_zrc_md_campaign.py','zrc_md_engine.py','zrc_md_review.py']:
  cp(OLD/'scripts'/name,OUT/'scripts'/name)
 cp(ROOT/'scripts/run_zrc216_continuous.py',OUT/'scripts/run_zrc216_continuous.py')
 cp(OLD/'configs/experiments/zrc_mace_round1.json',OUT/'configs/experiments/zrc_mace_round1.json')
 cp(ROOT/'models/mace-mh-1.model',OUT/'models/mace-mh-1.model')
 cp(OLD/'manifest.json',OUT/'provenance/previous-manifest.json')
 cp(OLD/'outputs/summary.json',OUT/'provenance/previous-summary.json')
 cp(OLD/'submissions/jobs.tsv',OUT/'provenance/previous-jobs.tsv')
 cp(ROOT/'hpc/reviews/results-20260923/audit.json',OUT/'provenance/returned-results-audit.json')
 source=OLD/'outputs/validation/216'
 for p in source.rglob('*'):
  if p.is_file():cp(p,OUT/'provenance/previous-validation-216'/p.relative_to(source))
 q=read(source/'queue.json');assert all(q['gates'][k]['status']=='passed' for k in ['warm_216','high_216'])
 assert read(source/'restart/zrc216_T6000_v100_s17/review.json')['status']=='blocked_review'
 m={'schema_version':1,'campaign_id':'zrc216-continuous-v1','model_sha256':old['model_sha256'],'hpc_versions':old['hpc_versions'],
    'remaining':records,'previous_completed_8_and_64':108,'execution_policy':{
    'name':'continuous_216_v1','equilibration_fs':5000,'sampling_fs':10000,'timestep_fs':.5,'dtype':'float32',
    'production_resume_allowed':False,'on_infrastructure_interruption':'preserve_failed_run_and_start_entire_15ps_from_original_pilot',
    'on_numerical_failure':'blocked_review_no_automatic_threshold_change','max_full_attempts':3,
    'checkpoint_writes':'for_evidence_only_not_production_resume','stages':'same_process_in_memory_handoff',
    'restart_comparison':'original_failed_test_retained_not_claimed_passed_and_not_a_gate_for_continuous_execution',
    'numeric_authorization':'reuse_verified_V100_warm_high_static_and_NVE_evidence_same_environment',
    'user_basis':'User requested a new 216-atom HPC package after discussion of continuous runs with whole-task reruns'},
    'physical_validated':False}
 (OUT/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8',newline='\n')
 table=['array_index\tjob_id\tatoms\ttemperature_K\tvolume_scale\tseed']
 for i,r in enumerate(records):
  j=r['job'];table.append(f"{i}\t{r['id']}\t216\t{j['temperature_K']}\t{j['volume_scale']}\t{j['seed']}")
 (OUT/'tasks.tsv').write_text('\n'.join(table)+'\n',encoding='utf-8',newline='\n')
 files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS' and not {'outputs','logs','submissions','__pycache__'}&set(p.relative_to(OUT).parts))
 (OUT/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(OUT).as_posix()}\n' for p in files),encoding='utf-8',newline='\n')
 archive=ROOT/'hpc/zrc216-continuous.tgz'
 with tarfile.open(archive,'w:gz') as t:
  for p in files+[OUT/'SHA256SUMS']:
   info=t.gettarinfo(str(p),arcname='zrc216-continuous/'+p.relative_to(OUT).as_posix());info.mode=0o755 if p.suffix=='.sh' else 0o644
   with p.open('rb') as f:t.addfile(info,f)
 archive.with_suffix('.tgz.sha256').write_text(sha(archive)+'  '+archive.name+'\n',encoding='utf-8',newline='\n')
 print(json.dumps({'tasks':54,'bytes':archive.stat().st_size,'sha256':sha(archive),'files':len(files)+1},indent=2))
if __name__=='__main__':build()