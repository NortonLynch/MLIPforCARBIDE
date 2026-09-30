"""CPU-only, source-traceable screening and 18-frame DFT calibration export.
No model inference, training, geometry relaxation or DFT submission is performed.
"""
from pathlib import Path
import json,hashlib,csv,collections,sys,platform,importlib.metadata
import numpy as np
from ase import Atoms
from ase.io import iread,read,write
from dscribe.descriptors import SOAP
from scipy.spatial.distance import cdist
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/candidates/zrc_round1'
STRUCT=ROOT/'dft/structures/zrc_calibration18'
AUD=ROOT/'hpc/reviews/completed-round1-20260924'
TEMPS=[300,1500,3000,4500,5250,6000]
VOLS=[1.0,.95,1.05]
SPLITS={17:'development',42:'validation_reserve',2026:'test_reserve'}
SOAP_ARGS=dict(species=['C','Zr'],periodic=True,r_cut=6.0,n_max=6,l_max=4,sigma=.5,average='off',dtype='float64')
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
 return h.hexdigest()
def rel(p):return p.relative_to(ROOT).as_posix()
def csvout(p,rows):
 with p.open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def structural_copy(a):
 # The input species order is deliberately kept, and checked at POSCAR export.
 b=Atoms(numbers=a.numbers,positions=a.positions,cell=a.cell,pbc=a.pbc)
 b.wrap();return b

def geometry_hash(a):
 # Same wrapped coordinates/cell at 1e-8 resolution; atom permutations handled within each species.
 # This is a duplicate detector, not a rotation/translation-invariant structural similarity measure.
 pieces=[np.round(np.asarray(a.cell),8).astype('<f8').tobytes()]
 frac=np.mod(a.get_scaled_positions(wrap=True),1)
 for z in sorted(set(a.numbers)):
  s=np.round(frac[a.numbers==z],8);s[s>=1]=0
  s=s[np.lexsort((s[:,2],s[:,1],s[:,0]))]
  pieces.extend([str(z).encode(),s.astype('<f8').tobytes()])
 return hashlib.sha256(b''.join(pieces)).hexdigest()

