"""GPU inference and MD smoke checks; synthetic labels are NOT DFT data."""
import importlib.metadata as metadata
import json
from pathlib import Path
import time

import numpy as np
import torch
from ase import units
from ase.build import bulk
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import write
from ase.md.verlet import VelocityVerlet
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary
from mace.calculators import MACECalculator


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "tmp" / "environment-checks" / "mace"
    out.mkdir(parents=True, exist_ok=True)
    assert torch.cuda.is_available(), "A working GPU is required for this check"
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    calc = MACECalculator(model_paths=str(root / "models" / "mace-mh-1.model"),
                          device="cuda", default_dtype="float32", head="omat_pbe")
    base = bulk("ZrC", "rocksalt", a=4.7, cubic=True)
    rng = np.random.default_rng(17)
    results = []
    for repeat in [1, 2]:
        atoms = base.repeat((repeat, repeat, repeat))
        atoms.positions += rng.normal(scale=0.01, size=atoms.positions.shape)
        atoms.calc = calc
        start = time.perf_counter()
        energy = atoms.get_potential_energy()
        forces = atoms.get_forces()
        stress = atoms.get_stress()
        torch.cuda.synchronize()
        assert np.isfinite(energy) and np.isfinite(forces).all() and np.isfinite(stress).all()
        assert forces.shape == (len(atoms), 3) and stress.shape == (6,)
        results.append({"atoms": len(atoms), "seconds_including_first_call_overhead": time.perf_counter()-start,
                        "energy_eV": float(energy), "force_shape": list(forces.shape),
                        "stress_shape": list(stress.shape)})
    labeled = []
    for i in range(4):
        atoms = base.copy()
        atoms.set_cell(base.cell * (1 + (i - 1.5) * 0.005), scale_atoms=True)
        atoms.positions += rng.normal(scale=0.02, size=atoms.positions.shape)
        atoms.calc = calc
        energy, forces, stress = atoms.get_potential_energy(), atoms.get_forces(), atoms.get_stress()
        atoms.calc = SinglePointCalculator(atoms, energy=energy, forces=forces, stress=stress)
        atoms.info["label_source"] = "MACE-MH-1_synthetic_installation_check_NOT_DFT"
        labeled.append(atoms)
    write(out / "synthetic-train.extxyz", labeled[:3])
    write(out / "synthetic-valid.extxyz", labeled[3:])
    atoms = base.copy()
    atoms.calc = calc
    MaxwellBoltzmannDistribution(atoms, temperature_K=300, rng=np.random.default_rng(42))
    Stationary(atoms)
    md = VelocityVerlet(atoms, timestep=0.5 * units.fs)
    start = time.perf_counter()
    md.run(10)
    torch.cuda.synchronize()
    assert np.isfinite(atoms.positions).all() and np.isfinite(atoms.get_potential_energy())
    report = {"status": "passed", "purpose": "installation_check_not_physical_validation",
              "model": "MACE-MH-1", "head": "omat_pbe", "dtype": "float32",
              "versions": {name: metadata.version(name) for name in ["mace-torch", "torch", "e3nn", "ase", "matscipy"]},
              "gpu": torch.cuda.get_device_name(0), "torch_cuda": torch.version.cuda,
              "single_points": results, "md_steps": 10, "md_seconds": time.perf_counter()-start,
              "peak_allocated_MiB": torch.cuda.max_memory_allocated()/1024**2}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
