"""Generate the initial VASP 6.3.2 input study (no POTCAR, no submission)."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.build import bulk
from ase.io import read, write
from ase.neighborlist import neighbor_list
from ase.io.vasp import write_vasp
from io import StringIO

ROOT = Path(__file__).resolve().parents[1] / "dft" / "jobs"
COMMON = dict(GGA="PE", PREC="Accurate", ENCUT=600, EDIFF="1E-7",
              ALGO="Normal", NELM=200, NELMIN=4, ISTART=0, ICHARG=2,
              ISPIN=1, ISMEAR=0, SIGMA=0.10, LREAL=".FALSE.",
              LASPH=".TRUE.", ADDGRID=".FALSE.", LMAXMIX=4, ISYM=0,
              NSW=0, IBRION=-1, ISIF=2, LWAVE=".FALSE.", LCHARG=".FALSE.",
              NWRITE=2)


def save(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    if path.exists() and path.read_bytes() != payload:
        raise FileExistsError(f"Refusing to overwrite modified file: {path}")
    if not path.exists():
        path.write_bytes(payload)


def main():
    jobs = []
    pristine = bulk("ZrC", "rocksalt", a=4.7, cubic=True)
    rng = np.random.default_rng(20260921)
    distorted = pristine.copy()
    deformation = np.array([[0.97, 0.018, 0], [0, 1.01, 0.012], [0, 0, 0.99]])
    distorted.set_cell(pristine.cell.array @ deformation, scale_atoms=True)
    displacement = rng.normal(0, 0.04, (8, 3))
    distorted.positions += displacement - displacement.mean(axis=0)
    distorted.wrap()
    pilot = pristine.repeat((2, 2, 2))
    pilot.set_cell(pilot.cell.array @ deformation, scale_atoms=True)
    displacement = rng.normal(0, 0.08, (64, 3))
    pilot.positions += displacement - displacement.mean(axis=0)
    pilot.wrap()

    def add(path, atoms, grid, purpose, stage, group, **overrides):
        symbols = atoms.get_chemical_symbols()
        order = [symbol for symbol in ("Zr", "C") if symbol in symbols]
        atoms = atoms[sorted(range(len(atoms)), key=lambda i: order.index(symbols[i]))]
        config = COMMON | overrides
        config = {"SYSTEM": path.replace("/", "_"), **config}
        spec = ["Zr_sv" if symbol == "Zr" else "C" for symbol in order]
        stream = StringIO()
        write_vasp(stream, atoms, direct=True, sort=False, vasp5=True)
        poscar = stream.getvalue()
        incar = "# VASP 6.3.2; proposed settings, convergence not yet established.\n"
        incar += "# Numerical Gaussian smearing, not an electronic temperature.\n"
        incar += "\n".join(f"{key} = {value}" for key, value in config.items()) + "\n"
        kpoints = f"Gamma-centered {grid}x{grid}x{grid}\n0\nGamma\n{grid} {grid} {grid}\n0 0 0\n"
        folder = ROOT / path
        for name, content in [("INCAR", incar), ("KPOINTS", kpoints), ("POSCAR", poscar)]:
            save(folder / name, content)
        distances = neighbor_list("d", atoms, cutoff=3.0)
        record = dict(path=path, stage=stage, purpose=purpose, source_group=group,
                      structure_kind="isolated_atom" if len(atoms) == 1 else "constructed_not_thermalized",
                      natoms=len(atoms), species=order,
                      counts=[symbols.count(symbol) for symbol in order],
                      recommended_potentials=spec, kmesh=[grid]*3, incar=config,
                      poscar_sha256=hashlib.sha256(poscar.encode()).hexdigest(),
                      min_periodic_distance_A=float(distances.min()) if len(distances) else None,
                      label_status="not_calculated", dataset_split="unassigned",
                      input_status="awaiting_local_POTCAR_assembly_and_preflight")
        save(folder / "job.json", json.dumps(record, indent=2) + "\n")
        jobs.append(record)

    add("00_smoke/zrc8", pristine, 4, "Check executable, POTCAR and parsing; not a converged label", 0, "pristine8")
    # Distorted geometry makes nonzero forces and shear stress available for convergence tests.
    for cutoff in (520, 600, 700, 800):
        add(f"01_convergence/encut_{cutoff}_k8", distorted, 8,
            "ENCUT convergence at fixed geometry and k mesh", 1, "distorted8", ENCUT=cutoff)
    # The k=8 member is the existing encut_800_k8 job.
    for grid in (4, 6, 10):
        add(f"01_convergence/encut_800_k{grid}", distorted, grid,
            "k-point convergence at fixed geometry and ENCUT=800", 1, "distorted8", ENCUT=800)
    # The sigma=0.10 member is encut_800_k10.
    for sigma in (0.05, 0.20):
        add(f"01_convergence/sigma_{sigma:.2f}", distorted, 10,
            "Gaussian width sensitivity at ENCUT=800 and k=10", 1, "distorted8", ENCUT=800, SIGMA=sigma)
    add("01_convergence/ediff_1e-8", distorted, 10,
        "SCF tolerance sensitivity relative to encut_800_k10", 1, "distorted8", ENCUT=800, EDIFF="1E-8")
    add("01_convergence/spin_check", distorted, 8,
        "Check nonmagnetic bulk assumption against encut_600_k8", 1, "distorted8",
        ISPIN=2, MAGMOM="4*1.0 4*0.0", LORBIT=11)
    add("02_relax/zrc8", pristine, 8,
        "Relax cubic crystal after choosing converged protocol; provisional 600 eV", 2, "pristine8",
        ISYM=2, IBRION=2, NSW=100, ISIF=3, EDIFFG=-0.005, POTIM=0.3, PSTRESS=0)
    for grid in (2, 3, 4):
        add(f"03_supercell_check/zrc64_k{grid}", pilot, grid,
            "64-atom distorted solid single point; k convergence, NOT a liquid frame", 3, "distorted64")
    # Small optional scan; lowest converged spin candidate still needs occupation/box checks.
    for element in ("Zr", "C"):
        for spin in (0, 2, 4):
            atom = Atoms(element, scaled_positions=[[0.5, 0.5, 0.5]], cell=[16, 17, 18], pbc=True)
            add(f"04_atomic_references/{element}_spin{spin}", atom, 1,
                "Optional isolated-atom spin scan; do not assume ground state from one run", 4, f"atom_{element}",
                ISPIN=2, MAGMOM=float(spin), NUPDOWN=spin, SIGMA=0.01, ISIF=0,
                EDIFF="1E-8", NELM=300, LORBIT=11)
        atom = Atoms(element, scaled_positions=[[0.5, 0.5, 0.5]], cell=[20, 21, 22], pbc=True)
        add(f"04_atomic_references/{element}_spin2_box20", atom, 1,
            "Optional box check for spin=2; repeat for another spin if it wins", 4, f"atom_{element}",
            ISPIN=2, MAGMOM=2.0, NUPDOWN=2, SIGMA=0.01, ISIF=0,
            EDIFF="1E-8", NELM=300, LORBIT=11)

    manifest = dict(protocol_id="zrc-pbe64-zrsv-c-v2-proposed", vasp_target="6.3.2",
                    status="inputs_only_not_converged", jobs=jobs,
                    vaspkit_target="1.3.5", potcar_preparation="local_library_assembly_pending",
                    expected_job_count=len(jobs), intended_potcar_family="PAW_PBE",
                    potential_release="potpaw_PBE.64",
                    primary_label_energy="free_energy_TOTEN_force_consistent",
                    retain_additional_energies=["energy_without_entropy", "energy_sigma_to_zero"],
                    electronic_model="fixed_numerical_gaussian_smearing_not_Te_equals_Tion",
                    approximate_reference_lattice_A=4.7)
    save(ROOT / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    out = StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["stage", "path", "natoms", "ENCUT_eV", "kmesh", "ISMEAR", "SIGMA_eV", "ISPIN", "purpose"])
    for job in jobs:
        config = job["incar"]
        writer.writerow([job["stage"], job["path"], job["natoms"], config["ENCUT"],
                         "x".join(map(str, job["kmesh"])), config["ISMEAR"], config["SIGMA"], config["ISPIN"], job["purpose"]])
    save(ROOT / "job-list.csv", out.getvalue())
    save(ROOT / "jobs.list", "\n".join(job["path"] for job in jobs) + "\n")
    for job in jobs:
        restored = read(ROOT / job["path"] / "POSCAR")
        assert len(restored) == job["natoms"]
        if len(restored) > 1:
            assert job["min_periodic_distance_A"] > 1.5
    assert len({job["poscar_sha256"] for job in jobs if job["stage"] == 1}) == 1
    assert len({job["poscar_sha256"] for job in jobs if job["stage"] == 3}) == 1
    print(f"Created and structurally checked {len(jobs)} VASP input directories under {ROOT}")


if __name__ == "__main__":
    main()