def autocorr(x,dt=5):
 x=np.asarray(x,float);x=x-x.mean()
 if np.dot(x,x)<1e-20:return {'tau_int_fs':0.,'rho_250fs':0.,'positive_lags':0}
 fft=np.fft.rfft(x,n=2*len(x));cov=np.fft.irfft(fft*np.conj(fft),n=2*len(x))[:len(x)]
 acf=cov/cov[0];s=0.;count=0
 for rho in acf[1:min(len(x)//4,500)]:
  if rho<=0:break
  s+=float(rho);count+=1
 return {'tau_int_fs':float(dt*(.5+s)),'rho_250fs':float(acf[50]),'positive_lags':count}

def scan():
 OUT.mkdir(parents=True,exist_ok=True)
 reg=load(AUD/'trajectory-index.json');rows=[];candidates=[];atoms=[];diagnostics=[];seen={};dupes=[]
 for jn,j in enumerate(reg['jobs'],1):
  source=ROOT/j['segments']['sampling']['path'];path=source/'frames.extxyz'
  assert digest(path)==j['segments']['sampling']['file_sha256']['frames.extxyz']
  log=[json.loads(s) for s in (source/'log.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
  bystep={v['step']:v for v in log};assert len(log)==2001
  r=load(source/'review.json');m=r['metrics'];a_corr=autocorr([v['potential_eV']/j['atoms'] for v in log[1:]])
  diagnostics.append({'job_id':j['id'],'atoms':j['atoms'],'temperature_K':j['temperature_K'],'volume_scale':j['volume_scale'],'seed':j['seed'],'temperature_mean_K':m['temperature_K']['mean'],'pressure_mean_GPa':m['pressure_GPa']['mean'],'potential_mean_eV_atom':m['potential_eV_atom']['mean'],'four_block_energy_range_meV_atom':1000*np.ptp([b['potential_eV_atom'] for b in m['four_block_means']]),'maximum_force_eV_A':m['maximum_force_eV_A'],'minimum_ZrC_A':m['minimum_pair_distances_A']['Zr-C'],'minimum_CC_A':m['minimum_pair_distances_A']['C-C'],'energy_tau_int_fs_estimate':a_corr['tau_int_fs'],'energy_rho_250fs':a_corr['rho_250fs'],'phase':'unassigned','equilibration_established':False})
  count=0
  for fi,a in enumerate(iread(path,index=':',format='extxyz')):
   count+=1;info=a.info;time=float(info['time_fs']);step=int(info['step'])
   assert len(a)==j['atoms'] and collections.Counter(a.get_chemical_symbols())=={'Zr':len(a)//2,'C':len(a)//2}
   assert a.pbc.all() and np.isfinite(a.positions).all() and np.isfinite(a.cell).all()
   assert np.isfinite(a.arrays['model_forces']).all() and np.isfinite(float(info['model_energy']))
   assert info['job_id']==j['id'] and info['stage']=='sampling' and abs(time-fi*50)<1e-8
   assert np.isclose(a.get_volume(),4.7**3*(len(a)/8)*j['volume_scale'],rtol=1e-8)
   assert int(info['target_temperature_K'])==j['temperature_K']
   assert abs(float(info['model_energy'])-bystep[step]['potential_eV'])<1e-5
   if fi==0:continue  # Same state as the final equilibration checkpoint.
   gh=geometry_hash(a);fid=f"{j['id']}_f{fi:04d}"
   duplicated=seen.get(gh,'')
   if duplicated:dupes.append({'frame_id':fid,'same_geometry_as':duplicated})
   else:seen[gh]=fid
   l=bystep[step];pair=l['min_pair_distances_A']
   row={'frame_id':fid,'job_id':j['id'],'atoms':len(a),'target_temperature_K':j['temperature_K'],'volume_scale':j['volume_scale'],'md_seed':j['seed'],'split':SPLITS[j['seed']],'source_group':j['source_group'],'frame_index_zero_based':fi,'sampling_time_fs':time,'step':step,'temperature_K':float(info['temperature_K']),'MACE_energy_eV_atom':float(info['model_energy'])/len(a),'MACE_pressure_GPa':l['pressure_GPa'],'MACE_max_force_eV_A':l['max_force_eV_A'],'min_ZrC_A':pair['Zr-C'],'min_CC_A':pair['C-C'],'min_ZrZr_A':pair['Zr-Zr'],'geometry_sha256':gh,'source_path':rel(path),'source_sha256':j['segments']['sampling']['file_sha256']['frames.extxyz'],'duplicate_of':duplicated,'phase':'unassigned'}
   rows.append(row)
   if len(a)==64 and fi%5==0 and not duplicated:
    candidates.append(row.copy());atoms.append(structural_copy(a))
  assert count==201
  if jn%9==0:print(f'Validated trajectories {jn}/162; indexed {len(rows)} frames; 64-atom candidates {len(candidates)}',flush=True)
 assert len(rows)==32400 and len(candidates)==2160,(len(rows),len(candidates))
 csvout(OUT/'all-sampling-frames.csv',rows);csvout(OUT/'trajectory-diagnostics.csv',diagnostics)
 dump(OUT/'duplicate-audit.json',{'method':'wrapped fractional geometry and cell, rounded 1e-8, species permutation invariant only','duplicates':dupes})
 dump(OUT/'candidates64.json',candidates)
 for a,r in zip(atoms,candidates):a.info={'frame_id':r['frame_id'],'label_source':'UNLABELED_STRUCTURE_NOT_DFT','phase_assignment':'unassigned'}
 write(OUT/'candidates64.extxyz',atoms,format='extxyz')
 dump(OUT/'scan-summary.json',{'complete_trajectories':len(reg['jobs']),'raw_sampling_frames_including_t0':32562,'frames_after_t0_removed':len(rows),'raw64_frames':sum(r['atoms']==64 for r in rows),'thinned64_frames':len(candidates),'time_grid_fs':250,'duplicate_count':len(dupes),'rejected_nonfinite_or_invalid_frames':0,'hard_checks':'abort, do not silently drop invalid source data','independence_at_250fs_established':False,'physical_validated':False,'trajectory_index_sha256':digest(AUD/'trajectory-index.json'),'candidate_structures_sha256':digest(OUT/'candidates64.extxyz')})
 return candidates,atoms

def describe(rows,atoms):
 soap=SOAP(**SOAP_ARGS);vectors=[]
 for i,a in enumerate(atoms):
  p=soap.create(a);p=p/np.linalg.norm(p,axis=1,keepdims=True)
  pieces=[]
  for z in [6,40]:
   v=p[a.numbers==z];pieces.extend([v.mean(axis=0),v.std(axis=0,ddof=0)])
  vector=np.concatenate(pieces);vector/=np.linalg.norm(vector);vectors.append(vector)
  if (i+1)%180==0:print(f'SOAP descriptors {i+1}/{len(atoms)}',flush=True)
 x=np.asarray(vectors);assert np.isfinite(x).all()
 np.savez_compressed(OUT/'soap64.npz',vectors=x,frame_ids=np.array([r['frame_id'] for r in rows]))
 dump(OUT/'soap-method.json',{'constructor':SOAP_ARGS,'local_normalization':'unit L2 for every atom','global_aggregation':'concatenate C mean, C population standard deviation, Zr mean, Zr population standard deviation; final unit L2','metric':'Euclidean on normalized global vectors; custom aggregation, not a fitted SOAP kernel','vector_dimensions':x.shape[1],'fitted_scaler':None,'scope':'geometry-only; no DFT labels, no uncertainty estimate','software':{p:importlib.metadata.version(p) for p in ['numpy','ase','dscribe','scipy']},'python':sys.version,'platform':platform.platform(),'input_sha256':digest(OUT/'candidates64.extxyz')})
 return x

def select(rows,atoms,x):
 states=[(t,v) for t in TEMPS for v in VOLS]
 def state(i):return (rows[i]['target_temperature_K'],rows[i]['volume_scale'])
 dev=[i for i,r in enumerate(rows) if r['md_seed']==17]
 # Reference is a medoid-like actual frame nearest the centroid of its development stratum.
 cold=[i for i in dev if state(i)==(300,1.)]
 centre=x[cold].mean(axis=0);reference=cold[int(np.argmin(np.linalg.norm(x[cold]-centre,axis=1)))]
 chosen=[reference]
 for s in states[1:]:
  candidates=[i for i in dev if state(i)==s]
  dd=cdist(x[candidates],x[chosen]).min(axis=1)
  chosen.append(candidates[int(np.argmax(dd))])
 assert len(set(chosen))==18 and {state(i) for i in chosen}==set(states)
 STRUCT.mkdir(parents=True,exist_ok=True);selected=[];exported=[]
 for rank,i in enumerate(chosen,1):
  row=rows[i].copy();a=atoms[i].copy()
  assert list(a.numbers)==[40]*32+[6]*32
  outdir=STRUCT/f'{rank:02d}_{row["frame_id"]}';outdir.mkdir(parents=True,exist_ok=True)
  a.info={'structure_id':outdir.name,'label_source':'UNLABELED_STRUCTURE_NOT_DFT','phase_assignment':'unassigned'}
  write(outdir/'POSCAR',a,format='vasp',direct=True,vasp5=True,sort=False)
  reread=read(outdir/'POSCAR',format='vasp')
  delta=reread.get_scaled_positions()-a.get_scaled_positions();delta-=np.rint(delta)
  error=float(np.max(np.abs(delta@a.cell)))
  assert error<1e-10 and np.array_equal(a.numbers,reread.numbers) and np.allclose(a.cell,reread.cell,rtol=0,atol=1e-12)
  row.update(calibration_rank=rank,structure_id=outdir.name,POSCAR=rel(outdir/'POSCAR'),POSCAR_sha256=digest(outdir/'POSCAR'),relative_energy_reference=(i==reference),selection='reference_nearest_centroid' if i==reference else 'one_per_TV_stratum_maximum_minimum_SOAP_distance',DFT_label_status='not_calculated',DFT_protocol_status='calibration_pending',roundtrip_max_position_component_error_A=error)
  dump(outdir/'structure.json',row);selected.append(row);exported.append(a)
 write(STRUCT/'calibration18.extxyz',exported,format='extxyz')
 csvout(STRUCT/'structures.csv',selected)
 (STRUCT/'structures.list').write_text('\n'.join(r['POSCAR'] for r in selected)+'\n',encoding='utf-8')
 manifest={'schema_version':1,'count':18,'atoms_each':64,'species_order':['Zr','C'],'counts':[32,32],'role':'DFT numerical protocol development, excluded from later adaptation training sequences','reference_structure_id':selected[0]['structure_id'],'model_predictions_are_DFT_labels':False,'POSCARs_are_unrelaxed_MD_snapshots':True,'static_single_point_required':True,'submitted':False,'DFT_protocol_certified':False,'structures':selected}
 dump(STRUCT/'manifest.json',manifest)
 train=[i for i in dev if i not in chosen];assert len(train)==702
 seqdir=OUT/'sequences';seqdir.mkdir(exist_ok=True);sequence_summary=[]
 # Same balanced state schedule per selection replicate for both strategies.
 # Replicate seeds govern selection, not MD origin (which remains seed 17).
 for selection_seed in [17,42,2026]:
  rng=np.random.default_rng(selection_seed);schedule=[]
  while len(schedule)<200:schedule.extend([states[int(k)] for k in rng.permutation(len(states))])
  for method in ['stratified_random','stratified_SOAP_FPS']:
   rng=np.random.default_rng(selection_seed);picked=[];minimum=np.full(len(rows),np.inf);seq=[]
   for rank,s in enumerate(schedule[:200],1):
    available=[i for i in train if state(i)==s and i not in picked]
    if method=='stratified_random' or not picked:i=available[int(rng.integers(len(available)))]
    else:i=available[int(np.argmax(minimum[available]))]
    olddistance=None if not picked else float(minimum[i])
    picked.append(i);minimum=np.minimum(minimum,np.linalg.norm(x-x[i],axis=1))
    r=rows[i].copy();r.update(rank=rank,method=method,selection_seed=selection_seed,min_SOAP_distance_before_selection=olddistance)
    seq.append(r)
   assert len(set(picked))==200 and not set(picked).intersection(chosen)
   name=f'{method}_selectionseed{selection_seed}'
   dump(seqdir/(name+'.json'),{'method':method,'selection_seed':selection_seed,'MD_origin_seed':17,'candidate_pool_count':702,'calibration18_included':False,'nested_budgets':[20,50,100,200],'submitted':False,'sequence':seq})
   csvout(seqdir/(name+'.csv'),seq)
   for n in [20,50,100,200]:
    counts=collections.Counter(state(i) for i in picked[:n]);assert max(counts.values())-min(counts.values())<=1
    sequence_summary.append({'method':method,'selection_seed':selection_seed,'budget':n,'unique_frames':len(set(picked[:n])),'mean_nearest_SOAP_distance_on_development_pool':float(cdist(x[train],x[picked[:n]]).min(axis=1).mean()),'max_nearest_SOAP_distance_on_development_pool':float(cdist(x[train],x[picked[:n]]).min(axis=1).max())})
 csvout(OUT/'selection-coverage.csv',sequence_summary)
 split={'schema_version':1,'grouping':'global MD seed; merge every size, volume and heating descendant with the same seed','MD_seed_assignment':SPLITS,'development64_count':720,'calibration18_count':18,'training64_after_calibration_exclusion':702,'validation64_reserved_count':720,'test64_reserved_count':720,'validation_DFT_budget':None,'test_DFT_budget':None,'test_used_for_training_selection':False,'all_frames_unlabeled':True,'warning':'These three seeds form only three conservative origin groups. Reserve/test independence in phase-space and physical coverage is not established. No 216-to-64 crops.'}
 split['frame_ids_by_role']={'calibration':[rows[i]['frame_id'] for i in chosen],'adaptation_development':[rows[i]['frame_id'] for i in train],'validation_reserve':[r['frame_id'] for r in rows if r['md_seed']==42],'test_reserve':[r['frame_id'] for r in rows if r['md_seed']==2026]}
 dump(ROOT/'data/splits/zrc_round1_frozen_groups.json',split)
 csvout(OUT/'calibration18-summary.csv',selected)
 dump(OUT/'selection-summary.json',{'calibration_count':18,'temperature_volume_states':18,'future_sequences':6,'each_sequence_length':200,'budgets':[20,50,100,200],'reference_frame':rows[reference]['frame_id'],'input_candidate_count':len(rows),'SOAP_shape':list(x.shape),'scan_summary_sha256':digest(OUT/'scan-summary.json'),'method_sha256':digest(OUT/'soap-method.json'),'SOAP_file_sha256':digest(OUT/'soap64.npz'),'frozen_split_sha256':digest(ROOT/'data/splits/zrc_round1_frozen_groups.json'),'calibration_manifest_sha256':digest(STRUCT/'manifest.json'),'source_code_sha256':digest(Path(__file__))})
 print('Exported 18 calibration structures and six nested 200-frame selection sequences.',flush=True)

if __name__=='__main__':
 if '--from-scan' in sys.argv:
  rows=load(OUT/'candidates64.json');atoms=read(OUT/'candidates64.extxyz',index=':')
 else:rows,atoms=scan()
 if '--from-soap' in sys.argv:x=np.load(OUT/'soap64.npz')['vectors']
 else:x=describe(rows,atoms)
 select(rows,atoms,x)
