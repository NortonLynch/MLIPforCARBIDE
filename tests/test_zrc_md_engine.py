"""CPU-only synthetic mechanics tests, never research trajectories or labels."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.constraints import FixCom
from ase.io import read


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zrc_md_engine.py"
_SPEC = importlib.util.spec_from_file_location("zrc_md_engine", _MODULE_PATH)
_ENGINE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ENGINE)


class SyntheticHarmonicCalculator(Calculator):
    """A deterministic CPU harmonic potential used only to test orchestration."""

    implemented_properties = ["energy", "forces", "stress"]

    def __init__(self, reference):
        super().__init__()
        self.reference = np.asarray(reference).copy()

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        displacement = self.atoms.positions - self.reference
        spring = 0.2
        self.results = {
            "energy": float(0.5 * spring * np.sum(displacement**2)),
            "forces": -spring * displacement,
            "stress": np.zeros(6),
        }


class SegmentCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic_md_engine_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.reference = np.array([[1, 1, 1], [4, 4, 1], [1, 4, 4], [4, 1, 4]], dtype=float)
        self.atoms = Atoms("Zr2C2", positions=self.reference, cell=[8, 8, 8], pbc=True)
        self.atoms.positions[0, 0] += 0.02
        self.atoms.positions[1, 0] -= 0.02
        self.atoms.set_constraint(FixCom())
        self.atoms.set_momenta(np.random.default_rng(31).normal(0, 0.03, (4, 3)))
        self.rng = np.random.default_rng(1729)
        self.spec = {
            "job_id": "synthetic_engine_test", "source_group": "synthetic_not_research",
            "atoms": 4, "target_temperature_K": 10, "stage": "pilot", "ensemble": "NVT",
            "expected_duration_fs": 6, "time_step_fs": 0.5, "dtype": "float64",
            "model_sha256": "synthetic_harmonic_calculator_not_a_model_file", "head": "synthetic",
            "log_interval_fs": 1, "checkpoint_interval_fs": 2, "frame_interval_fs": 2,
            "friction_per_fs": 0.01, "nve_drift_limit_meV_atom_ps": 1.0,
        }

    def run_segment(self, directory, spec=None, **kwargs):
        return _ENGINE.run_segment(self.atoms, self.rng, SyntheticHarmonicCalculator(self.reference),
                                   directory, self.spec if spec is None else spec, **kwargs)

    def interrupt_after_first_progress_checkpoint(self, directory):
        stop_file = self.path / "synthetic_stop_marker"

        def stop_on_checkpoint(detail):
            if detail["step"] >= 4:
                stop_file.touch()

        with self.assertRaises(_ENGINE.YieldRun):
            self.run_segment(directory, progress=stop_on_checkpoint, stop_file=stop_file)
        stop_file.unlink()
        _, _, metadata = _ENGINE.load_checkpoint(directory / "checkpoint.npz")
        self.assertEqual(metadata["step"], 4)
        return metadata

    def test_nvt_resume_matches_uninterrupted_states_rng_and_scientific_outputs(self):
        initial_positions = self.atoms.positions.copy()
        initial_momenta = self.atoms.get_momenta().copy()
        initial_rng = copy.deepcopy(self.rng.bit_generator.state)
        uninterrupted = self.path / "uninterrupted"
        resumed = self.path / "resumed"
        full_atoms, full_rng = self.run_segment(uninterrupted)
        metadata = self.interrupt_after_first_progress_checkpoint(resumed)
        for filename, key in (("log.jsonl", "log"), ("frames.extxyz", "frames")):
            output = resumed / filename
            self.assertEqual(output.stat().st_size, metadata["offsets"][key])
            with output.open("ab") as stream:
                stream.write(b"SYNTHETIC UNCOMMITTED CORRUPT TAIL\n\xff\n")
        resumed_atoms, resumed_rng = self.run_segment(resumed)
        np.testing.assert_array_equal(full_atoms.positions, resumed_atoms.positions)
        np.testing.assert_array_equal(full_atoms.get_momenta(), resumed_atoms.get_momenta())
        self.assertEqual(full_rng.bit_generator.state, resumed_rng.bit_generator.state)
        for filename in ("log.jsonl", "frames.extxyz"):
            self.assertNotIn(b"SYNTHETIC UNCOMMITTED CORRUPT TAIL", (resumed / filename).read_bytes())
        full_rows = [json.loads(line) for line in (uninterrupted / "log.jsonl").read_text().splitlines()]
        rows = [json.loads(line) for line in (resumed / "log.jsonl").read_text().splitlines()]
        # Wall-clock execution timestamps intentionally differ between runs.
        strip_clock = lambda values: [{k: v for k, v in row.items() if k != "run_time_utc"} for row in values]
        self.assertEqual(strip_clock(full_rows), strip_clock(rows))
        full_frames = read(uninterrupted / "frames.extxyz", index=":")
        resumed_frames = read(resumed / "frames.extxyz", index=":")
        self.assertEqual(len(full_frames), len(resumed_frames))
        for full_frame, resumed_frame in zip(full_frames, resumed_frames):
            self.assertEqual(set(full_frame.arrays), set(resumed_frame.arrays))
            for key in full_frame.arrays:
                np.testing.assert_array_equal(full_frame.arrays[key], resumed_frame.arrays[key])
            np.testing.assert_array_equal(full_frame.cell.array, resumed_frame.cell.array)
            np.testing.assert_array_equal(full_frame.pbc, resumed_frame.pbc)
            self.assertEqual(set(full_frame.info), set(resumed_frame.info))
            for key in full_frame.info:
                np.testing.assert_equal(full_frame.info[key], resumed_frame.info[key])
        self.assertEqual([r["step"] for r in rows], list(range(0, 13, 2)))
        np.testing.assert_array_equal(self.atoms.positions, initial_positions)
        np.testing.assert_array_equal(self.atoms.get_momenta(), initial_momenta)
        self.assertEqual(self.rng.bit_generator.state, initial_rng)

    def test_changed_spec_cannot_resume_checkpoint(self):
        directory = self.path / "changed_spec"
        self.interrupt_after_first_progress_checkpoint(directory)
        original = (directory / "checkpoint.npz").read_bytes()
        changed = {**self.spec, "target_temperature_K": 11}
        with self.assertRaisesRegex(RuntimeError, "parameters changed"):
            self.run_segment(directory, spec=changed)
        self.assertEqual((directory / "checkpoint.npz").read_bytes(), original)

    def test_nve_preserves_caller_atoms_and_rng(self):
        positions = self.atoms.positions.copy()
        momenta = self.atoms.get_momenta().copy()
        cell = self.atoms.cell.array.copy()
        rng_state = copy.deepcopy(self.rng.bit_generator.state)
        final, final_rng = self.run_segment(self.path / "nve", spec={**self.spec, "ensemble": "NVE", "stage": "nve"})
        self.assertIsNot(final, self.atoms)
        np.testing.assert_array_equal(self.atoms.positions, positions)
        np.testing.assert_array_equal(self.atoms.get_momenta(), momenta)
        np.testing.assert_array_equal(self.atoms.cell.array, cell)
        self.assertEqual(self.rng.bit_generator.state, rng_state)
        self.assertEqual(final_rng.bit_generator.state, rng_state)
        self.assertFalse(np.array_equal(final.positions, positions))

    def test_missing_committed_output_is_not_silently_recreated(self):
        directory = self.path / "missing_committed_output"
        self.interrupt_after_first_progress_checkpoint(directory)
        (directory / "log.jsonl").write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "shorter than its committed checkpoint"):
            self.run_segment(directory)

    def test_finished_checkpoint_is_idempotent(self):
        directory = self.path / "finished"
        first, first_rng = self.run_segment(directory)
        log_bytes = (directory / "log.jsonl").read_bytes()
        frame_bytes = (directory / "frames.extxyz").read_bytes()
        second, second_rng = self.run_segment(directory)
        np.testing.assert_array_equal(first.positions, second.positions)
        np.testing.assert_array_equal(first.get_momenta(), second.get_momenta())
        self.assertEqual(first_rng.bit_generator.state, second_rng.bit_generator.state)
        self.assertEqual(log_bytes, (directory / "log.jsonl").read_bytes())
        self.assertEqual(frame_bytes, (directory / "frames.extxyz").read_bytes())


    def test_progress_write_failure_resumes_from_committed_state(self):
        full_atoms, full_rng = self.run_segment(self.path / "uninterrupted_io")
        directory = self.path / "interrupted_io"

        def fail_after_commit(detail):
            if detail["step"] == 4:
                raise PermissionError("synthetic status-file sharing conflict")

        with self.assertRaises(PermissionError):
            self.run_segment(directory, progress=fail_after_commit)
        _, _, saved = _ENGINE.load_checkpoint(directory / "checkpoint.npz")
        self.assertEqual(saved["step"], 4)
        for name, key in (("log.jsonl", "log"), ("frames.extxyz", "frames")):
            self.assertEqual((directory / name).stat().st_size, saved["offsets"][key])
        resumed, rng = self.run_segment(directory)
        np.testing.assert_array_equal(resumed.positions, full_atoms.positions)
        np.testing.assert_array_equal(resumed.get_momenta(), full_atoms.get_momenta())
        self.assertEqual(rng.bit_generator.state, full_rng.bit_generator.state)


class AtomicFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic_atomic_file_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.json"
        self.path.write_text('{"old": true}', encoding="utf-8")

    @staticmethod
    def sharing_error():
        error = PermissionError("synthetic Windows sharing violation")
        error.winerror = 32
        return error

    def test_transient_windows_conflict_preserves_old_file_until_success(self):
        replace = _ENGINE.os.replace
        attempts = []

        def transient(source, target):
            attempts.append(1)
            self.assertEqual(json.loads(self.path.read_text()), {"old": True})
            if len(attempts) < 3:
                raise self.sharing_error()
            return replace(source, target)

        with patch.object(_ENGINE.os, "replace", side_effect=transient), patch.object(_ENGINE.time, "sleep"):
            _ENGINE.atomic_json(self.path, {"new": True})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads(self.path.read_text()), {"new": True})

    def test_persistent_conflict_is_bounded_and_keeps_old_and_pending_data(self):
        with patch.object(_ENGINE.os, "replace", side_effect=self.sharing_error()) as replace, patch.object(_ENGINE.time, "sleep"):
            with self.assertRaises(PermissionError):
                _ENGINE.atomic_json(self.path, {"new": True})
        self.assertEqual(replace.call_count, 8)
        self.assertEqual(json.loads(self.path.read_text()), {"old": True})
        self.assertEqual(json.loads(self.path.with_name("runtime.json.tmp").read_text()), {"new": True})

    def test_other_io_error_is_not_retried(self):
        with patch.object(_ENGINE.os, "replace", side_effect=OSError("disk error")) as replace, patch.object(_ENGINE.time, "sleep") as sleep:
            with self.assertRaises(OSError):
                _ENGINE.atomic_json(self.path, {"new": True})
        self.assertEqual(replace.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
