"""Checkpointed ASE segments. Model predictions are never DFT labels."""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ase import Atoms, units
from ase.constraints import FixCom
from ase.io import write
from ase.md.langevin import Langevin
from ase.md.verlet import VelocityVerlet


class YieldRun(Exception):
    """A bounded worker turn or a user stop file requested a checkpoint exit."""


class NumericalFailure(RuntimeError):
    pass


def _replace_with_retry(source, destination):
    """Keep the old file intact while a Windows reader briefly blocks replacement."""
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 7:
                raise
            time.sleep(min(0.05 * 2**attempt, 0.5))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _replace_with_retry(tmp, path)


def save_checkpoint(path, atoms, rng, metadata):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    metadata = {**metadata, "rng_state": rng.bit_generator.state}
    with tmp.open("wb") as stream:
        np.savez_compressed(stream, numbers=atoms.numbers, positions=atoms.positions,
                            momenta=atoms.get_momenta(), masses=atoms.get_masses(),
                            cell=np.asarray(atoms.cell), pbc=atoms.pbc,
                            metadata=np.array(json.dumps(metadata, allow_nan=False)))
        stream.flush()
        os.fsync(stream.fileno())
    _replace_with_retry(tmp, path)


def load_checkpoint(path):
    with np.load(path, allow_pickle=False) as data:
        atoms = Atoms(numbers=data["numbers"], positions=data["positions"],
                      masses=data["masses"], cell=data["cell"], pbc=data["pbc"])
        atoms.set_constraint(FixCom())
        atoms.set_momenta(data["momenta"], apply_constraint=False)
        metadata = json.loads(str(data["metadata"]))
    rng = np.random.default_rng()
    rng.bit_generator.state = metadata["rng_state"]
    return atoms, rng, metadata


def diagnostics(atoms, step, spec, target_temperature):
    energy = float(atoms.get_potential_energy())
    kinetic = float(atoms.get_kinetic_energy())
    forces = atoms.get_forces(apply_constraint=False)
    potential_stress = atoms.get_stress(include_ideal_gas=False)
    total_stress = atoms.get_stress(include_ideal_gas=True)
    finite = all(np.isfinite(x).all() for x in [energy, kinetic, forces, total_stress,
                                               atoms.positions, atoms.get_momenta()])
    if not finite:
        raise NumericalFailure("Nonfinite positions/momenta/energy/force/stress")
    distances = atoms.get_all_distances(mic=True)
    np.fill_diagonal(distances, np.inf)
    symbols = np.array(atoms.get_chemical_symbols())
    pair_min = {}
    for a, b in [("Zr", "Zr"), ("Zr", "C"), ("C", "C")]:
        selected = distances[np.ix_(symbols == a, symbols == b)]
        pair_min[a+"-"+b] = float(selected.min())
    temperature = float(atoms.get_temperature())
    # A broad numerical catastrophe guard, not a physical short-bond criterion.
    if temperature > max(100000.0, 30 * spec["target_temperature_K"]):
        raise NumericalFailure(f"Explosive kinetic temperature: {temperature} K")
    row = {
        "step": step, "time_fs": step * spec["time_step_fs"], "stage_time_fs": step * spec["time_step_fs"],
        "run_time_utc": datetime.now(timezone.utc).isoformat(), "stage": spec["stage"],
        "ensemble": spec["ensemble"], "target_temperature_K": target_temperature,
        "temperature_K": temperature, "potential_eV": energy, "kinetic_eV": kinetic,
        "total_eV": energy+kinetic, "pressure_GPa": float(-np.mean(total_stress[:3])*160.21766208),
        "potential_pressure_GPa": float(-np.mean(potential_stress[:3])*160.21766208),
        "max_force_eV_A": float(np.linalg.norm(forces, axis=1).max()),
        "min_pair_distances_A": pair_min, "finite": True, "atoms": len(atoms),
        "degrees_of_freedom": atoms.get_number_of_degrees_of_freedom(),
        "volume_A3": atoms.get_volume(),
    }
    return row, forces, potential_stress


