"""Review MD segment logs without importing ASE, Torch, or a potential.

Passing this review establishes numerical completion only. It does not establish
thermodynamic equilibration, DFT accuracy, phase identity, or physical validity.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any


_SCALARS = (
    "time_fs", "target_temperature_K", "temperature_K", "potential_eV",
    "kinetic_eV", "total_eV", "pressure_GPa", "max_force_eV_A", "volume_A3",
)
_PAIRS = ("Zr-Zr", "Zr-C", "C-C")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _linear_slope(x: list[float], y: list[float]) -> float:
    x_mean, y_mean = statistics.fmean(x), statistics.fmean(y)
    denominator = sum((item - x_mean) ** 2 for item in x)
    if denominator <= 0:
        raise ValueError("A drift fit requires a nonzero time span")
    return sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y)) / denominator


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "standard_deviation": statistics.pstdev(values),
    }


def review_segment(segment_dir: str | Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Check ``segment_dir/log.jsonl`` against the runner's segment contract.

    Required expected keys: ensemble (NVT/NVE), atoms, time_step_fs,
    expected_duration_fs, target_temperature_K, stage. Optional keys:
    log_interval_fs, nve_drift_limit_meV_atom_ps (default 1),
    short_distance_warning_A (default 1.2). A ramp stage additionally requires
    ramp_start_K, with target temperature interpolated linearly in segment time.
    Logged time and step start at zero.
    The final row must be exactly the requested final integration step; its log
    interval may be shorter than the normal interval.
    """
    result: dict[str, Any] = {
        "schema_version": 1,
        "hard_pass": False,
        "completed_numerically": False,
        "equilibrated": False,
        "physical_validated": False,
        "equilibration_assessment": "not_established_from_automated_log_review",
        "scope": "Numerical completion and diagnostics; not DFT or physical validation.",
        "errors": [],
        "warnings": [],
        "metrics": {},
    }
    errors, warnings, metrics = result["errors"], result["warnings"], result["metrics"]

    try:
        ensemble = expected["ensemble"].upper()
        if ensemble not in ("NVT", "NVE"):
            raise ValueError("ensemble must be NVT or NVE")
        atoms = expected["atoms"]
        if not isinstance(atoms, int) or isinstance(atoms, bool) or atoms < 2:
            raise ValueError("atoms must be an integer of at least two")
        dt = expected["time_step_fs"]
        duration = expected["expected_duration_fs"]
        target_temperature = expected["target_temperature_K"]
        if not all(_number(v) and v > 0 for v in (dt, duration, target_temperature)):
            raise ValueError("time step, duration, and target temperature must be positive finite numbers")
        expected_steps = round(duration / dt)
        if expected_steps < 1 or not math.isclose(expected_steps * dt, duration, rel_tol=0, abs_tol=1e-7):
            raise ValueError("duration must be an integer multiple of the time step")
        stage = expected["stage"]
        if not isinstance(stage, str) or not stage:
            raise ValueError("stage must be a nonempty string")
        ramp_start = expected.get("ramp_start_K", target_temperature)
        if stage == "ramp":
            if ensemble != "NVT" or "ramp_start_K" not in expected:
                raise ValueError("a ramp stage requires NVT and ramp_start_K")
            if not _number(ramp_start) or ramp_start <= 0:
                raise ValueError("ramp_start_K must be positive and finite")
        elif ramp_start != target_temperature:
            raise ValueError("a changing target temperature requires stage='ramp'")
        interval = expected.get("log_interval_fs")
        if interval is not None:
            if not _number(interval) or interval <= 0:
                raise ValueError("log_interval_fs must be positive and finite")
            log_steps = round(interval / dt)
            if log_steps < 1 or not math.isclose(log_steps * dt, interval, rel_tol=0, abs_tol=1e-7):
                raise ValueError("log_interval_fs must be an integer multiple of time_step_fs")
        else:
            log_steps = None
        drift_limit = expected.get("nve_drift_limit_meV_atom_ps", 1.0)
        if not _number(drift_limit) or drift_limit <= 0:
            raise ValueError("NVE drift limit must be positive and finite")
        short_distance = expected.get("short_distance_warning_A", 1.2)
        if not _number(short_distance) or short_distance <= 0:
            raise ValueError("short_distance_warning_A must be positive and finite")
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError) as exc:
        errors.append(f"Invalid review contract: {exc}")
        return result

    try:
        raw_lines = (Path(segment_dir) / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        errors.append(f"Cannot read log.jsonl: {exc}")
        return result
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_lines, 1):
        if not line.strip():
            errors.append(f"Blank log record at line {line_number}")
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("record is not a JSON object")
            missing = [key for key in (*_SCALARS, "step", "stage", "finite", "atoms", "min_pair_distances_A") if key not in row]
            if missing:
                raise ValueError(f"missing fields: {', '.join(missing)}")
            if any(not _number(row[key]) for key in _SCALARS):
                raise ValueError("a required scalar is nonnumeric or nonfinite")
            if row["finite"] is not True:
                raise ValueError("finite flag is not true")
            if not isinstance(row["step"], int) or isinstance(row["step"], bool) or row["step"] < 0:
                raise ValueError("step must be a nonnegative integer")
            if not isinstance(row["atoms"], int) or isinstance(row["atoms"], bool) or row["atoms"] != atoms:
                raise ValueError("atom count does not match review contract")
            if row["stage"] != stage:
                raise ValueError("stage does not match review contract")
            if row["volume_A3"] <= 0:
                raise ValueError("volume must be positive")
            if row["temperature_K"] < 0 or row["kinetic_eV"] < 0 or row["max_force_eV_A"] < 0:
                raise ValueError("temperature, kinetic energy, and force magnitude must be nonnegative")
            row_target = ramp_start + (target_temperature - ramp_start) * min(row["time_fs"] / duration, 1)
            if not math.isclose(row["target_temperature_K"], row_target, rel_tol=1e-9, abs_tol=1e-6):
                raise ValueError("target temperature does not match review contract")
            if not math.isclose(row["time_fs"], row["step"] * dt, rel_tol=0, abs_tol=1e-6):
                raise ValueError("step and time do not agree with the time step")
            if not math.isclose(row["potential_eV"] + row["kinetic_eV"], row["total_eV"], rel_tol=0, abs_tol=1e-6):
                raise ValueError("potential plus kinetic energy does not equal total energy")
            pairs = row["min_pair_distances_A"]
            if not isinstance(pairs, dict) or any(pair not in pairs or not _number(pairs[pair]) or pairs[pair] < 0 for pair in _PAIRS):
                raise ValueError("all three minimum pair distances must be finite nonnegative numbers")
            rows.append(row)
        except (json.JSONDecodeError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"Invalid log record at line {line_number}: {exc}")

    metrics.update({"valid_log_records": len(rows), "expected_steps": expected_steps, "requested_duration_fs": duration})
    if len(rows) < 2:
        errors.append("At least initial and final log records are required")
        return result
    if rows[0]["step"] != 0:
        errors.append("Initial record must have step 0 and time 0")
    if rows[-1]["step"] != expected_steps:
        errors.append(f"Final step is {rows[-1]['step']}; expected {expected_steps}")
    if any(right["step"] <= left["step"] for left, right in zip(rows, rows[1:])):
        errors.append("Log steps/times must increase strictly; duplicate or out-of-order records found")
    if log_steps is not None:
        required_steps = list(range(0, expected_steps + 1, log_steps))
        if required_steps[-1] != expected_steps:
            required_steps.append(expected_steps)
        if [row["step"] for row in rows] != required_steps:
            errors.append("Log records do not cover the exact requested logging schedule")
    if any(not math.isclose(row["volume_A3"], rows[0]["volume_A3"], rel_tol=1e-8, abs_tol=1e-6) for row in rows):
        errors.append("Cell volume changed during a fixed-volume NVT/NVE segment")
    if errors:
        return result

    # Exclude the shared initial checkpoint from summaries and block statistics.
    samples = rows[1:]
    metrics.update({
        "completed_steps": rows[-1]["step"],
        "observed_duration_fs": rows[-1]["time_fs"] - rows[0]["time_fs"],
        "atoms": atoms,
        "volume_A3": rows[0]["volume_A3"],
        "temperature_K": _summary([r["temperature_K"] for r in samples]),
        "target_temperature_K": _summary([r["target_temperature_K"] for r in samples]),
        "potential_eV_atom": _summary([r["potential_eV"] / atoms for r in samples]),
        "pressure_GPa": _summary([r["pressure_GPa"] for r in samples]),
        "maximum_force_eV_A": max(r["max_force_eV_A"] for r in rows),
        "minimum_pair_distances_A": {pair: min(r["min_pair_distances_A"][pair] for r in rows) for pair in _PAIRS},
    })
    if any(v < short_distance for v in metrics["minimum_pair_distances_A"].values()):
        warnings.append(f"At least one pair distance is below the diagnostic threshold {short_distance:g} A; inspect the trajectory. This alone is not a physical-failure test.")
    # This broad operational limit matches the runner. It prevents a finite but
    # catastrophic trajectory from advancing automatically; it is not a claim
    # that a smaller temperature excursion is physically valid.
    catastrophe_temperature = max(100000.0, 30 * max(target_temperature, ramp_start))
    metrics["catastrophe_temperature_limit_K"] = catastrophe_temperature
    if max(r["temperature_K"] for r in rows) > catastrophe_temperature:
        errors.append(f"Explosive kinetic temperature exceeds the broad numerical guard {catastrophe_temperature:g} K")
    if ensemble == "NVE":
        x = [r["time_fs"] / 1000.0 for r in rows]
        y = [r["total_eV"] / atoms * 1000.0 for r in rows]
        slope = _linear_slope(x, y)
        first, last = y[0], y[-1]
        metrics["nve"] = {
            "linear_drift_meV_atom_ps": slope,
            "absolute_linear_drift_meV_atom_ps": abs(slope),
            "endpoint_drift_meV_atom_ps": (last - first) / (x[-1] - x[0]),
            "peak_to_peak_energy_meV_atom": max(y) - min(y),
            "fit_duration_ps": x[-1] - x[0],
            "drift_limit_meV_atom_ps": drift_limit,
        }
        if abs(slope) > drift_limit:
            errors.append(f"NVE total-energy drift {abs(slope):.6g} meV/atom/ps exceeds numerical gate {drift_limit:g}")
        if duration < 1000:
            warnings.append("NVE drift was fitted over less than 1 ps; passing establishes only this short segment's numerical gate.")
    else:
        mean_temperature = metrics["temperature_K"]["mean"]
        mean_target = metrics["target_temperature_K"]["mean"]
        # Small cells have large thermal fluctuations. This permissive warning is
        # diagnostic only; no thermostat accuracy claim follows from passing it.
        fractional_warning = max(0.5, 4.0 * math.sqrt(2.0 / max(1, 3 * atoms - 3)))
        if abs(mean_temperature - mean_target) / mean_target > fractional_warning:
            warnings.append("Mean temperature differs substantially from its target; inspect thermostat behavior and initialization before interpreting the trajectory.")
        if max(r["temperature_K"] for r in rows) > max(10 * target_temperature, 100000):
            warnings.append("Very large temperature excursion detected; inspect forces and trajectory for an instability. Finite logs alone do not prove stability.")
    if len(samples) >= 8:
        blocks = [samples[i * len(samples) // 4:(i + 1) * len(samples) // 4] for i in range(4)]
        block_means = [{
            "start_time_fs": b[0]["time_fs"], "end_time_fs": b[-1]["time_fs"],
            "temperature_K": statistics.fmean(r["temperature_K"] for r in b),
            "potential_eV_atom": statistics.fmean(r["potential_eV"] / atoms for r in b),
            "pressure_GPa": statistics.fmean(r["pressure_GPa"] for r in b),
        } for b in blocks]
        metrics["four_block_means"] = block_means
        warnings.append("Block means are descriptive diagnostics with correlated samples; they do not establish equilibration or independent statistical precision.")
    else:
        warnings.append("Too few log samples for four-block diagnostics.")
    if stage == "pilot" or duration < 5000:
        warnings.append("This short segment is a pilot/numerical check; thermodynamic equilibration is not certified.")
    if stage == "ramp":
        warnings.append("This segment changes the thermostat target; its averages are heating/cooling diagnostics, not equilibrium observables.")
    warnings.append("Physical validity, phase identity, and DFT agreement require separate trajectory and reference-data validation.")
    result["hard_pass"] = not errors
    result["completed_numerically"] = not errors
    return result
