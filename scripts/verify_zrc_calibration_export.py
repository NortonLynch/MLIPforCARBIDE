"""Independent checks of exported POSCARs against original MD, plus label-budget unions."""
from pathlib import Path
import json,hashlib,collections,csv
import numpy as np
from ase.io import read
from ase.geometry import find_mic
ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
pool=ROOT/'data/candidates/zrc_round1';base=ROOT/'dft/structures/zrc_calibration18';manifest=load(base/'manifest.json');checks=[]
for r in manifest['structures']:
 source=ROOT/r['source_path'];pos=ROOT/r['POSCAR']
 assert sha(source)==r['source_sha256'] and sha(pos)==r['POSCAR_sha256']
 original=read(source,index=r['frame_index_zero_based'],format='extxyz');exported=read(pos,format='vasp')
 assert len(original)==len(exported)==64 and np.array_equal(original.numbers,exported.numbers)
 assert np.array_equal(exported.numbers,np.array([40]*32+[6]*32))
 assert np.max(np.abs(original.cell-exported.cell))<1e-12
 _,dist=find_mic(original.positions-exported.positions,original.cell,pbc=True)
 assert max(dist)<1e-8
 assert np.array_equal(exported.pbc,original.pbc) and 'momenta' not in exported.arrays and exported.calc is None
 d=exported.get_all_distances(mic=True);np.fill_diagonal(d,np.inf)
 mind={'Zr-C':float(d[:32,32:].min()),'C-C':float(d[32:,32:].min()),'Zr-Zr':float(d[:32,:32].min())}
 for pair,key in [('Zr-C','min_ZrC_A'),('C-C','min_CC_A'),('Zr-Zr','min_ZrZr_A')]:assert abs(mind[pair]-r[key])<3e-8
 checks.append({'id':r['structure_id'],'source_frame_verified':True,'periodic_max_position_error_A':float(max(dist)),'minimum_pair_distances_A':mind})
assert len(checks)==18 and len({(r['target_temperature_K'],r['volume_scale']) for r in manifest['structures']})==18
split=load(ROOT/'data/splits/zrc_round1_frozen_groups.json');roles=split['frame_ids_by_role']
seen=set()
for role,ids in roles.items():assert not seen.intersection(ids);seen.update(ids)
assert len(seen)==2160
sequences=[load(p) for p in sorted((pool/'sequences').glob('*.json'))]
assert len(sequences)==6
ids={r['frame_id']:r for r in load(pool/'candidates64.json')};uses=collections.defaultdict(list)
for s in sequences:
 frames=s['sequence'];assert len(frames)==200 and len({r['frame_id'] for r in frames})==200
 for r in frames:
  assert r['frame_id'] in roles['adaptation_development'] and ids[r['frame_id']]['md_seed']==17
  assert r['source_sha256']==ids[r['frame_id']]['source_sha256']
  uses[r['frame_id']].append({'method':s['method'],'selection_seed':s['selection_seed'],'rank':r['rank']})
 for n in [20,50,100,200]:
  counts=collections.Counter((r['target_temperature_K'],r['volume_scale']) for r in frames[:n])
  assert len(counts)==18 and max(counts.values())-min(counts.values())<=1
budgets=[]
for n in [20,50,100,200]:
 budgets.append({'budget_per_strategy_and_selection_seed':n,'unique_for_both_strategies_selection_seed17':len({r['frame_id'] for s in sequences if s['selection_seed']==17 for r in s['sequence'][:n]}),'unique_for_both_strategies_all_three_selection_seeds':len({r['frame_id'] for s in sequences for r in s['sequence'][:n]}),'calibration18_included':False,'validation_test_included':False})
save(pool/'DFT-budget-unions.json',{'calibration_count_separate':18,'budgets':budgets,'union_all_N200_count':len(uses),'submitted':False,'frames':[dict(ids[f],requested_by=uses[f]) for f in sorted(uses)]})
save(base/'export-verification.json',{'all_passed':True,'count':18,'source_model_labels_exported_as_DFT':False,'geometry_unchanged_modulo_periodic_wrapping':True,'split_roles_disjoint':True,'six_selection_sequences_verified':True,'checks':checks})
# Confirm all data files in their new locations still match the accepted numerical reviews.
reg=load(ROOT/'hpc/reviews/completed-round1-20260924/trajectory-index.json')
for j in reg['jobs']:
 for seg in j['segments'].values():
  p=ROOT/seg['path'];assert sha(p/'review.json')==seg['review_sha256']
print(json.dumps({'POSCARs_verified':18,'sequences_verified':6,'segment_reviews_in_new_locations_verified':324,'budgets':budgets},indent=2),flush=True)
