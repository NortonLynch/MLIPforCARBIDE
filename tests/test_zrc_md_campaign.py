"""CPU mock tests of attempt recovery; no model loading or MD execution."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, sentinel


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "zrc_md_campaign_under_test", _SCRIPTS / "run_zrc_md_campaign.py"
)
_MODULE = importlib.util.module_from_spec(_SPEC)
with patch.object(sys, "path", [str(_SCRIPTS), *sys.path]):
    _SPEC.loader.exec_module(_MODULE)


class CampaignAttemptRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic_md_campaign_")
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.options = [
            {"timestep_fs": 0.5, "dtype": "float32"},
            {"timestep_fs": 0.25, "dtype": "float32"},
            {"timestep_fs": 0.25, "dtype": "float64"},
        ]
        self.job = {
            "id": "synthetic_recovery_not_research",
            "atoms": 8,
            "temperature_K": 300,
            "source_group": "synthetic_mock",
            "production": {"status": "pending", "attempts": []},
        }
        self.campaign = _MODULE.Campaign.__new__(_MODULE.Campaign)
        self.campaign.out = self.out
        self.campaign.cfg = {"md": {
            "attempts": self.options, "equilibration_ps": 5, "sampling_ps": 10,
        }}
        self.campaign.queue = {"jobs": [self.job], "gates": {}}
        self.campaign.save = Mock()
        self.campaign.stage_start = Mock(return_value=(sentinel.initial_atoms, sentinel.initial_rng))
        self.campaign.spec = Mock(side_effect=lambda job, stage, duration, dt, dtype: {
            "stage": stage, "expected_duration_fs": duration,
            "time_step_fs": dt, "dtype": dtype,
        })
        # Any unintended calculator call must fail before a GPU/model is touched.
        self.campaign.calculator = Mock(side_effect=AssertionError("GPU access in CPU mock test"))
        self.attempt1 = self.out / "jobs" / self.job["id"] / "production" / "attempt-01"
        self.calls = []

    def invoke(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.campaign.run_job(self.job, "production")

    def record_call(self, atoms, rng, directory, spec):
        self.calls.append((Path(directory), dict(spec), atoms, rng))
        Path(directory).mkdir(parents=True, exist_ok=True)

    def assert_failure_records(self, attempt, directory, count, kind):
        events = attempt["failure_events"]
        files = list(directory.glob("failure-*.json"))
        self.assertEqual(len(events), count)
        self.assertEqual(len(files), count)
        self.assertEqual(len({event["record"] for event in events}), count)
        self.assertEqual({Path(event["record"]).name for event in events}, {p.name for p in files})
        for event in events:
            self.assertEqual(event["kind"], kind)
            self.assertTrue(event["utc"])
            self.assertTrue(event["error"])
        for path in files:
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["error"])
        return events

    def test_infrastructure_error_raises_then_resumes_same_attempt_and_parameters(self):
        marker = b"synthetic checkpoint identity; not a real MD checkpoint"

        def fail_sampling(atoms, rng, directory, spec):
            self.record_call(atoms, rng, directory, spec)
            if spec["stage"] == "sampling":
                (directory / "checkpoint.npz").write_bytes(marker)
                raise PermissionError("synthetic transient runtime.json sharing violation")
            return sentinel.equilibrated_atoms, sentinel.equilibrated_rng, {"hard_pass": True}

        self.campaign.segment = Mock(side_effect=fail_sampling)
        with self.assertRaisesRegex(PermissionError, "sharing violation"):
            self.invoke()
        attempts = self.job["production"]["attempts"]
        self.assertEqual(len(attempts), 1)
        first = attempts[0]
        self.assertEqual(first["status"], "interrupted")
        self.assertEqual(first["parameters"], self.options[0])
        started = first["started_utc"]
        events_before = json.loads(json.dumps(self.assert_failure_records(first, self.attempt1, 1, "infrastructure")))
        failure_before = (self.attempt1 / "failure.json").read_bytes()

        def resume_sampling(atoms, rng, directory, spec):
            self.record_call(atoms, rng, directory, spec)
            self.assertEqual(directory.parent, self.attempt1)
            self.assertEqual(first["status"], "running")
            self.assertEqual(spec["time_step_fs"], 0.5)
            self.assertEqual(spec["dtype"], "float32")
            if spec["stage"] == "sampling":
                self.assertEqual((directory / "checkpoint.npz").read_bytes(), marker)
                self.assertIs(atoms, sentinel.equilibrated_atoms)
                self.assertIs(rng, sentinel.equilibrated_rng)
            return sentinel.equilibrated_atoms, sentinel.equilibrated_rng, {"hard_pass": True}

        self.campaign.segment.side_effect = resume_sampling
        self.invoke()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(self.job["production"]["status"], "passed")
        self.assertEqual(self.job["production"]["accepted_parameters"], self.options[0])
        self.assertEqual(first["started_utc"], started)
        self.assertEqual(first["failure_events"], events_before)
        self.assertEqual(len(first["resume_events"]), 1)
        self.assertTrue(first["resume_events"][0]["utc"])
        self.assertEqual((self.attempt1 / "failure.json").read_bytes(), failure_before)
        self.assertEqual([call[0].name for call in self.calls], ["equilibration", "sampling"] * 2)
        self.assertFalse((self.attempt1.parent / "attempt-02").exists())
        self.campaign.calculator.assert_not_called()

    def test_repeated_infrastructure_errors_append_unique_evidence_without_overwriting_first(self):
        for message in ("first synthetic I/O error", "second synthetic I/O error"):
            self.campaign.segment = Mock(side_effect=PermissionError(message))
            with self.assertRaisesRegex(PermissionError, message):
                self.invoke()
            if message.startswith("first"):
                first_failure = (self.attempt1 / "failure.json").read_bytes()
                first_record = next(self.attempt1.glob("failure-*.json"))
                first_record_bytes = first_record.read_bytes()

        attempts = self.job["production"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "interrupted")
        events = self.assert_failure_records(attempts[0], self.attempt1, 2, "infrastructure")
        self.assertIn("first synthetic", events[0]["error"])
        self.assertIn("second synthetic", events[1]["error"])
        self.assertEqual((self.attempt1 / "failure.json").read_bytes(), first_failure)
        self.assertEqual(first_record.read_bytes(), first_record_bytes)
        self.assertEqual(len(attempts[0]["resume_events"]), 1)
        self.assertFalse((self.attempt1.parent / "attempt-02").exists())

    def test_numerical_failure_preserves_evidence_and_uses_next_parameter_attempt(self):
        def segment(atoms, rng, directory, spec):
            self.record_call(atoms, rng, directory, spec)
            if directory.parent.name == "attempt-01" and spec["stage"] == "sampling":
                raise _MODULE.NumericalFailure("synthetic numerical instability")
            if directory.parent.name == "attempt-02" and spec["stage"] == "equilibration":
                self.assertIs(atoms, sentinel.initial_atoms)
                self.assertIs(rng, sentinel.initial_rng)
            return sentinel.equilibrated_atoms, sentinel.equilibrated_rng, {"hard_pass": True}

        self.campaign.segment = Mock(side_effect=segment)
        self.invoke()
        attempts = self.job["production"]["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual([a["status"] for a in attempts], ["failed", "passed"])
        self.assertEqual([a["parameters"] for a in attempts], self.options[:2])
        self.assertEqual(self.job["production"]["accepted_parameters"], self.options[1])
        self.assert_failure_records(attempts[0], self.attempt1, 1, "numerical")
        self.assertIn("synthetic numerical instability", (self.attempt1 / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual([call[0].parent.name for call in self.calls], ["attempt-01"] * 2 + ["attempt-02"] * 2)
        self.assertEqual([call[1]["time_step_fs"] for call in self.calls], [0.5, 0.5, 0.25, 0.25])
        self.assertEqual([call[1]["dtype"] for call in self.calls], ["float32"] * 4)
        self.assertFalse(attempts[0].get("resume_events"))
        self.assertFalse((self.attempt1.parent / "attempt-03").exists())
        self.campaign.calculator.assert_not_called()


class FinishCurrentJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="synthetic_finish_current_")
        self.addCleanup(self.tmp.cleanup)
        self.c = _MODULE.Campaign.__new__(_MODULE.Campaign)
        self.c.out = Path(self.tmp.name)
        self.c.stop_file = self.c.out / "STOP"
        self.c.config_path = self.c.out / "synthetic_config.json"
        self.c.cfg = {"matrix": {"sizes_atoms": [8]}, "model": {
            "path": "synthetic-no-model", "sha256": "synthetic", "mace_torch_version": "synthetic"}}
        self.target = {"id": "current", "pilot": {"status": "passed"}, "production": {"status": "running"}}
        self.other = {"id": "next", "pilot": {"status": "passed"}, "production": {"status": "pending"}}
        self.c.queue = {"jobs": [self.target, self.other], "gates": {
            "warm_8": {"status": "passed"}, "high_8": {"status": "passed"}}}
        self.c.save = Mock()
        self.c.initialize = Mock()
        self.c.progress = Mock()
        self.c.run_gate = Mock(side_effect=AssertionError("Unexpected gate dispatch"))
        def complete(job, phase):
            self.assertIs(job, self.target)
            self.assertEqual(phase, "production")
            job[phase]["status"] = "passed"
        self.c.run_job = Mock(side_effect=complete)

    def request(self, job_id="current"):
        _MODULE.atomic_json(self.c.out / "FINISH_CURRENT_JOB.json", {
            "job_id": job_id, "phase": "production", "allow_remaining_matrix": False})

    def test_run_finishes_only_target_then_sets_persistent_stop(self):
        from types import SimpleNamespace
        self.request()
        fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True,
            get_device_name=lambda _: "synthetic-no-GPU"), set_num_threads=lambda _: None)
        with patch.dict(sys.modules, {"torch": fake_torch}), \
             patch.object(_MODULE, "digest", return_value="synthetic"), \
             patch.object(_MODULE.importlib.metadata, "version", return_value="synthetic"):
            self.c.run()
        self.c.run_job.assert_called_once_with(self.target, "production")
        self.c.run_gate.assert_not_called()
        self.assertEqual(self.other["production"]["status"], "pending")
        self.assertEqual(self.c.queue["status"], "stopped_by_marker")
        self.assertTrue(self.c.stop_file.exists())
        result = _MODULE.read_json(self.c.out / "finish-current-job-result.json")
        self.assertEqual(result["target_status"], "passed")
        self.assertTrue(self.c.progress.call_args.args[0]["worker_exited"])

    def test_missing_request_keeps_normal_dispatch_available(self):
        self.assertFalse(self.c.finish_requested_job())
        self.c.run_job.assert_not_called()

    def test_unknown_target_refuses_all_dispatch(self):
        self.request("unknown")
        with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
            self.c.finish_requested_job()
        self.c.run_job.assert_not_called()

    def test_unpassed_gate_refuses_dispatch(self):
        self.request()
        self.c.queue["gates"]["high_8"]["status"] = "pending"
        with self.assertRaisesRegex(RuntimeError, "gates are not passed"):
            self.c.finish_requested_job()
        self.c.run_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
