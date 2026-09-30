"""Assemble existing jobs from the user's local PAW-PBE library, without submission.

Plain and gzip inputs use the standard library. Unix .Z inputs use libarchive-c
and libarchive (already installed in this workspace's Conda base environment).
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))


def load_potential(root, name):
    folder = root / name
    paths = [folder / f for f in ('POTCAR', 'POTCAR.gz', 'POTCAR.Z') if (folder / f).is_file()]
    if len(paths) != 1:
        raise ValueError(f'Expected one unambiguous source in {folder}: {paths}')
    path = paths[0]
    raw = path.read_bytes()
    if raw.startswith(b'\x1f\x8b'):
        data = gzip.decompress(raw)
    elif raw.startswith(b'\x1f\x9d'):
        dll_handle = None
        if os.name == 'nt':
            dll_dir = Path(sys.prefix) / 'Library/bin'
            dll_path = dll_dir / 'archive.dll'
            if dll_path.is_file():
                os.environ.setdefault('LIBARCHIVE', str(dll_path))
                dll_handle = os.add_dll_directory(str(dll_dir))
        import libarchive
        try:
            with libarchive.file_reader(str(path), format_name='raw') as archive:
                entries = [b''.join(entry.get_blocks()) for entry in archive]
            if len(entries) != 1:
                raise ValueError(f'Unexpected archive contents: {path}')
            data = entries[0]
        finally:
            if dll_handle is not None:
                dll_handle.close()
    else:
        data = raw
    text = data.decode('ascii')
    titles = re.findall(r'^\s*TITEL\s*=\s*(.+)$', text, re.M)
    if len(titles) != 1 or titles[0].split()[:2] != ['PAW_PBE', name]:
        raise ValueError(f'Wrong PAW-PBE species in {path}: {titles}')
    if re.findall(r'LEXCH\s*=\s*(\w+)', text) != ['PE']:
        raise ValueError(f'Wrong exchange-correlation identifier: {path}')
    if len(re.findall(r'^\s*End of Dataset\s*$', text, re.M)) != 1 or not text.rstrip().endswith('End of Dataset'):
        raise ValueError(f'Missing/extra dataset boundary: {path}')
    if not data.endswith(b'\n') or data.startswith(b'\xef\xbb\xbf'):
        raise ValueError(f'Unexpected source encoding/boundary: {path}')
    vrhfin = re.search(r'VRHFIN\s*=\s*([A-Za-z]+)\s*:', text).group(1)
    if vrhfin != name.split('_')[0] or not re.search(r'LPAW\s*=\s*T\b', text):
        raise ValueError(f'Invalid PAW element: {path}')
    metadata = dict(name=name, element=vrhfin, title=titles[0].strip(),
                    lexch='PE', enmax_eV=float(re.search(r'ENMAX\s*=\s*([\d.]+)', text).group(1)),
                    zval=float(re.search(r'ZVAL\s*=\s*([\d.]+)', text).group(1)),
                    source_path=path.relative_to(PROJECT).as_posix() if path.is_relative_to(PROJECT) else str(path),
                    source_sha256=sha(raw), decompressed_sha256=sha(data), bytes=len(data),
                    embedded_sha256=(re.search(r'SHA256\s*=\s*([0-9a-fA-F]{64})', text).group(1)
                                     if re.search(r'SHA256\s*=\s*([0-9a-fA-F]{64})', text) else None))
    return data, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pp-root', type=Path, default=PROJECT / 'dft/psudopotential/potpaw_PBE.64')
    parser.add_argument('--release', default='potpaw_PBE.64')
    parser.add_argument('--source-archive', type=Path, default=PROJECT / 'dft/potpaw_PBE.64.tgz')
    args = parser.parse_args()
    source_root = args.pp_root.resolve()
    source_dir = source_root.relative_to(PROJECT).as_posix() if source_root.is_relative_to(PROJECT) else str(source_root)
    archive = args.source_archive.resolve()
    archive_record = dict(path=archive.relative_to(PROJECT).as_posix() if archive.is_relative_to(PROJECT) else str(archive), sha256=sha(archive.read_bytes()))
    root = PROJECT / 'dft/jobs'
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    sources = {name: load_potential(args.pp_root.resolve(), name) for name in ('Zr_sv', 'C')}
    planned = []
    # Validate all jobs and existing destinations before writing any POTCAR.
    for job in manifest['jobs']:
        folder = (root / job['path']).resolve()
        if not folder.is_relative_to(root.resolve()):
            raise ValueError('Job path escapes jobs directory')
        poscar = (folder / 'POSCAR').read_bytes()
        lines = poscar.decode('utf-8').splitlines()
        species, counts = lines[5].split(), list(map(int, lines[6].split()))
        if species != job['species'] or counts != job['counts'] or sha(poscar) != job['poscar_sha256']:
            raise ValueError(f'POSCAR differs from job record: {folder}')
        names = ['Zr_sv' if e == 'Zr' else e for e in species]
        if names != job['recommended_potentials']:
            raise ValueError(f'Unexpected potential selection: {folder}')
        data = b''.join(sources[name][0] for name in names)
        entries = [sources[name][1] for name in names]
        incar = (folder / 'INCAR').read_text(encoding='utf-8')
        encut = float(re.search(r'^\s*ENCUT\s*=\s*([\d.]+)', incar, re.M).group(1))
        max_enmax = max(entry['enmax_eV'] for entry in entries)
        if encut < max_enmax or encut != float(job['incar']['ENCUT']):
            raise ValueError(f'ENCUT too small or record mismatch: {folder}')
        if re.search(r'^\s*ISIF\s*=\s*3\s*$', incar, re.M) and encut < 1.3 * max_enmax:
            raise ValueError(f'Cell relaxation cutoff below 1.3 ENMAX: {folder}')
        if not re.search(r'^\s*GGA\s*=\s*PE\s*$', incar, re.M | re.I):
            raise ValueError(f'Unexpected functional: {folder}')
        output = folder / 'POTCAR'
        if output.exists() and output.read_bytes() != data:
            raise FileExistsError(f'Refusing to overwrite a different POTCAR: {output}')
        meta = dict(assembly='binary_concatenation_in_POSCAR_species_order', species=species,
                    potentials=entries, sha256=sha(data), bytes=len(data), dataset_count=len(names),
                    max_enmax_eV=max_enmax, encut_eV=encut, source_release=args.release,
                    source_archive=archive_record,
                    source_release_note='Release declared by user-supplied archive; archive and source bytes recorded, not authenticated against the VASP portal.')
        planned.append((folder, data, meta, job))
    for folder, data, meta, job in planned:
        (folder / 'POTCAR').write_bytes(data)
        write_json(folder / 'POTCAR.meta.json', meta)
        job.update(protocol_id=manifest['protocol_id'], potcar_release=args.release, potcar_sha256=meta['sha256'], potcar_metadata='POTCAR.meta.json',
                   input_status='potcar_assembled_requires_cluster_smoke_and_convergence')
        write_json(folder / 'job.json', job)
    manifest.update(potcar_preparation='assembled_from_user_supplied_local_library',
                    potential_release=args.release, potential_source_directory=source_dir, source_archive=archive_record,
                    potential_identity_file='potcar-inventory.json')
    write_json(root / 'manifest.json', manifest)
    write_json(root / 'potcar-inventory.json', dict(
        source_directory=source_dir, source_release=args.release, source_archive=archive_record,
        protocol_id=manifest['protocol_id'],
        source_note='User-supplied potpaw archive; per-potential dates are not the library release date. Portal authenticity not independently verified.',
        potentials=[v[1] for v in sources.values()], job_count=len(planned),
        jobs=[dict(path=job['path'], species=meta['species'], sha256=meta['sha256'],
                   encut_eV=meta['encut_eV']) for _, _, meta, job in planned], vasp_executed=False))
    print(f'Assembled and checked {len(planned)} POTCAR files.')
    for _, meta in sources.values():
        print(f"{meta['title']}: ZVAL={meta['zval']}, ENMAX={meta['enmax_eV']} eV")


if __name__ == '__main__':
    main()
