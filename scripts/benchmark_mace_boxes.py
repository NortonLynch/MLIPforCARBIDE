"""Small inference benchmark for box planning; produces no DFT labels or MD."""

import gc
import hashlib
import importlib.metadata as metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from ase.build import bulk
from mace.calculators import MACECalculator


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / "docs/environments/mace-box-benchmark.json"
    model = root / "models/mace-mh-1.model"
    if not torch.cuda.is_available():
        raise RuntimeError("This benchmark requires the configured CUDA GPU")
    torch.set_num_threads(4)
    calc = MACECalculator(model_paths=str(model), device="cuda",
                          default_dtype="float32", head="omat_pbe")
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "cold_structure_inference_feasibility_not_MD_or_physical_validation",
        "model": "MACE-MH-1", "head": "omat_pbe", "dtype": "float32",
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "cutoff_A": calc.r_max,
        "gpu": torch.cuda.get_device_name(0),
        "device_total_MiB": torch.cuda.get_device_properties(0).total_memory / 1024**2,
        "versions": {name: metadata.version(name) for name in ["mace-torch", "torch", "ase", "matscipy"]},
        "timing": "2 warm-up calls then 5 changed-position E/F/stress calls; CUDA synchronized; no MD integration or file output in timer",
        "memory": "PyTorch allocated/reserved only; excludes other applications and some CUDA/driver memory",
        "boxes": [],
    }
    reference = None
    try:
        for repeat in [1, 2, 3, 4]:
            gc.collect()
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            atoms = bulk("ZrC", "rocksalt", a=4.7, cubic=True).repeat((repeat,) * 3)
            atoms.calc = calc
            entry = {"atoms": len(atoms), "repeat_conventional": [repeat] * 3,
                     "box_length_A": repeat * 4.7}
            try:
                energy = atoms.get_potential_energy() / len(atoms)
                forces = atoms.get_forces()
                stress = atoms.get_stress()
                assert np.isfinite(energy) and np.isfinite(forces).all() and np.isfinite(stress).all()
                if reference is None:
                    reference = (energy, stress.copy())
                entry["ideal_periodic_replication"] = {
                    "energy_eV_atom": float(energy),
                    "energy_difference_from_8_atom_meV_atom": float((energy-reference[0])*1000),
                    "max_abs_force_eV_A": float(np.abs(forces).max()),
                    "max_stress_difference_from_8_atom_GPa": float(np.abs(stress-reference[1]).max()*160.21766208),
                }
                initial = atoms.positions.copy()
                rng = np.random.default_rng(1700 + len(atoms))
                timings = []
                for i in range(7):
                    atoms.positions = initial + rng.normal(0, 0.02, initial.shape)
                    torch.cuda.synchronize()
                    start = perf_counter()
                    energy = atoms.get_potential_energy()
                    forces = atoms.get_forces()
                    stress = atoms.get_stress()
                    torch.cuda.synchronize()
                    elapsed = perf_counter() - start
                    assert np.isfinite(energy) and np.isfinite(forces).all() and np.isfinite(stress).all()
                    if i >= 2:
                        timings.append(elapsed)
                entry.update(status="passed", measured_call_seconds=timings,
                             median_call_seconds=float(np.median(timings)),
                             peak_allocated_MiB=torch.cuda.max_memory_allocated()/1024**2,
                             peak_reserved_MiB=torch.cuda.max_memory_reserved()/1024**2)
            except torch.OutOfMemoryError as exc:
                entry.update(status="out_of_memory", error=str(exc))
            report["boxes"].append(entry)
            print(json.dumps(entry), flush=True)
            if entry["status"] != "passed":
                break
    finally:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
