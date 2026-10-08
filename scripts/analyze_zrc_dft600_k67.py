"""Audit the returned 18-pair ZrC k-mesh calibration without editing raw data.

Run in carbide-analysis. Energies use force-consistent VASP free energy;
stress is retained both as VASP kbar and ASE tensile-positive eV/Angstrom^3.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from ase.io import read
from pymatgen.io.vasp.inputs import Incar, Kpoints, Poscar
from pymatgen.io.vasp.outputs import Vasprun

ROOT = Path(__file__).resolve().parents[1]
GPA_PER_EV_A3 = 160.21766208


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_checksums(folder: Path, filename: str) -> int:
    entries = (folder / filename).read_text().splitlines()
    for line in entries:
        digest, name = line.split(maxsplit=1)
        target = folder / name.lstrip('*')
        assert target.resolve().is_relative_to(folder.resolve()), name
        assert sha(target) == digest, str(target)
    return len(entries)


def read_status(path: Path) -> dict:
    return dict(line.split('\t', 1) for line in path.read_text().splitlines())


def audit_task(base: Path, task: dict) -> dict:
    inputs = base / task['task_path']
    attempts = sorted((inputs / 'runs').iterdir())
    candidates = [p for p in attempts if p.is_dir()
                  and (p / 'run-status.tsv').exists()
                  and read_status(p / 'run-status.tsv').get('state') == 'EXECUTION_COMPLETE_REVIEW_PENDING']
    assert len(candidates) == 1, (task['task_path'], candidates)
    p = candidates[0]
    verify_checksums(inputs, 'INPUT_SHA256SUMS')
    verify_checksums(p, 'INPUT_SHA256SUMS')
    for name in ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR', 'job.json', 'POTCAR.meta.json']:
        assert (p / name).read_bytes() == (inputs / name).read_bytes(), str(p / name)
    for name in ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR']:
        assert sha(p / name) == task[name + '_sha256']
    assert (p / 'POSCAR').read_bytes() == (ROOT / task['source_record']['POSCAR']).read_bytes()

    v = Vasprun(p / 'vasprun.xml', parse_dos=False,
                parse_projected_eigen=False, parse_potcar_file=False)
    s = v.ionic_steps[-1]
    atoms = read(p / 'vasprun.xml', index=-1)
    incar = Incar.from_file(p / 'INCAR')
    pos = Poscar.from_file(p / 'POSCAR', check_for_potcar=False)
    out = (p / 'OUTCAR').read_text(errors='replace')
    stdout = (p / 'stdout.vasp').read_text(errors='replace')
    meta = json.loads((p / 'POTCAR.meta.json').read_text())
    force = np.asarray(s['forces'])
    stress = np.asarray(s['stress'])
    energy = {key: float(s[key]) for key in ['e_fr_energy', 'e_wo_entrp', 'e_0_energy']}
    # The final SCF row has separate dE and d eps even when later ncg/rms columns touch.
    scf_rows = [line.split() for line in (p / 'OSZICAR').read_text().splitlines()
                if line.startswith(('DAV:', 'RMM:'))]
    last = scf_rows[-1]
    top_occupation = max(float(e[:, -1, 1].max()) for e in v.eigenvalues.values())
    xml_cell = v.initial_structure.lattice.matrix
    frac_delta = v.initial_structure.frac_coords - pos.structure.frac_coords
    frac_delta -= np.rint(frac_delta)
    position_error = float(np.max(np.abs(frac_delta @ xml_cell)))
    output_toten = float(re.findall(r'free\s+energy\s+TOTEN\s*=\s*([-\d.]+)', out)[-1])
    checks = {
        'electronic_converged': bool(v.converged_electronic),
        'normal_end': 'General timing and accounting' in out,
        'ediff_reached': 'aborting loop because EDIFF is reached' in out,
        'last_scf_deltas_below_ediff': max(abs(float(last[3])), abs(float(last[4]))) < incar['EDIFF'],
        'single_static_step': len(v.ionic_steps) == 1 and v.final_structure == v.initial_structure,
        'geometry_preserved': position_error < 1e-6 and bool(np.allclose(xml_cell, pos.structure.lattice.matrix, atol=1e-7, rtol=0)),
        'species_order': [str(x) for x in v.initial_structure.species] == ['Zr']*32+['C']*32,
        'xml_incar_matches_input': v.incar == incar,
        'actual_parameters_match': all(v.parameters['ENMAX' if k == 'ENCUT' else k] == incar[k]
            for k in ['ENCUT', 'EDIFF', 'ISPIN', 'ISMEAR', 'SIGMA', 'NSW', 'ISYM', 'LREAL', 'LASPH', 'ADDGRID']),
        'kmesh_matches_input': list(v.kpoints.kpts[0]) == task['kmesh'] == list(Kpoints.from_file(p/'KPOINTS').kpts[0]),
        'potentials_match_output': all(x['embedded_sha256'] in out and x['title'] in out for x in meta['potentials']),
        'finite_labels': bool(np.isfinite(force).all() and np.isfinite(stress).all() and np.isfinite(list(energy.values())).all()),
        'ase_toten_matches': abs(atoms.get_potential_energy(force_consistent=True)-energy['e_fr_energy']) < 1e-7,
        'outcar_toten_matches': abs(output_toten-energy['e_fr_energy']) < 1e-7,
        'ase_forces_match': bool(np.allclose(atoms.get_forces(), force, atol=1e-8, rtol=0)),
        # ASE's XML reader retains the upper triangle, then mirrors it on request.
        # Compare identical representations; raw XML can be slightly asymmetric.
        'ase_stress_sign_units_match': bool(np.allclose(atoms.get_stress(), -stress.reshape(9)[[0,4,8,5,2,1]]*0.1/GPA_PER_EV_A3, atol=1e-8, rtol=0)),
        'highest_band_empty': top_occupation < 1e-6,
        'stderr_empty': (p/'stderr.vasp').stat().st_size == 0,
        'worker_exit_zero': read_status(p/'run-status.tsv').get('exit_code') == '0',
    }
    checks = {key: bool(value) for key, value in checks.items()}
    alert_pattern = re.compile(r'warning|PSMAXN|BRMIX|ZBRENT|EDDDAV|VERY BAD|internal error|not hermitian', re.I)
    alerts = sorted(set(line.strip() for line in (out+'\n'+stdout).splitlines() if alert_pattern.search(line)))
    wall = float(re.search(r'Elapsed time \(sec\):\s*([\d.]+)', out).group(1))
    return {
        'array_index': task['array_index'], 'structure_id': task['structure_id'],
        'temperature_K': task['target_temperature_K'], 'volume_scale': task['volume_scale'],
        'kmesh': task['kmesh'], 'natoms': len(atoms), 'attempt': p.name,
        'run_path': p.relative_to(ROOT).as_posix(), 'checks': checks,
        'all_checks_pass': all(checks.values()), 'alert_lines': alerts,
        'advisory_LREAL_auto': 'try LREAL= Auto' in out,
        'advisory_NCORE1': 'default, NCORE=1' in stdout,
        'vasp_version': v.vasp_version, 'nkpts': len(v.actual_kpoints),
        'nbands': v.parameters['NBANDS'], 'nelect': v.parameters['NELECT'],
        'ncore': v.parameters.get('NCORE'), 'kpar': v.parameters.get('KPAR'),
        'scf_steps': len(s['electronic_steps']), 'last_scf_deltas_eV': [float(last[3]),float(last[4])],
        'highest_band_occupation': top_occupation, 'position_roundoff_A': position_error,
        'energies_eV': energy, 'forces_eV_A': force.tolist(),
        'stress_vasp_kbar': stress.tolist(), 'stress_ase_eV_A3': atoms.get_stress().tolist(),
        'xml_stress_antisymmetry_max_GPa': float(np.abs(stress-stress.T).max()*.1),
        'pressure_GPa': float(np.trace(stress)*0.1/3),
        'smearing_entropy_meV_atom': (energy['e_wo_entrp']-energy['e_fr_energy'])*1000/len(atoms),
        'sigma0_minus_free_meV_atom': (energy['e_0_energy']-energy['e_fr_energy'])*1000/len(atoms),
        'wall_seconds': wall,
        'core_sha256': {name:sha(p/name) for name in ['INCAR','POSCAR','KPOINTS','POTCAR','OUTCAR','OSZICAR','vasprun.xml','run-status.tsv','stdout.vasp','stderr.vasp']},
    }


def compare_pairs(records: list[dict], config: dict) -> list[dict]:
    refid = config['relative_energy_reference_structure']
    grouped = {}
    for rec in records:
        grouped.setdefault(rec['structure_id'], {})[rec['kmesh'][0]] = rec
    er = {k:grouped[refid][k]['energies_eV']['e_fr_energy'] for k in (6,7)}
    t = config['tolerances']
    rows = []
    for sid, pair in sorted(grouped.items()):
        a,b=pair[6],pair[7]
        f=np.asarray(a['forces_eV_A'])-np.asarray(b['forces_eV_A'])
        stress=(np.asarray(a['stress_vasp_kbar'])-np.asarray(b['stress_vasp_kbar']))*.1
        abs_e=(a['energies_eV']['e_fr_energy']-b['energies_eV']['e_fr_energy'])*1000/64
        rel_e=((a['energies_eV']['e_fr_energy']-er[6])-(b['energies_eV']['e_fr_energy']-er[7]))*1000/64
        metrics={'relative_energy_meV_atom':float(rel_e),
                 'force_component_RMS_eV_A':float(np.sqrt(np.mean(f*f))),
                 'force_component_max_eV_A':float(np.abs(f).max()),
                 'stress_component_max_GPa':float(np.abs(stress).max())}
        passes={key:abs(value)<=t[key] for key,value in metrics.items()}
        rows.append({'structure_id':sid,'temperature_K':a['temperature_K'],'volume_scale':a['volume_scale'],
                     'absolute_energy_difference_meV_atom':float(abs_e),**metrics,
                     'force_vector_max_eV_A':float(np.linalg.norm(f,axis=1).max()),
                     'pressure_difference_GPa':a['pressure_GPa']-b['pressure_GPa'],
                     'k6_wall_hours':a['wall_seconds']/3600,'k7_wall_hours':b['wall_seconds']/3600,
                     'k7_over_k6_wall_ratio':b['wall_seconds']/a['wall_seconds'],
                     'passes':passes,'all_budgets_pass':all(passes.values())})
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--results-dir',type=Path,default=ROOT/'hpc/results/zrc-dft600-k67-20261008')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dft/reviews/dft600-k67-20261008')
    args=parser.parse_args();base=args.results_dir.resolve();dest=args.output_dir.resolve()
    assert not dest.is_relative_to(base), 'Do not write analysis into raw results'
    config=json.loads((ROOT/'configs/experiments/zrc_dft600_k67.json').read_text())
    manifest=json.loads((base/'manifest.json').read_text())
    checksum_count=verify_checksums(base,'SHA256SUMS')
    original=ROOT/'dft/jobs/05_md_kmesh600'
    for line in (base/'SHA256SUMS').read_text().splitlines():
        _,name=line.split(maxsplit=1)
        assert (base/name).read_bytes()==(original/name).read_bytes(),name
    records=[]
    for task in manifest['tasks']:
        rec=audit_task(base,task);records.append(rec)
        failed = [key for key, value in rec['checks'].items() if not value]
        print(f"{rec['array_index']:02d} k{rec['kmesh'][0]} SCF={rec['scf_steps']} checks={rec['all_checks_pass']} failed={failed} top_occ={rec['highest_band_occupation']:.8g}",flush=True)
    assert len(records)==36
    pairs=compare_pairs(records,config)
    totals={k:sum(r['wall_seconds'] for r in records if r['kmesh'][0]==k) for k in (6,7)}
    maxima={key:max(pairs,key=lambda r:abs(r[key])) for key in config['tolerances']}
    summary={
        'review_date':'2026-10-08','results_directory':base.relative_to(ROOT).as_posix(),
        'original_bundle_checksums_verified':checksum_count,
        'task_count':len(records),'pairs_count':len(pairs),
        'all_numerical_integrity_checks_pass':all(r['all_checks_pass'] for r in records),
        'numerical_pattern_alerts':{r['array_index']:r['alert_lines'] for r in records if r['alert_lines']},
        'performance_advisories': {key:sum(r[key] for r in records) for key in ['advisory_LREAL_auto','advisory_NCORE1']},
        'all_pair_budgets_pass':all(p['all_budgets_pass'] for p in pairs),
        'tolerances':config['tolerances'],
        'maxima':{k:{'value':v[k],'structure_id':v['structure_id']} for k,v in maxima.items()},
        'wall_seconds_sum':totals,
        'k7_over_k6_wall_ratio':totals[7]/totals[6],
        'k6_wall_saving_fraction_vs_k7':1-totals[6]/totals[7],
        'cost_scope':'Sum of successful VASP wall times on 56 MPI ranks; excludes cancelled original22 and queue wait; different nodes prevent treating this as a controlled speed benchmark.',
        'scf_steps_range':[min(r['scf_steps'] for r in records),max(r['scf_steps'] for r in records)],
        'highest_band_occupation_max':max(r['highest_band_occupation'] for r in records),
        'xml_stress_antisymmetry_max_GPa':max(r['xml_stress_antisymmetry_max_GPa'] for r in records),
        'sigma0_minus_free_meV_atom_range':[min(r['sigma0_minus_free_meV_atom'] for r in records),max(r['sigma0_minus_free_meV_atom'] for r in records)],
        'raw_label_energy':'e_fr_energy (VASP TOTEN); no shifts applied to saved labels',
        'relative_energy_reference':config['relative_energy_reference_structure'],
    }
    dest.mkdir(parents=True,exist_ok=True)
    for name,data in [('runs.json',records),('pairs.json',pairs),('summary.json',summary)]:
        (dest/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    cols=[k for k in pairs[0] if k!='passes']
    with (dest/'kmesh-comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader();writer.writerows({k:p[k] for k in cols} for p in pairs)
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
