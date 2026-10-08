"""Read-only recovery of recorded MACE predictions and matched DFT comparison.

No model inference, MD, model download, or modification of scientific inputs.
Energy reference is fixed calibration structure 01; no per-temperature fitting.
"""
from pathlib import Path
import csv
import hashlib
import importlib.metadata
import json
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
from ase.io import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dft/reviews/dft600-k67-20261008/mace'
DFT = ROOT / 'hpc/results/zrc-dft600-k67-20261008'
CONV = 160.21766208


def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def csvout(name, rows):
    """Export scalar mappings only; exact array labels remain in JSON."""
    with (OUT / name).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def max_delta(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


def vec(node):
    return np.array([[float(x) for x in v.text.split()] for v in node.findall('v')])


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'dft/structures/zrc_calibration18/manifest.json'
    manifest = load(manifest_path)
    expected_model = load(ROOT / 'configs/experiments/zrc_mace_round1.json')['model']
    assert sha(ROOT / expected_model['path']) == expected_model['sha256']
    records = []
    for s in manifest['structures']:
        source = ROOT / s['source_path']
        assert sha(source) == s['source_sha256']
        frame = read(source, index=s['frame_index_zero_based'], format='extxyz')
        poscar = ROOT / s['POSCAR']
        assert sha(poscar) == s['POSCAR_sha256']
        atom = read(poscar, format='vasp')
        assert len(atom) == len(frame) == 64
        assert np.array_equal(atom.numbers, frame.numbers)
        delta = frame.get_scaled_positions(wrap=False) - atom.get_scaled_positions(wrap=False)
        delta -= np.round(delta)
        pos_delta = float(np.max(np.abs(delta @ atom.cell.array)))
        cell_delta = max_delta(frame.cell, atom.cell)
        assert pos_delta < 1e-10 and cell_delta < 1e-10
        assert frame.info['job_id'] == s['job_id']
        assert frame.info['step'] == s['step']
        segment_path = source.with_name('segment.json')
        segment = load(segment_path)
        assert segment['model_sha256'] == expected_model['sha256']
        assert segment['head'] == expected_model['head'] == 'omat_pbe'
        assert segment['dtype'] == expected_model['dtype'] == 'float32'
        assert segment['versions']['mace-torch'] == '0.3.16'
        log_path = source.with_name('log.jsonl')
        log = [json.loads(x) for x in log_path.read_text(encoding='utf-8').splitlines() if x.strip()]
        row = next(v for v in log if v['step'] == s['step'])
        energy = float(frame.info['model_energy'])
        forces = np.asarray(frame.arrays['model_forces'], dtype=float)
        stress = np.asarray(frame.info['model_stress'], dtype=float)
        pressure = float(-np.mean(stress[:3]) * CONV)
        force_norm_delta = abs(float(np.linalg.norm(forces, axis=1).max()) - row['max_force_eV_A'])
        assert forces.shape == (64, 3) and stress.shape == (6,)
        assert np.isfinite(forces).all() and np.isfinite(stress).all() and np.isfinite(energy)
        assert abs(energy - row['potential_eV']) < 1e-9
        assert abs(energy / 64 - s['MACE_energy_eV_atom']) < 1e-12
        # MD pressure metadata includes momenta, so it is not static DFT pressure.
        # float32 mean reduction in the MD logger leads to ~micro-GPa rounding.
        pressure_delta = abs(pressure - row['potential_pressure_GPa'])
        assert pressure_delta < 1e-5
        assert force_norm_delta < 2e-6
        rec = {
            'structure_id': s['structure_id'], 'frame_id': s['frame_id'],
            'target_temperature_K': s['target_temperature_K'], 'volume_scale': s['volume_scale'],
            'natoms': 64, 'symbols': atom.get_chemical_symbols(),
            'energy_eV': energy, 'energy_eV_atom': energy / 64,
            'forces_eV_A': forces.tolist(),
            'stress_ase_voigt_eV_A3': stress.tolist(),
            'stress_tension_positive_GPa': (stress * CONV).tolist(),
            'potential_pressure_GPa': pressure,
            'MD_total_pressure_with_kinetic_GPa_NOT_static_reference': row['pressure_GPa'],
            'cell_A': atom.cell.array.tolist(), 'positions_A': atom.positions.tolist(),
            'source_path': s['source_path'], 'source_sha256': s['source_sha256'],
            'frame_index_zero_based': s['frame_index_zero_based'],
            'POSCAR': s['POSCAR'], 'POSCAR_sha256': s['POSCAR_sha256'],
            'segment_path': segment_path.relative_to(ROOT).as_posix(), 'segment_sha256': sha(segment_path),
            'log_sha256': sha(log_path), 'segment_metadata': segment,
            'verification': {
                'source_sha256_matches_frozen_manifest': True,
                'input_atom_order_identical': True,
                'periodic_position_max_component_delta_A': pos_delta,
                'cell_max_component_delta_A': cell_delta,
                'energy_matches_log_and_manifest': True,
                'potential_pressure_matches_log_delta_GPa': pressure_delta,
                'maximum_force_norm_matches_log_delta_eV_A': force_norm_delta,
            },
        }
        records.append(rec)
        print('Recovered', s['structure_id'], flush=True)
    assert len(records) == 18
    provenance = {
        'method': 'reuse verified recorded model predictions; no new inference',
        'model': expected_model, 'model_file_sha256_verified': True,
        'frozen_calibration_manifest_sha256': sha(manifest_path),
        'reference_structure_id': manifest['reference_structure_id'],
        'stress_convention': 'ASE tension-positive; Voigt xx yy zz yz xz xy; eV/A^3',
        'pressure_convention': '-trace(static potential stress)/3; compression positive; no kinetic term',
        'conversion_eV_A3_to_GPa': CONV,
        'rounding_caveat': 'MD forces and positions stored in extxyz at 8 decimal places; predictions originally evaluated before coordinate serialization; POSCAR preserves exported rounded positions modulo cell with unchanged atom order.',
        'scope': '18 calibration structures, not held-out test data; parent audit controls DFT acceptance',
        'python': sys.version,
        'analysis_versions': {p: importlib.metadata.version(p) for p in ('ase', 'numpy')},
        'script_sha256': sha(Path(__file__)),
    }
    dump('mace18-recorded-predictions.json', {'provenance': provenance, 'structures': records})
    dft_records = []
    comparisons = []
    independent_checks = []
    for m in records:
        for mesh in (6, 7):
            task = DFT / 'structures' / m['structure_id'] / f'k{mesh}'
            runs = sorted((task / 'runs').glob('*'))
            good = [r for r in runs if (r / 'vasprun.xml').exists() and '</modeling>' in (r / 'vasprun.xml').read_text(errors='replace')[-300:]]
            assert len(good) == 1, (task, good)
            run = good[0]
            assert sha(run / 'POSCAR') == m['POSCAR_sha256']
            xml_path = run / 'vasprun.xml'
            xml = ET.parse(xml_path).getroot()
            steps = xml.findall('calculation')
            assert len(steps) == 1
            step = steps[0]
            energies = {i.attrib['name']: float(i.text) for i in step.find('energy').findall('i')}
            f = vec(step.find("varray[@name='forces']"))
            stress_kbar = vec(step.find("varray[@name='stress']"))
            # Match ASE's VASP XML reader: use upper-triangle xy/xz/yz values.
            # XML can carry tiny antisymmetric residuals from printed rounding;
            # averaging opposite off-diagonals would differ from that reader.
            stress_ase = -stress_kbar.reshape(9)[[0, 4, 8, 5, 2, 1]] * .1 / CONV
            assert f.shape == (64, 3) and stress_kbar.shape == (3, 3)
            assert np.isfinite(f).all() and np.isfinite(stress_ase).all()
            # A separate parser and OUTCAR independently check energy and stress conventions.
            ase_dft = read(xml_path, index=-1)
            outcar_text = (run / 'OUTCAR').read_text(errors='replace')
            outcar_toten = float(re.findall(r'free\s+energy\s+TOTEN\s*=\s*([-+\d.Ee]+)', outcar_text)[-1])
            checks = {
                'ase_force_consistent_energy_delta_eV': abs(ase_dft.get_potential_energy(force_consistent=True) - energies['e_fr_energy']),
                'OUTCAR_TOTEN_delta_eV': abs(outcar_toten - energies['e_fr_energy']),
                'ase_forces_max_delta_eV_A': max_delta(ase_dft.get_forces(), f),
                'ase_stress_max_delta_eV_A3': max_delta(ase_dft.get_stress(), stress_ase),
                'XML_stress_antisymmetric_residual_max_kbar': max_delta(stress_kbar, stress_kbar.T),
            }
            assert checks['ase_force_consistent_energy_delta_eV'] < 1e-7
            assert checks['OUTCAR_TOTEN_delta_eV'] < 1e-7
            assert checks['ase_forces_max_delta_eV_A'] < 1e-10
            assert checks['ase_stress_max_delta_eV_A3'] < 1e-8
            independent_checks.append({'structure_id': m['structure_id'], 'kmesh': mesh, 'checks': checks})
            df = np.asarray(m['forces_eV_A']) - f
            ds = np.asarray(m['stress_tension_positive_GPa']) - stress_ase * CONV
            pressure_dft = float(np.trace(stress_kbar) * .1 / 3)
            dr = {'structure_id': m['structure_id'], 'kmesh': mesh, 'run_path': run.relative_to(ROOT).as_posix(),
                  'vasprun_sha256': sha(xml_path), 'energies_eV': energies,
                  'forces_eV_A': f.tolist(), 'stress_vasp_compression_positive_kbar': stress_kbar.tolist(),
                  'stress_ase_voigt_eV_A3': stress_ase.tolist(), 'pressure_GPa': pressure_dft}
            dft_records.append(dr)
            c = {'structure_id': m['structure_id'], 'kmesh': mesh,
                 'target_temperature_K': m['target_temperature_K'], 'volume_scale': m['volume_scale'],
                 'mace_energy_eV': m['energy_eV'], 'dft_energies_eV': energies,
                 'raw_mace_minus_DFT_energy_meV_atom': {k: (m['energy_eV'] - v) / 64 * 1000 for k, v in energies.items()},
                 'force_component_RMSE_eV_A': rms(df), 'force_component_MAE_eV_A': float(np.mean(np.abs(df))),
                 'force_component_max_abs_eV_A': float(np.max(np.abs(df))),
                 'force_vector_max_error_eV_A': float(np.linalg.norm(df, axis=1).max()),
                 'mace_force_component_RMS_eV_A': rms(m['forces_eV_A']),
                 'dft_force_component_RMS_eV_A': rms(f),
                 'force_relative_RMSE': rms(df) / rms(f),
                 'stress_6_component_RMSE_GPa': rms(ds), 'stress_component_max_abs_GPa': float(np.max(np.abs(ds))),
                 'stress_6_component_error_GPa': ds.tolist(),
                 'mace_potential_pressure_GPa': m['potential_pressure_GPa'],
                 'dft_static_pressure_GPa': pressure_dft,
                 'mace_minus_DFT_pressure_GPa': m['potential_pressure_GPa'] - pressure_dft,
                 'species_force_component_RMSE_eV_A': {symbol: rms(df[np.asarray(m['symbols']) == symbol]) for symbol in ('Zr', 'C')},
                 'DFT_TOTEN_minus_sigma0_meV_atom': (energies['e_fr_energy'] - energies['e_0_energy']) / 64 * 1000,
                 }
            comparisons.append(c)
    reference = manifest['reference_structure_id']
    for mesh in (6, 7):
        ref = next(c for c in comparisons if c['kmesh'] == mesh and c['structure_id'] == reference)
        for c in comparisons:
            if c['kmesh'] == mesh:
                c['reference01_aligned_mace_minus_DFT_energy_meV_atom'] = {
                    k: v - ref['raw_mace_minus_DFT_energy_meV_atom'][k]
                    for k, v in c['raw_mace_minus_DFT_energy_meV_atom'].items()}
    summaries = []
    for mesh in (6, 7):
        for temp in [None, 300, 1500, 3000, 4500, 5250, 6000]:
            rows = [c for c in comparisons if c['kmesh'] == mesh and (temp is None or c['target_temperature_K'] == temp)]
            summaries.append({
                'kmesh': mesh, 'target_temperature_K': temp, 'n_structures': len(rows),
                'force_component_RMSE_eV_A': rms([c['force_component_RMSE_eV_A'] for c in rows]),
                'force_component_max_abs_eV_A': max(c['force_component_max_abs_eV_A'] for c in rows),
                'stress_6_component_RMSE_GPa': rms([c['stress_6_component_RMSE_GPa'] for c in rows]),
                'stress_component_max_abs_GPa': max(c['stress_component_max_abs_GPa'] for c in rows),
                'mean_signed_pressure_error_GPa': float(np.mean([c['mace_minus_DFT_pressure_GPa'] for c in rows])),
                'reference01_aligned_energy_RMSE_meV_atom': {key: rms([c['reference01_aligned_mace_minus_DFT_energy_meV_atom'][key] for c in rows]) for key in ('e_fr_energy', 'e_0_energy')},
                'reference01_aligned_energy_mean_error_meV_atom': {key: float(np.mean([c['reference01_aligned_mace_minus_DFT_energy_meV_atom'][key] for c in rows])) for key in ('e_fr_energy', 'e_0_energy')},
                'reference01_aligned_energy_max_abs_error_meV_atom': {key: max(abs(c['reference01_aligned_mace_minus_DFT_energy_meV_atom'][key]) for c in rows) for key in ('e_fr_energy', 'e_0_energy')},
            })
    dump('DFT36-extracted-for-comparison.json', {'stress_conversion': 'ASE = -VASP_kbar * 0.1 / 160.21766208; Voigt xx yy zz yz xz xy uses XML upper triangle, matching ASE VASP reader; raw 3x3 retained', 'records': dft_records})
    dump('independent-ase-verification.json', {'all_checks_passed': True, 'DFT_count': len(independent_checks),
         'stress_note': 'XML stress has tiny antisymmetric/printed-rounding residuals. Upper triangle is used, matching ASE VASP reader; residuals are recorded below, not silently averaged.',
         'checks': independent_checks})
    dump('mace-vs-DFT36.json', {'provenance': provenance,
         'energy_note': 'Both e_fr_energy (TOTEN/free energy, force-consistent) and e_0_energy (sigma->0 estimate) included; do not treat them as identical. Model training-target convention needs separate provenance check.',
         'comparison_sign': 'MACE minus DFT', 'comparisons': comparisons, 'summaries': summaries})
    frame_rows = []
    for c in comparisons:
        row = {k: v for k, v in c.items() if not isinstance(v, (dict, list))}
        for key in ('e_fr_energy', 'e_wo_entrp', 'e_0_energy'):
            row['DFT_' + key + '_eV'] = c['dft_energies_eV'][key]
            row['raw_mace_minus_DFT_' + key + '_meV_atom'] = c['raw_mace_minus_DFT_energy_meV_atom'][key]
            row['reference01_aligned_mace_minus_DFT_' + key + '_meV_atom'] = c['reference01_aligned_mace_minus_DFT_energy_meV_atom'][key]
        for symbol in ('Zr', 'C'):
            row[symbol + '_force_component_RMSE_eV_A'] = c['species_force_component_RMSE_eV_A'][symbol]
        for component, value in zip(('xx', 'yy', 'zz', 'yz', 'xz', 'xy'), c['stress_6_component_error_GPa']):
            row['stress_error_' + component + '_GPa'] = value
        frame_rows.append(row)
    csvout('mace-vs-DFT-per-frame.csv', frame_rows)
    summary_rows = []
    for s in summaries:
        row = {k: ('all' if v is None else v) for k, v in s.items() if not isinstance(v, dict)}
        for metric in ('RMSE', 'mean_error', 'max_abs_error'):
            for key in ('e_fr_energy', 'e_0_energy'):
                row['reference01_aligned_' + key + '_' + metric + '_meV_atom'] = s['reference01_aligned_energy_' + metric + '_meV_atom'][key]
        summary_rows.append(row)
    csvout('mace-vs-DFT-by-temperature.csv', summary_rows)
    print(json.dumps([s for s in summaries if s['kmesh'] == 7], indent=2))


if __name__ == '__main__':
    main()
