"""Prepare ideal periodic starting boxes, not equilibrated MD/DFT structures."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from ase.build import bulk
from ase.io import read, write


def main():
    root = Path(__file__).resolve().parents[1]
    config_path = root / "configs/experiments/zrc_mace_sampling.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    structure = config["structure"]
    out = root / structure["input_directory"]
    out.mkdir(parents=True, exist_ok=True)
    a = structure["a_start_A"]
    base = bulk("ZrC", "rocksalt", a=a, cubic=True)
    entries = []
    for repeat in [1, 2, 3, 4]:
        ratios = structure["volume_ratios"] if repeat in [2, 3] else [1.0]
        for ratio in ratios:
            atoms = base.repeat((repeat,) * 3)
            atoms = atoms[[i for symbol in ["Zr", "C"] for i, atom in enumerate(atoms) if atom.symbol == symbol]]
            atoms.set_cell(atoms.cell * ratio ** (1/3), scale_atoms=True)
            atoms.wrap()
            stem = f"zrc{len(atoms)}_v{round(ratio*100):03d}"
            atoms.info.update(structure_id=stem, reference_id=out.name,
                              provenance="ideal_starting_structure_NOT_equilibrated_NOT_DFT_labeled",
                              a_start_A=a, volume_ratio_to_start=ratio)
            poscar, xyz = out / f"{stem}.POSCAR", out / f"{stem}.extxyz"
            write(poscar, atoms, format="vasp", direct=True, vasp5=True, sort=False)
            write(xyz, atoms, format="extxyz")
            for path in [poscar, xyz]:
                back = read(path, format="vasp" if path == poscar else "extxyz")
                assert back.get_chemical_symbols() == atoms.get_chemical_symbols()
                assert np.all(back.pbc) and np.allclose(back.cell, atoms.cell, atol=1e-8)
                assert np.allclose(back.positions, atoms.positions, atol=1e-8)
            counts = dict(Counter(atoms.get_chemical_symbols()))
            assert counts == {"Zr": len(atoms)//2, "C": len(atoms)//2}
            distances = atoms.get_all_distances(mic=True)
            np.fill_diagonal(distances, np.inf)
            expected_nearest = a * ratio**(1/3) / 2
            assert np.isclose(distances.min(), expected_nearest, atol=1e-8)
            assert np.isclose(atoms.get_volume(), (a*repeat)**3 * ratio)
            entries.append({
                "id": stem, "atoms": len(atoms), "counts": counts,
                "repeat_conventional": [repeat]*3, "volume_ratio_to_start": ratio,
                "cell_lengths_A": atoms.cell.lengths().tolist(),
                "volume_A3": atoms.get_volume(), "volume_A3_atom": atoms.get_volume()/len(atoms),
                "minimum_distance_A": float(distances.min()),
                "pbc": atoms.pbc.tolist(), "species_order": ["Zr", "C"],
                "files": [{"path": str(p.relative_to(root)).replace("\\", "/"),
                           "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in [poscar, xyz]],
            })
    manifest = {"status": "prepared_and_geometry_roundtrip_validated",
                "provenance": "ideal_crystals_at_initial_guess_not_DFT_relaxed_not_thermalized",
                "a_start_A": a, "reference_volume_name": "V_start",
                "source_config": str(config_path.relative_to(root)).replace("\\", "/"),
                "structures": entries}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"structure_count": len(entries), "atoms": [e["atoms"] for e in entries],
                      "validated": "composition, Zr/C order, periodic boundaries, volume, nearest distance, POSCAR/extxyz roundtrip"}))


if __name__ == "__main__":
    main()
