"""Audit returned stage-1 VASP runs without changing raw calculation files."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from ase.io import read
from pymatgen.io.vasp.inputs import Incar, Kpoints, Poscar
from pymatgen.io.vasp.outputs import Vasprun, Outcar

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dft/reviews'
ORDER = ['encut_520_k8', 'encut_600_k8', 'encut_700_k8', 'encut_800_k8',
         'encut_800_k4', 'encut_800_k6', 'encut_800_k10',
         'sigma_0.05', 'sigma_0.20', 'ediff_1e-8', 'spin_check']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(name, stage_directory='01_convergence'):
    p = ROOT / 'dft/jobs' / stage_directory / name
    record = json.loads((p / 'job.json').read_text())
    meta = json.loads((p / 'POTCAR.meta.json').read_text())
    incar = Incar.from_file(p / 'INCAR')
    v = Vasprun(p / 'vasprun.xml', parse_dos=False,
                parse_projected_eigen=False, parse_potcar_file=False)
    s = v.ionic_steps[-1]
    a = read(p / 'vasprun.xml', index=-1)
    out = (p / 'OUTCAR').read_text()
    oc = Outcar(p / 'OUTCAR')
    last = [l.split() for l in (p / 'OSZICAR').read_text().splitlines()
            if l.startswith(('DAV:', 'RMM:'))][-1]
    stderr = list(p.glob('stderr.*'))
    kp = list(Kpoints.from_file(p / 'KPOINTS').kpts[0])
    checks = {
        'input_incar_matches_job': incar == Incar(record['incar']),
        'xml_incar_matches_input': v.incar == incar,
        'actual_key_parameters_match_input': all(v.parameters['ENMAX' if k == 'ENCUT' else k] == incar[k]
            for k in ['ENCUT', 'EDIFF', 'ISPIN', 'ISMEAR', 'SIGMA', 'NSW', 'ISYM', 'LREAL', 'LASPH', 'ADDGRID']),
        'kmesh_matches_job_and_output': kp == record['kmesh'] == list(v.kpoints.kpts[0]),
        'poscar_hash_matches_job': sha(p / 'POSCAR') == record['poscar_sha256'],
        'potcar_hash_matches_job': sha(p / 'POTCAR') == record['potcar_sha256'],
        'source_potcar_matches': (p / 'POTCAR').read_bytes() == b''.join(
            (ROOT / x['source_path']).read_bytes() for x in meta['potentials']),
        'output_potentials_match': all(x['embedded_sha256'] in out and x['title'] in out
            for x in meta['potentials']),
        'normal_end': 'General timing and accounting' in out,
        'electronic_converged': bool(v.converged_electronic),
        'ediff_reached': 'aborting loop because EDIFF is reached' in out,
        'last_scf_deltas_below_ediff': max(abs(float(last[3])), abs(float(last[4]))) < incar['EDIFF'],
        'stderr_empty': bool(stderr) and all(f.stat().st_size == 0 for f in stderr),
        'single_static_step': len(v.ionic_steps) == 1 and v.final_structure == v.initial_structure,
        'output_structure_matches_input': bool(np.allclose(v.initial_structure.cart_coords,
            Poscar.from_file(p / 'POSCAR').structure.cart_coords, atol=1e-7) and
            np.allclose(v.initial_structure.lattice.matrix,
            Poscar.from_file(p / 'POSCAR').structure.lattice.matrix, atol=1e-7)),
        'finite_labels': bool(np.isfinite(s['forces']).all() and np.isfinite(s['stress']).all()
                             and np.isfinite(s['e_fr_energy'])),
        'ase_energy_matches': abs(a.get_potential_energy(force_consistent=True) - s['e_fr_energy']) < 1e-7,
        'ase_forces_match': bool(np.allclose(a.get_forces(), s['forces'], atol=1e-8)),
        'ase_stress_sign_units_match': bool(np.allclose(a.get_stress(voigt=False),
            -np.asarray(s['stress']) * 0.1 / 160.21766208, atol=1e-8)),
        'top_band_empty': max(float(e[:, -1, 1].max()) for e in v.eigenvalues.values()) < 1e-6,
    }
    core = ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR', 'POTCAR.meta.json',
            'OUTCAR', 'OSZICAR', 'vasprun.xml', 'CONTCAR', 'JobModel']
    core += [f.name for f in p.glob('std*.*')]
    return {
        'name': name, 'job_path': p.relative_to(ROOT).as_posix(),
        'slurm_run_ids': [f.name.split('.')[-1] for f in p.glob('stdout.*')],
        'checks': {k: bool(ok) for k, ok in checks.items()}, 'all_checks_pass': all(checks.values()),
        'vasp_version': v.vasp_version, 'natoms': len(a), 'kmesh': kp,
        'actual_parameters': {k: v.parameters.get(k, v.incar.get(k)) for k in
            ['ENCUT', 'EDIFF', 'ISPIN', 'ISMEAR', 'SIGMA', 'NELECT', 'NBANDS', 'NCORE', 'KPAR', 'ISYM']},
        'nkpts': len(v.actual_kpoints), 'electronic_steps': len(s['electronic_steps']),
        'last_scf_deltas_eV': [float(last[3]), float(last[4])],
        'energies_eV': {k: float(s[k]) for k in ['e_fr_energy', 'e_wo_entrp', 'e_0_energy']},
        'entropy_magnitude_meV_atom': abs(s['e_wo_entrp'] - s['e_fr_energy']) * 1000 / len(a),
        'forces_eV_A': np.asarray(s['forces']).tolist(),
        'stress_vasp_kbar': np.asarray(s['stress']).tolist(),
        'stress_ase_eV_A3': a.get_stress().tolist(),
        'pressure_GPa': float(np.trace(s['stress']) / 3 * 0.1),
        'maximum_force_norm_eV_A': float(np.linalg.norm(s['forces'], axis=1).max()),
        'total_magnetization_muB': oc.total_mag,
        'local_magnetization_muB': list(oc.magnetization),
        'highest_band_occupancy': max(float(e[:, -1, 1].max()) for e in v.eigenvalues.values()),
        'wall_seconds': float(re.search(r'Elapsed time \(sec\):\s*([\d.]+)', out).group(1)),
        'source_group': record['source_group'], 'poscar_sha256': sha(p / 'POSCAR'),
        'core_file_sha256': {n: sha(p / n) for n in core if (p / n).exists()},
    }


def compare(a, b, kind):
    f = np.asarray(a['forces_eV_A']) - np.asarray(b['forces_eV_A'])
    stress = (np.asarray(a['stress_vasp_kbar']) - np.asarray(b['stress_vasp_kbar'])) * 0.1
    energy = {k: (a['energies_eV'][k] - b['energies_eV'][k]) * 1000 / a['natoms']
              for k in a['energies_eV']}
    rmse = float(np.sqrt(np.mean(f * f)))
    fm = float(np.max(np.abs(f)))
    sm = float(np.max(np.abs(stress)))
    return dict(job=a['name'], reference=b['name'], comparison=kind,
                signed_energy_difference_meV_atom=energy,
                force_component_RMS_eV_A=rmse, force_component_max_eV_A=fm,
                force_vector_max_eV_A=float(np.linalg.norm(f, axis=1).max()),
                stress_component_max_GPa=sm,
                meets_project_tolerances=abs(energy['e_fr_energy']) <= 1 and rmse <= .01 and fm <= .03 and sm <= .1)


def main():
    records = {n: audit(n) for n in ORDER}
    assert len({r['poscar_sha256'] for r in records.values()}) == 1
    comparisons = []
    for n in ['encut_520_k8', 'encut_600_k8', 'encut_700_k8']:
        comparisons.append(compare(records[n], records['encut_800_k8'], 'cutoff'))
    for n in ['encut_800_k4', 'encut_800_k6', 'encut_800_k8']:
        comparisons.append(compare(records[n], records['encut_800_k10'], 'kmesh'))
    for n in ['sigma_0.05', 'sigma_0.20', 'ediff_1e-8']:
        comparisons.append(compare(records[n], records['encut_800_k10'], 'smearing_or_scf'))
    comparisons.append(compare(records['spin_check'], records['encut_600_k8'], 'spin'))
    for n in ['encut_600_k8', 'encut_700_k8']:
        comparisons.append(compare(records[n], records['encut_800_k10'], 'combined_cutoff_and_kmesh'))
    report = {'schema_version': 1, 'review_date': '2026-09-21',
              'scope': 'One constructed distorted eight-atom ZrC cell; no high-temperature certification',
              'all_runs_valid': all(r['all_checks_pass'] for r in records.values()),
              'tolerances': {'energy_meV_atom': 1, 'force_component_RMS_eV_A': .01,
                             'force_component_max_eV_A': .03, 'stress_component_max_GPa': .1},
              'jobs': list(records.values()), 'comparisons': comparisons}
    DEST.mkdir(exist_ok=True)
    (DEST / 'convergence-2026-09-21.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for n, r in records.items():
        print(n, 'PASS' if r['all_checks_pass'] else 'FAIL',
              r['actual_parameters'], 'steps', r['electronic_steps'], 'mag', r['total_magnetization_muB'],
              'failed_checks', [k for k, ok in r['checks'].items() if not ok])
    print(json.dumps(comparisons, indent=2))


if __name__ == '__main__':
    main()