def run_segment(initial_atoms, initial_rng, calc, directory, spec, progress=None,
                deadline=None, stop_file=None):
    """Run/resume one fixed-cell segment. Checkpoints refer to committed byte offsets."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    checkpoint = directory / "checkpoint.npz"
    if checkpoint.exists():
        atoms, rng, saved = load_checkpoint(checkpoint)
        if saved["spec_sha256"] != signature:
            raise RuntimeError("Segment parameters changed after checkpoint; create a new attempt")
        step = saved["step"]
        offsets = saved["offsets"]
    else:
        atoms = initial_atoms.copy()
        atoms.set_masses(atoms.get_masses())
        atoms.set_constraint(FixCom())
        rng = np.random.default_rng()
        rng.bit_generator.state = initial_rng.bit_generator.state
        step, offsets = 0, {"log": 0, "frames": 0}
        saved = None
    atoms.calc = calc
    dt = spec["time_step_fs"]
    nsteps = round(spec["expected_duration_fs"] / dt)
    if not np.isclose(nsteps*dt, spec["expected_duration_fs"]):
        raise ValueError("Duration must be an integer number of time steps")
    log_steps = round(spec["log_interval_fs"] / dt)
    checkpoint_steps = round(spec["checkpoint_interval_fs"] / dt)
    frame_steps = round(spec["frame_interval_fs"] / dt)
    if not all(np.isclose(count*dt, spec[key], atol=1e-9) for count, key in [
        (log_steps, "log_interval_fs"), (checkpoint_steps, "checkpoint_interval_fs"),
        (frame_steps, "frame_interval_fs")]):
        raise ValueError("All time intervals must be integer multiples of the step")
    if min(log_steps, checkpoint_steps, frame_steps) < 1 or checkpoint_steps % log_steps or frame_steps % log_steps:
        raise ValueError("Intervals must align with the diagnostic interval")
    if spec["ensemble"] == "NVE":
        dyn = VelocityVerlet(atoms, timestep=dt*units.fs)
    else:
        dyn = Langevin(atoms, timestep=dt*units.fs, temperature_K=spec["target_temperature_K"],
                       friction=spec["friction_per_fs"] / units.fs, fixcm=False, rng=rng)
    dyn.nsteps = step
    previous_positions = atoms.positions.copy()

    def guard():
        nonlocal previous_positions
        if not np.isfinite(atoms.positions).all() or not np.isfinite(atoms.get_momenta()).all():
            raise NumericalFailure("Nonfinite state during integration")
        if atoms.get_temperature() > max(100000.0, 30*spec["target_temperature_K"]):
            raise NumericalFailure("Explosive kinetic temperature during integration")
        if np.linalg.norm(atoms.positions-previous_positions, axis=1).max() > 1.0:
            raise NumericalFailure("More than 1 A displacement in one step; reduce step and inspect")
        previous_positions = atoms.positions.copy()

    dyn.attach(guard, interval=1)
    atomic_json(directory / "segment.json", spec)
    started = time.monotonic()

    def target_at(s):
        start = spec.get("ramp_start_K", spec["target_temperature_K"])
        return start + (spec["target_temperature_K"]-start) * min(s/nsteps, 1) if nsteps else start

    with (directory / "log.jsonl").open("a+b") as log, (directory / "frames.extxyz").open("a+b") as frames:
        # Uncommitted tails may exist after an interruption. The checkpoint is authoritative.
        for stream, key in [(log, "log"), (frames, "frames")]:
            stream.seek(0, os.SEEK_END)
            if stream.tell() < offsets[key]:
                raise RuntimeError(f"{key} is shorter than its committed checkpoint")
            stream.truncate(offsets[key])
            stream.seek(0, os.SEEK_END)

        def commit():
            for stream in [log, frames]:
                stream.flush()
                os.fsync(stream.fileno())
            meta = {"step": step, "spec_sha256": signature, "checkpoint_time_utc": datetime.now(timezone.utc).isoformat(),
                    "offsets": {"log": log.tell(), "frames": frames.tell()},
                    "spec": spec, "wall_seconds_this_invocation": time.monotonic()-started}
            save_checkpoint(checkpoint, atoms, rng, meta)
            if progress:
                progress({"segment": str(directory), "step": step, "steps": nsteps,
                          "time_fs": step*dt, "duration_fs": nsteps*dt})

        def record():
            row, forces, stress = diagnostics(atoms, step, spec, target_at(step))
            log.write((json.dumps(row, allow_nan=False)+"\n").encode())
            log.flush()
            if step % frame_steps == 0 or step == nsteps:
                frame = atoms.copy()
                frame.calc = None
                frame.info = {"job_id": spec["job_id"], "source_group": spec["source_group"],
                              "stage": spec["stage"], "step": step, "time_fs": step*dt,
                              "target_temperature_K": target_at(step), "temperature_K": row["temperature_K"],
                              "model_energy": row["potential_eV"], "model_stress": stress,
                              "positions_are_unwrapped": True, "label_source": "MACE_prediction_NOT_DFT",
                              "phase_assignment": "unassigned", "a_start_A": 4.7}
                frame.set_array("model_forces", forces)
                stream = io.StringIO()
                write(stream, frame, format="extxyz", write_results=False)
                frames.write(stream.getvalue().encode())

        if saved is None:
            record()
            commit()
        while step < nsteps:
            if (deadline is not None and time.monotonic() >= deadline) or (stop_file and Path(stop_file).exists()):
                commit()
                raise YieldRun("Stopped at a committed checkpoint")
            count = min(log_steps, nsteps-step)
            if spec["ensemble"] != "NVE":
                # Piecewise 5 fs heating increments, documented in segment metadata.
                dyn.set_temperature(temperature_K=target_at(step+count))
            dyn.run(count)
            step += count
            record()
            if step % checkpoint_steps == 0 or step == nsteps:
                commit()
    return atoms, rng
