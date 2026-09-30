"""Audit supplemental runs and compare with the earlier reference."""
import json
import re
from review_zrc_convergence import ROOT, DEST, audit, compare, sha


def main():
    previous = json.loads((DEST / 'convergence-2026-09-21.json').read_text(encoding='utf-8'))
    old = next(j for j in previous['jobs'] if j['name'] == 'encut_800_k10')
    for filename, expected in old['core_file_sha256'].items():
        assert sha(ROOT / old['job_path'] / filename) == expected
    names = ['encut_800_k12', 'encut_800_k14', 'encut_900_k14']
    records = {n: audit(n, '01b_confirmation') for n in names}
    records['encut_800_k10'] = audit('encut_800_k10')
    assert len({r['poscar_sha256'] for r in records.values()}) == 1
    for r in records.values():
        p = ROOT / r['job_path']
        diagnostics = []
        for output in [p / 'OUTCAR', *p.glob('stdout.*'), *p.glob('stderr.*')]:
            for line_number, line in enumerate(output.read_text(errors='replace').splitlines(), 1):
                if re.search(r'WARNING:|internal ERROR|BRMIX:|EDDDAV:|ZBRENT:|VERY BAD NEWS|MPI_ABORT|SIGSEGV|segmentation fault', line, re.I):
                    diagnostics.append({'file': output.relative_to(ROOT).as_posix(), 'line': line_number, 'text': line.strip()})
        r['diagnostics'] = diagnostics
        r['unresolved_physical_warning'] = bool(diagnostics)
        r['reference_warning_screen_passed'] = not diagnostics
    pairs = [
        ('encut_800_k10', 'encut_800_k12', 'kmesh'),
        ('encut_800_k10', 'encut_800_k14', 'kmesh'),
        ('encut_800_k12', 'encut_800_k14', 'kmesh'),
        ('encut_800_k14', 'encut_900_k14', 'cutoff'),
        ('encut_800_k10', 'encut_900_k14', 'joint'),
        ('encut_800_k12', 'encut_900_k14', 'joint'),
    ]
    comparisons = [compare(records[a], records[b], kind) for a, b, kind in pairs]
    for c in comparisons:
        c['unresolved_warning_in_comparison'] = any(records[n]['unresolved_physical_warning'] for n in [c['job'], c['reference']])
        c['numeric_pass_with_warning_screen'] = c['meets_project_tolerances'] and not c['unresolved_warning_in_comparison']
    result = dict(schema_version=2, review_date='2026-09-21',
        scope='Same constructed distorted eight-atom ZrC cell; larger cells and high-temperature frames remain unvalidated',
        all_runs_integrity_passed=all(r['all_checks_pass'] for r in records.values()),
        all_runs_warning_screen_passed=all(r['reference_warning_screen_passed'] for r in records.values()),
        production_protocol_certified=False,
        tolerances=previous['tolerances'], jobs=list(records.values()), comparisons=comparisons)
    (DEST / 'confirmation-2026-09-21.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for r in records.values():
        print(r['name'], 'PASS' if r['all_checks_pass'] else 'FAIL',
              'steps', r['electronic_steps'], 'version', r['vasp_version'],
              'run_ids', r['slurm_run_ids'], 'top_occupation', r['highest_band_occupancy'],
              'failed_checks', [k for k, v in r['checks'].items() if not v])
    print(json.dumps(comparisons, indent=2))


if __name__ == '__main__':
    main()
