"""Audit completed round-1 MD and prepare an explicit, bounded HPC cleanup plan."""
from pathlib import Path
import hashlib,json,tarfile,shutil,datetime,collections
ROOT=Path(__file__).resolve().parents[1]
AUD=ROOT/'hpc/reviews/completed-round1-20260924'
AUD.mkdir(parents=True,exist_ok=True)
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def rel(p): return p.relative_to(ROOT).as_posix()
def save(p,x): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def copy(p,d): d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
bundles={'zrc-round1-remaining':'round1-8-64','zrc216-continuous':'round1-216'}
inventory=[{'path':rel(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in (ROOT/'hpc').rglob('*') if p.is_file() and AUD not in p.parents]
save(AUD/'before-cleanup-files.json',inventory)
print('Inventory:',len(inventory),'files',flush=True)
archives=[]
for name,bundle,result in [('zrc-round1-results.tgz','zrc-round1-remaining',True),('zrc216-continuous-results.tgz','zrc216-continuous',True),('zrc-round1-remaining.tgz','zrc-round1-remaining',False),('zrc216-continuous.tgz','zrc216-continuous',False)]:
 path=ROOT/'hpc'/name; matches=0;different=[];nbytes=0
 with tarfile.open(path,'r|gz') as tf:
  for member in tf:
   if not member.isfile(): continue
   part=Path(member.name)
   assert not part.is_absolute() and '..' not in part.parts
   target=(ROOT/'hpc'/bundle/part) if result else ROOT/'hpc'/part
   content=tf.extractfile(member).read(); digest=hashlib.sha256(content).hexdigest();nbytes+=len(content)
   if target.is_file() and sha(target)==digest: matches+=1
   else:
    # Regenerated summaries or patched submit scripts are preserved in their original archive version.
    critical=result and (('production' in part.parts or 'validation' in part.parts) and target.name not in ['worker.lock'])
    if critical: raise RuntimeError(f'Archive production/validation mismatch: {name}:{member.name}')
    preserved=AUD/'archive-original-differences'/name.replace('.tgz','')/part
    preserved.parent.mkdir(parents=True,exist_ok=True);preserved.write_bytes(content)
    different.append({'member':member.name,'sha256':digest,'preserved_at':rel(preserved)})
 archives.append({'path':rel(path),'sha256':sha(path),'matching_files':matches,'uncompressed_bytes':nbytes,'preserved_differences':different})
 print('Archive verified:',name,matches,'matches',len(different),'metadata differences',flush=True)
save(AUD/'archive-comparison.json',archives)
q=read(ROOT/'experiments/zrc_mace_round1/queue.json')
assert len(q['jobs'])==162 and all(j['pilot']['status']=='passed' for j in q['jobs'])
assert len(q['gates'])==6 and all(g['status']=='passed' for g in q['gates'].values())
meta={j['id']:j for j in q['jobs']}; entries=[]
def add(j,base,origin):
 cp=base/Path(j['production']['final_checkpoint'].replace('\\','/'))
 sam=cp.parent
 e={k:j[k] for k in ['id','atoms','temperature_K','volume_scale','seed','source_group']}
 e.update(origin=origin,production_status=j['production']['status'],parameters=j['production']['accepted_parameters'],segments={})
 assert e['production_status']=='passed'
 for stage,duration in [('equilibration',5000),('sampling',10000)]:
  d=sam.parent/stage;r=read(d/'review.json')
  assert r['hard_pass'] and r['trajectory_integrity_passed'] and r['metrics']['observed_duration_fs']==duration,(e['id'],stage)
  for name,digest in r['file_sha256'].items(): assert sha(d/name)==digest,(e['id'],name)
  new=rel(d)
  for old,folder in bundles.items(): new=new.replace('hpc/'+old+'/outputs/production/','hpc/results/'+folder+'/production/')
  e['segments'][stage]={'path':new,'original_path':rel(d),'duration_fs':duration,'frames':r['frame_count'],'file_sha256':r['file_sha256'],'review_sha256':sha(d/'review.json')}
 entries.append(e)
for j in q['jobs']:
 if j['production']['status']=='passed':add(j,ROOT/'experiments/zrc_mace_round1','local')
old=ROOT/'hpc/zrc-round1-remaining'
for p in sorted((old/'outputs/production').glob('*/queue.json')):
 r=read(p)
 for j in r['jobs']:
  if j['production']['status']=='passed':
   assert j['atoms'] in (8,64);assert all(g['status']=='passed' for g in r['gates'].values());add(j,p.parent,'HPC8_64')
new=ROOT/'hpc/zrc216-continuous'
for p in sorted((new/'outputs/production').glob('*/task.json')):
 t=read(p);assert t['status']=='passed' and not t['production_resume_allowed']
 passed=[a for a in t['attempts'] if a['status']=='passed'];assert len(passed)==1 and passed[0]['same_process_stages']
 run=p.parent/passed[0]['directory'];r=read(run/'queue.json');add(r['jobs'][0],run,'HPC216_continuous')
assert len(entries)==162 and len({e['id'] for e in entries})==162 and set(e['id'] for e in entries)==set(meta)
assert collections.Counter(e['origin'] for e in entries)=={'local':18,'HPC8_64':90,'HPC216_continuous':54}
model_sha=sha(ROOT/'models/mace-mh-1.model')
for b in bundles:
 for p in (ROOT/'hpc'/b/'models').glob('*'):
  if p.suffix=='.model': assert sha(p)==model_sha
# Keep lightweight numerical certificates and raw evidence of the failed 216-atom restart comparison.
for p in (old/'outputs/validation').rglob('*'):
 if p.is_file() and (p.suffix=='.json' or ('restart' in p.parts and 'zrc216_T6000_v100_s17' in p.parts)):
  copy(p,AUD/'numerical-evidence'/p.relative_to(old/'outputs/validation'))
# Submission code, frozen configs and manifests remain, but are explicitly archival, not current submit entry points.
for b,folder in bundles.items():
 base=ROOT/'hpc'/b
 for p in base.rglob('*'):
  if not p.is_file(): continue
  sub=p.relative_to(base)
  if sub.parts[0] in ['models','inputs','outputs','logs','submissions']: continue
  if 'previous-validation-216' in sub.parts: continue
  copy(p,ROOT/'hpc/archive/submission-provenance'/b/sub)
 for p in (base/'outputs').glob('*'):
  if p.is_file():copy(p,AUD/'original-summaries'/b/p.name)
 save(AUD/'input-identities'/f'{b}.json',[{'path':rel(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in (base/'inputs').rglob('*') if p.is_file()])
 # Pilot starting states already persist in the immutable local campaign and production branches.
 manifest=read(base/'manifest.json')
 for row in manifest['remaining']:
  jid=row['id'];src=ROOT/'experiments/zrc_mace_round1'/Path(meta[jid]['pilot']['final_checkpoint'].replace('\\','/'))
  assert sha(src)==row['checkpoint_sha256'],jid
save(AUD/'trajectory-index.json',{'schema_version':1,'path_base':'D:/MaterialModel','model_sha256':model_sha,'jobs':sorted(entries,key=lambda e:(e['atoms'],e['temperature_K'],e['volume_scale'],e['seed']))})
summary={'audit_date':'2026-09-24','production_passed':162,'pilot_passed':162,'local_gates_passed':6,'production_by_origin':dict(collections.Counter(e['origin'] for e in entries)),'production_by_atoms':dict(collections.Counter(e['atoms'] for e in entries)),'equilibration_total_ps':810,'sampling_total_ps':1620,'sampling_frames_including_t0':sum(e['segments']['sampling']['frames'] for e in entries),'restart_equivalence_certified_for_216':False,'216_method':'54 fresh uninterrupted same-process 5+10 ps branches; no partial production resume','physical_validated':False,'equilibration_established':False,'DFT_protocol_certified':False,'model_sha256':model_sha,'all_review_hashes_rechecked':True}
save(AUD/'completion-audit.json',summary)
moves=[]
for b,folder in bundles.items():
 for part in ['outputs/production','logs','submissions']:
  source=ROOT/'hpc'/b/part
  if source.exists(): moves.append({'from':rel(source),'to':'hpc/results/'+folder+'/'+Path(part).name})
remove=['hpc/'+b for b in bundles]+['hpc/'+a['path'].split('/')[-1] for a in archives]+['hpc/zrc-round1-remaining.tgz.sha256','hpc/zrc216-continuous.tgz.sha256','hpc/submit_review_only.sh']
save(AUD/'cleanup-plan.json',{'approved_scope':'User asked to clean all hpc validation files and duplicate tgz packages; raw production retained','moves':moves,'remove':remove,'before_bytes':sum(x['bytes'] for x in inventory),'evidence_kept':rel(AUD),'status':'audited_ready_for_native_powershell_cleanup'})
print(json.dumps(summary,indent=2),flush=True)
