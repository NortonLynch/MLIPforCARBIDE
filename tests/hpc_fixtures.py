"""Build temporary synthetic inputs; never read or alter production trajectories."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from ase.build import bulk
from ase.constraints import FixCom
from ase.io import write
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from zrc_md_engine import atomic_json, save_checkpoint

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "hpc/archive/submission-provenance"


def prepare_bundle(destination, name, atoms, temperature, count):
    """Reuse the historical schema but generate every checkpoint in a temp dir."""
    source = ARCHIVE / name
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    records = copy.deepcopy([
        r for r in manifest["remaining"]
        if r["job"]["atoms"] == atoms and r["job"]["temperature_K"] == temperature
    ][:count])
    assert len(records) == count
    config = destination / "configs/experiments/zrc_mace_round1.json"
    config.parent.mkdir(parents=True)
    shutil.copyfile(source / "configs/experiments/zrc_mace_round1.json", config)
    for index, record in enumerate(records):
        ident = f"synthetic_only_{atoms}_{index}"
        record["id"] = record["job"]["id"] = ident
        record["job"]["source_group"] = "synthetic_test_not_research"
        record["checkpoint_path"] = f"inputs/{ident}/pilot.npz"
        record["initial_path"] = f"inputs/{ident}/initial.POSCAR"
        folder = destination / "inputs" / ident
        folder.mkdir(parents=True)
        repeat = round((atoms / 8) ** (1 / 3))
        structure = bulk("ZrC", "rocksalt", a=4.7, cubic=True).repeat((repeat,) * 3)
        assert len(structure) == atoms
        structure.set_cell(structure.cell * record["job"]["volume_scale"] ** (1 / 3), scale_atoms=True)
        structure.set_constraint(FixCom())
        rng = np.random.default_rng(100 + index)
        MaxwellBoltzmannDistribution(structure, temperature_K=300, rng=rng)
        write(folder / "initial.POSCAR", structure, format="vasp")
        save_checkpoint(folder / "pilot.npz", structure, rng, {"synthetic_test": True})
        for kind in ("initial", "checkpoint"):
            record[kind + "_sha256"] = hashlib.sha256((destination / record[kind + "_path"]).read_bytes()).hexdigest()
        record["job"]["input_sha256"] = record["initial_sha256"]
        record.pop("source_review_sha256", None)
    manifest["campaign_id"] = "synthetic_test_not_research"
    manifest["remaining"] = records
    manifest["synthetic_test"] = True
    atomic_json(destination / "manifest.json", manifest)
    return manifest
