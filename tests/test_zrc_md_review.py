"""Synthetic log-contract tests. These records are not research MD data."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zrc_md_review.py"
_SPEC = importlib.util.spec_from_file_location("zrc_md_review", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
review_segment = _MODULE.review_segment


class SegmentReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic_md_review_")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.expected = {
            "ensemble": "NVT", "atoms": 8, "time_step_fs": 0.5,
            "expected_duration_fs": 500, "target_temperature_K": 300,
            "stage": "pilot", "log_interval_fs": 5,
        }
        self.rows = [self.record(step) for step in range(0, 1001, 10)]

    def record(self, step):
        return {
            "step": step, "time_fs": step * 0.5, "stage": "pilot",
            "target_temperature_K": 300, "temperature_K": 300,
            "potential_eV": -100, "kinetic_eV": 1, "total_eV": -99,
            "pressure_GPa": 1, "max_force_eV_A": 2,
            "min_pair_distances_A": {"Zr-Zr": 3.2, "Zr-C": 2.1, "C-C": 3.2},
            "finite": True, "atoms": 8, "volume_A3": 103.823,
        }

    def review(self):
        (self.path / "log.jsonl").write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")
        return review_segment(self.path, self.expected)

    def test_short_complete_pilot_never_certifies_equilibration_or_physics(self):
        result = self.review()
        self.assertTrue(result["hard_pass"])
        self.assertTrue(result["completed_numerically"])
        self.assertFalse(result["equilibrated"])
        self.assertFalse(result["physical_validated"])
        self.assertEqual(result["metrics"]["completed_steps"], 1000)

    def test_missing_endpoint_and_interior_record_fail(self):
        for index in (-1, 40):
            with self.subTest(index=index):
                original = self.rows[:]
                del self.rows[index]
                self.assertFalse(self.review()["hard_pass"])
                self.rows = original

    def test_duplicate_restarted_record_fails(self):
        self.rows.insert(30, self.rows[29].copy())
        result = self.review()
        self.assertFalse(result["hard_pass"])
        self.assertTrue(any("duplicate" in error for error in result["errors"]))

    def test_nonfinite_scalar_cannot_be_hidden_by_finite_flag(self):
        self.rows[40]["max_force_eV_A"] = float("nan")
        self.assertFalse(self.review()["hard_pass"])

    def test_time_and_step_contract_mismatch_fails(self):
        self.rows[25]["time_fs"] += 0.5
        self.assertFalse(self.review()["hard_pass"])

    def test_fixed_volume_and_composition_contracts(self):
        for field, wrong in (("atoms", 64), ("volume_A3", 110), ("stage", "sampling")):
            with self.subTest(field=field):
                original = self.rows[50][field]
                self.rows[50][field] = wrong
                self.assertFalse(self.review()["hard_pass"])
                self.rows[50][field] = original

    def test_large_small_cell_temperature_fluctuations_are_not_hard_failure(self):
        for index, row in enumerate(self.rows):
            row["temperature_K"] = 100 if index % 2 else 500
        self.assertTrue(self.review()["hard_pass"])

    def test_finite_temperature_catastrophe_is_a_hard_failure(self):
        self.rows[50]["temperature_K"] = 100001
        result = self.review()
        self.assertFalse(result["hard_pass"])
        self.assertTrue(any("Explosive" in error for error in result["errors"]))

    def test_ramp_contract_matches_all_targets_and_never_certifies_equilibrium(self):
        self.expected.update(stage="ramp", ramp_start_K=300, target_temperature_K=1500)
        for row in self.rows:
            row["stage"] = "ramp"
            row["target_temperature_K"] = 300 + 1200 * row["time_fs"] / 500
            row["temperature_K"] = row["target_temperature_K"]
        result = self.review()
        self.assertTrue(result["hard_pass"])
        self.assertFalse(result["equilibrated"])
        self.assertTrue(any("heating/cooling" in warning for warning in result["warnings"]))
        self.rows[50]["target_temperature_K"] = 1500
        self.assertFalse(self.review()["hard_pass"])

    def test_ramp_requires_start_and_nvt(self):
        self.expected["stage"] = "ramp"
        self.assertFalse(self.review()["hard_pass"])
        self.expected.update(ramp_start_K=300, ensemble="NVE")
        self.assertFalse(self.review()["hard_pass"])

    def test_cooling_ramp_is_supported(self):
        self.expected.update(stage="ramp", ramp_start_K=1500, target_temperature_K=300)
        for row in self.rows:
            row["stage"] = "ramp"
            row["target_temperature_K"] = 1500 - 1200 * row["time_fs"] / 500
        self.assertTrue(self.review()["hard_pass"])

    def test_short_pair_distance_is_warning_not_arbitrary_physical_failure(self):
        self.rows[20]["min_pair_distances_A"]["Zr-C"] = 1.1
        result = self.review()
        self.assertTrue(result["hard_pass"])
        self.assertTrue(any("pair distance" in item for item in result["warnings"]))

    def test_nve_drift_unit_conversion_and_threshold(self):
        self.expected["ensemble"] = "NVE"
        for slope, expected_pass in ((0.5, True), (-1.5, False)):
            with self.subTest(slope=slope):
                for row in self.rows:
                    # meV/atom/ps -> eV of the whole eight-atom cell.
                    drift_eV = slope * (row["time_fs"] / 1000) * 8 / 1000
                    row["potential_eV"] = -100 + drift_eV
                    row["total_eV"] = row["potential_eV"] + row["kinetic_eV"]
                result = self.review()
                self.assertEqual(result["hard_pass"], expected_pass)
                self.assertAlmostEqual(result["metrics"]["nve"]["linear_drift_meV_atom_ps"], slope, places=7)

    def test_final_shorter_logging_interval_is_valid(self):
        self.expected["expected_duration_fs"] = 502
        self.rows.append(self.record(1004))
        self.assertTrue(self.review()["hard_pass"])

    def test_inconsistent_energy_and_truncated_json_fail(self):
        self.rows[5]["total_eV"] = -95
        self.assertFalse(self.review()["hard_pass"])
        (self.path / "log.jsonl").write_text('{"step":', encoding="utf-8")
        self.assertFalse(review_segment(self.path, self.expected)["hard_pass"])

    def test_missing_file_and_invalid_contract_return_errors(self):
        self.assertFalse(review_segment(self.path, self.expected)["hard_pass"])
        self.expected["time_step_fs"] = 0
        result = review_segment(self.path, self.expected)
        self.assertTrue(result["errors"])
        self.assertFalse(result["hard_pass"])


if __name__ == "__main__":
    unittest.main()
