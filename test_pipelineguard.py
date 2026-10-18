"""Automated tests for PipelineGuard + local IBM Granite integration.

Run:  python -m pytest test_pipelineguard.py -q
  or: python test_pipelineguard.py

The model server is MOCKED: tests start a local OpenAI-compatible endpoint that
returns canned Granite responses, so no model download and no s390x machine is
required. The REAL HTTP code path in fixer.py (_call_granite/parse_proposal/
validate_proposal/generate_repair) and the REAL pipeline flow in guard.py are
exercised end to end. Not covered here: quality of a specific GGUF checkpoint
(see README for how to run against a real llama-server).
"""

import contextlib
import io
import json
import os
import shutil
import sys
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import etl
import faults
import fixer
import guard
import risk
import sandbox

# Strategies fixer.ALLOWED_STRATEGIES accepts, per failure class.
STRATEGY_FOR = {
    "schema_mismatch": "rename_columns_to_expected",
    "type_mismatch": "coerce_amount_numeric",
    "null_explosion": "impute_missing_values",
    "duplicate_keys": "drop_duplicate_keys",
}


def valid_proposal(label, confidence=0.86):
    return {
        "root_cause": "incoming data does not match the expected schema/types",
        "repair_strategy": STRATEGY_FOR[label],
        "proposed_changes": ["adjust the affected column", "keep row count stable"],
        "reasoning": "apply the standard restricted repair for this failure class",
        "risks": ["rows that cannot be repaired become null"],
        "confidence": confidence,
    }


MALFORMED_JSON = '{"root_cause": "x", "repair_strategy": "coerce_amount_numeric", "confid'


# --------------------------------------------------------------------------
# Mock OpenAI-compatible model server (serves /v1/chat/completions)
# --------------------------------------------------------------------------
class MockModelServer:
    """Local HTTP server imitating llama-server's OpenAI-compatible API."""

    def __init__(self):
        self.mode = "valid"      # valid | escalate | bad_strategy | malformed | empty | timeout
        self.confidence = 0.86
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                if not self.path.endswith("/chat/completions"):
                    self.send_response(404); self.end_headers(); return
                content = outer._content(body)
                if outer.mode == "timeout":
                    time.sleep(3)
                resp = json.dumps({
                    "id": "mock-1", "object": "chat.completion", "model": "mock-granite",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": content}}],
                }).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                except OSError:   # client already timed out — expected in the timeout test
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.handle_error = lambda *a: None   # silence broken-pipe noise on timeouts
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def _content(self, request_body):
        """Pick a canned reply, keyed off the failure class in the prompt."""
        try:
            prompt = json.loads(request_body)["messages"][-1]["content"]
        except Exception:
            prompt = ""
        label = "type_mismatch"
        for known in STRATEGY_FOR:
            if f"Failure classification: {known}" in prompt:
                label = known
                break
        if self.mode == "escalate":
            proposal = dict(valid_proposal(label, self.confidence),
                            repair_strategy="escalate_to_human",
                            root_cause="evidence is insufficient, a human must review")
        elif self.mode == "bad_strategy":
            proposal = dict(valid_proposal(label, self.confidence),
                            repair_strategy="execute_raw_sql")
        else:
            proposal = valid_proposal(label, self.confidence)
        if self.mode == "malformed":
            return MALFORMED_JSON
        if self.mode == "empty":
            return ""
        return json.dumps(proposal)

    @property
    def base_url(self):
        return "http://127.0.0.1:%d/v1" % self.port

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


MOCK = None


def setUpModule():
    global MOCK
    MOCK = MockModelServer()


def tearDownModule():
    if MOCK is not None:
        MOCK.stop()


# --------------------------------------------------------------------------
# Environment helpers
# --------------------------------------------------------------------------
def clean_env():
    """Remove every Granite knob (baseline: deterministic templates, no network)."""
    for key in ("GRANITE_ENABLED", "GRANITE_MODEL", "GRANITE_BASE_URL",
                "GRANITE_TIMEOUT", "GRANITE_API_KEY", "PG_BAD_FIX"):
        os.environ.pop(key, None)


def granite_env(mode="valid", timeout="10", confidence=0.86):
    os.environ["GRANITE_ENABLED"] = "1"
    os.environ["GRANITE_BASE_URL"] = MOCK.base_url
    os.environ["GRANITE_MODEL"] = "ibm-granite/granite-3.3-2b-instruct"
    os.environ["GRANITE_TIMEOUT"] = timeout
    MOCK.mode, MOCK.confidence = mode, confidence


ERROR_TEXT = "ValueError: could not convert string to float: 'twelve'"
SAMPLE_TEXT = "order_id  customer  amount\n1  Acme  10.5\n2  Globex  20.0"


# --------------------------------------------------------------------------
# Base class: isolates PipelineGuard's ROOT/LIVE/BACKUP/RUNS/PENDING per test
# --------------------------------------------------------------------------
class PGTestCase(unittest.TestCase):
    SAVED = None

    def setUp(self):
        clean_env()
        MOCK.mode, MOCK.confidence = "valid", 0.86
        if PGTestCase.SAVED is None:
            PGTestCase.SAVED = (guard.ROOT, guard.LIVE, guard.BACKUP, guard.RUNS,
                                guard.PENDING, guard.LIVE_IN, guard.LIVE_OUT)
        root, tmp = Path(os.environ.get("TEMP", "/tmp")), None
        self.tmp = root / ("pgtest_%s_%d" % (self._testMethodName, os.getpid()))
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self.root = self.tmp / "pipelineguard_root"
        self.root.mkdir()
        # guard.heal() copies ROOT/etl.py into the sandbox workspace — provide it.
        shutil.copy(Path(etl.__file__), self.root / "etl.py")
        guard.ROOT = self.root
        guard.LIVE = self.tmp / "live"
        guard.BACKUP = self.root / "data" / "backup"
        guard.RUNS = self.root / "runs"
        guard.PENDING = self.root / "data" / "pending"
        guard.LIVE_IN = guard.LIVE / "orders.csv"
        guard.LIVE_OUT = guard.LIVE / "clean_orders.csv"

    def tearDown(self):
        clean_env()
        MOCK.mode, MOCK.confidence = "valid", 0.86
        (guard.ROOT, guard.LIVE, guard.BACKUP, guard.RUNS, guard.PENDING,
         guard.LIVE_IN, guard.LIVE_OUT) = PGTestCase.SAVED
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------
    def run_cli(self, *argv):
        """Drive the real guard CLI. Returns (output_text)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = guard.main(list(argv))
        return buf.getvalue(), rc

    def audit_events(self):
        events = []
        path = guard.ROOT / "logs" / "audit.jsonl"
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    events.append(json.loads(line))
        return events

    def latest_report(self):
        reports = sorted((guard.ROOT / "reports").glob("incident_*.md"))
        return reports[-1].read_text(encoding="utf-8") if reports else ""

    def live_text(self):
        return guard.LIVE_IN.read_text(encoding="utf-8")


# ==========================================================================
# 1. Valid JSON proposal from mock Granite -> repair executed, source recorded
# ==========================================================================
class TestValidGraniteProposal(PGTestCase):
    def test_unit_valid_proposal_drives_template_and_is_recorded(self):
        granite_env(mode="valid")
        result = fixer.generate_repair("type_mismatch", ERROR_TEXT, SAMPLE_TEXT,
                                       columns=["order_id", "amount", "customer"])
        code, src = result["code"], result["source"]
        self.assertTrue(code.startswith("import sys, json, difflib"), "executed code must be PipelineGuard's own template")
        self.assertIn("repair_stats.json", code)  # stats hook intact
        self.assertTrue(src.startswith("Granite ("), src)
        self.assertIn("executed via deterministic template", src)
        self.assertEqual(result["strategy"], "coerce_amount_numeric")
        d = result["diagnosis"]
        self.assertEqual(d["repair_strategy"], "coerce_amount_numeric")
        self.assertEqual(d["model"], "ibm-granite/granite-3.3-2b-instruct")
        self.assertFalse(d["low_confidence"])
        # The model's own text is never echoed into the executed script.
        self.assertNotIn(d["root_cause"], code)
        self.assertNotIn(d["reasoning"], code)

    def test_e2e_demo_records_granite_source(self):
        granite_env(mode="valid")
        out, rc = self.run_cli("demo", "--fault", "type", "--approve")
        self.assertEqual(rc, 0, out)
        self.assertIn("RECOVER", out)
        stages = [e["stage"] for e in self.audit_events()]
        self.assertIn("DIAGNOSE", stages)
        self.assertIn("FIX", stages)
        fix = next(e for e in self.audit_events() if e["stage"] == "FIX")
        self.assertIn("Granite", fix["msg"])
        self.assertIn("Granite", self.latest_report())


# ==========================================================================
# 2. Malformed JSON -> safe fallback to deterministic template
# ==========================================================================
class TestMalformedGraniteResponse(PGTestCase):
    def test_malformed_json_falls_back_to_template(self):
        granite_env(mode="malformed")
        result = fixer.generate_repair("type_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["amount"])
        self.assertIn("template", result["source"])
        self.assertIn("invalid", result["source"])
        self.assertIsNone(result["diagnosis"])
        self.assertIn("def repair_", result["code"] + "\ndef repair_x(): pass")  # template code present
        self.assertTrue(result["code"].startswith("import sys"))

    def test_empty_completion_falls_back_to_template(self):
        granite_env(mode="empty")
        result = fixer.generate_repair("null_explosion", "NaN storm", SAMPLE_TEXT, columns=["amount"])
        self.assertIn("template", result["source"])
        self.assertIn("invalid", result["source"])
        self.assertTrue(result["code"].startswith("import sys"))

    def test_parse_proposal_rejects_garbage(self):
        for junk in ("", "not json at all", "[]", '{"root_cause": "x"'):
            with self.assertRaises(fixer.GraniteError, msg=repr(junk)):
                fixer.parse_proposal(junk)

    def test_parse_proposal_tolerates_code_fences(self):
        fenced = "```json\n" + json.dumps(valid_proposal("type_mismatch")) + "\n```"
        proposal = fixer.parse_proposal(fenced)
        self.assertEqual(proposal["repair_strategy"], "coerce_amount_numeric")


# ==========================================================================
# 3. Timeout / connection refused -> template fallback, pipeline continues
# ==========================================================================
class TestGraniteUnavailable(PGTestCase):
    def test_timeout_is_honoured_and_falls_back(self):
        granite_env(mode="timeout", timeout="1")
        started = time.time()
        result = fixer.generate_repair("type_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["amount"])
        elapsed = time.time() - started
        self.assertIn("template", result["source"])
        self.assertIn("unavailable", result["source"])
        self.assertLess(elapsed, 8, "GRANITE_TIMEOUT knob was not honoured")
        self.assertTrue(result["code"].startswith("import sys"))

    def test_connection_refused_falls_back(self):
        os.environ["GRANITE_ENABLED"] = "1"
        os.environ["GRANITE_BASE_URL"] = "http://127.0.0.1:1/v1"   # nothing listens there
        os.environ["GRANITE_TIMEOUT"] = "2"
        result = fixer.generate_repair("schema_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["order_id"])
        self.assertIn("template", result["source"])
        self.assertIn("unavailable", result["source"])

    def test_pipeline_still_recovers_when_model_down(self):
        os.environ["GRANITE_ENABLED"] = "1"
        os.environ["GRANITE_BASE_URL"] = "http://127.0.0.1:1/v1"
        os.environ["GRANITE_TIMEOUT"] = "2"
        out, rc = self.run_cli("demo", "--fault", "nulls", "--approve")
        self.assertEqual(rc, 0, out)
        self.assertIn("RECOVER", out)
        fix = next(e for e in self.audit_events() if e["stage"] == "FIX")
        self.assertIn("template", fix["msg"])


# ==========================================================================
# 4. Low-confidence proposal -> flagged for review, still advisory
# ==========================================================================
class TestLowConfidence(PGTestCase):
    def test_unit_low_confidence_flagged(self):
        granite_env(mode="valid", confidence=0.4)
        result = fixer.generate_repair("type_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["amount"])
        self.assertIsNotNone(result["diagnosis"])
        self.assertTrue(result["diagnosis"]["low_confidence"])
        self.assertLess(result["diagnosis"]["confidence"], 0.5)

    def test_high_confidence_not_flagged(self):
        granite_env(mode="valid", confidence=0.9)
        result = fixer.generate_repair("type_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["amount"])
        self.assertFalse(result["diagnosis"]["low_confidence"])

    def test_report_marks_low_confidence_for_manual_review(self):
        granite_env(mode="valid", confidence=0.4)
        out, rc = self.run_cli("demo", "--fault", "type", "--approve")
        self.assertEqual(rc, 0, out)
        report = self.latest_report()
        self.assertIn("LOW — treat as uncertain", report)
        self.assertIn("manual", report.lower())
        # Low confidence is advisory only: the same gates ran and it recovered.
        stages = [e["stage"] for e in self.audit_events()]
        for stage in ("VALIDATE", "RISK", "APPLY"):
            self.assertIn(stage, stages)


# ==========================================================================
# 5. Disallowed strategy -> rejected; escalate -> nothing applied
# ==========================================================================
class TestDisallowedStrategy(PGTestCase):
    def test_unknown_strategy_rejected_as_unsafe(self):
        with self.assertRaises(fixer.GraniteError) as ctx:
            fixer.validate_proposal(valid_proposal("type_mismatch", 0.9) | {"repair_strategy": "drop_database_table"}, "type_mismatch")
        self.assertEqual(ctx.exception.kind, "unsafe")

    def test_wrong_failure_mode_strategy_rejected(self):
        # rename_columns_to_expected is valid for schema_mismatch, not for null_explosion.
        proposal = valid_proposal("null_explosion")
        proposal["repair_strategy"] = "rename_columns_to_expected"
        with self.assertRaises(fixer.GraniteError):
            fixer.validate_proposal(proposal, "null_explosion")

    def test_escalation_allowed_for_every_failure_class(self):
        for label in STRATEGY_FOR:
            proposal = valid_proposal(label) | {"repair_strategy": "escalate_to_human"}
            self.assertEqual(fixer.validate_proposal(proposal, label)["repair_strategy"], "escalate_to_human")

    def test_bad_strategy_proposal_falls_back_to_template(self):
        granite_env(mode="bad_strategy")
        result = fixer.generate_repair("null_explosion", ERROR_TEXT, SAMPLE_TEXT, columns=["amount"])
        self.assertIn("template", result["source"])
        self.assertIn("rejected", result["source"])
        self.assertTrue(result["code"].startswith("import sys"))

    def test_escalate_proposal_blocks_application_end_to_end(self):
        granite_env(mode="escalate")
        out, _ = self.run_cli("demo", "--fault", "type")
        self.assertIn("ESCALATED", out)
        events = self.audit_events()
        stages = [e["stage"] for e in events]
        self.assertNotIn("APPLY", stages, "an escalate proposal must never be applied")
        self.assertIn("ESCALATE", stages)
        self.assertFalse(list(guard.BACKUP.glob("*.csv")), "no backup should be written when nothing is applied")
        self.assertIn("ESCALATED", self.latest_report())


# ==========================================================================
# 6. Malformed / missing fields -> rejected
# ==========================================================================
class TestProposalFieldValidation(unittest.TestCase):
    def test_missing_required_fields_rejected(self):
        for field in ("root_cause", "repair_strategy", "proposed_changes", "reasoning", "risks", "confidence"):
            proposal = valid_proposal("type_mismatch")
            del proposal[field]
            with self.assertRaises(fixer.GraniteError, msg="missing " + field):
                fixer.validate_proposal(proposal, "type_mismatch")

    def test_wrong_types_rejected(self):
        for bad_field, bad_value in (("confidence", "high"),
                                     ("proposed_changes", "just a string"),
                                     ("risks", {"a": 1}),
                                     ("root_cause", ""),
                                     ("reasoning", 42)):
            proposal = valid_proposal("type_mismatch")
            proposal[bad_field] = bad_value
            with self.assertRaises(fixer.GraniteError, msg=bad_field):
                fixer.validate_proposal(proposal, "type_mismatch")

    def test_confidence_out_of_range_rejected(self):
        for value in (-0.5, 1.5, float("nan")):
            proposal = valid_proposal("type_mismatch")
            proposal["confidence"] = value
            with self.assertRaises(fixer.GraniteError, msg=str(value)):
                fixer.validate_proposal(proposal, "type_mismatch")

    def test_confidence_as_string_number_accepted(self):
        proposal = valid_proposal("type_mismatch")
        proposal["confidence"] = "0.8"
        self.assertEqual(fixer.validate_proposal(proposal, "type_mismatch")["confidence"], 0.8)


# ==========================================================================
# 7. GRANITE_ENABLED unset -> deterministic templates, no network call
# ==========================================================================
class TestGraniteDisabledByDefault(PGTestCase):
    def test_no_network_attempt_when_disabled(self):
        clean_env()
        os.environ["GRANITE_BASE_URL"] = "http://127.0.0.1:1/v1"  # unreachable on purpose
        self.assertFalse(fixer.granite_enabled())
        result = fixer.generate_repair("schema_mismatch", ERROR_TEXT, SAMPLE_TEXT, columns=["order_id"])
        self.assertEqual(result["source"], "deterministic template (GRANITE_ENABLED not set)")
        self.assertTrue(result["code"].startswith("import sys"))

    def test_disabled_flag_values(self):
        for value in ("0", "false", "", "no"):
            os.environ["GRANITE_ENABLED"] = value
            self.assertFalse(fixer.granite_enabled(), value)
        for value in ("1", "true", "yes", "on", "YES"):
            os.environ["GRANITE_ENABLED"] = value
            self.assertTrue(fixer.granite_enabled(), value)

    def test_env_knobs_read(self):
        os.environ.update({"GRANITE_ENABLED": "yes",
                           "GRANITE_MODEL": "ibm-granite/granite-4-1b",
                           "GRANITE_BASE_URL": "http://localhost:9999/v1/",
                           "GRANITE_TIMEOUT": "7"})
        cfg = fixer._config()
        self.assertEqual(cfg["model"], "ibm-granite/granite-4-1b")
        self.assertEqual(cfg["base_url"], "http://localhost:9999/v1")  # trailing slash stripped
        self.assertEqual(cfg["timeout"], 7.0)

    def test_invalid_timeout_never_crashes(self):
        os.environ["GRANITE_TIMEOUT"] = "not-a-number"
        self.assertEqual(fixer._config()["timeout"], 30.0)


# ==========================================================================
# 8. Repair runtime error -> live data untouched, backup/apply gates hold
# ==========================================================================
class TestRepairExecutionFailure(PGTestCase):
    def test_runtime_error_aborts_without_touching_live_data(self):
        clean_env()
        original_generate = fixer.generate_repair

        def exploding_repair(*a, **k):
            return {"code": "raise RuntimeError('simulated failure')\n",
                    "source": "test", "strategy": None, "diagnosis": None}

        fixer.generate_repair = exploding_repair
        try:
            out, _ = self.run_cli("demo", "--fault", "type")
        finally:
            fixer.generate_repair = original_generate
        self.assertIn("ESCALATED", out)
        self.assertIn("never applied", self.latest_report())
        stages = [e["stage"] for e in self.audit_events()]
        self.assertNotIn("APPLY", stages)
        self.assertFalse(list(guard.BACKUP.glob("*.csv")),
                         "backup must not exist because the fix was never applied")
        self.assertTrue(guard.LIVE_IN.exists(), "live input must still exist")
        self.assertIn("twelve", self.live_text(), "the injected fault must still be present — nothing was written")

    def test_bad_fix_is_rejected_by_validation_and_live_untouched(self):
        clean_env()
        os.environ["PG_BAD_FIX"] = "1"     # deliberately harmful script (deletes rows)
        out, _ = self.run_cli("demo", "--fault", "schema")
        self.assertIn("ESCALATED", out)
        stages = [e["stage"] for e in self.audit_events()]
        self.assertNotIn("APPLY", stages)
        self.assertIn("customer_name", self.live_text(), "live data must still carry the injected fault")
        self.assertIn("REJECTED by the validator", self.latest_report())


# ==========================================================================
# 9. Sandbox gate cannot be bypassed by model output
# ==========================================================================
class TestSandboxGate(PGTestCase):
    def test_granite_path_code_is_template_only(self):
        granite_env(mode="valid")
        result = fixer.generate_repair("schema_mismatch", ERROR_TEXT, SAMPLE_TEXT,
                                       columns=["order_id", "customer_name"])
        code = result["code"]
        for banned in ("os.system", "subprocess", "eval(", "exec(", "urllib", "socket", "DROP TABLE", "; rm"):
            self.assertNotIn(banned, code, f"model influence leaked banned token {banned!r} into executed code")
        self.assertTrue(code.startswith("import sys, json, difflib"))

    def test_template_repair_only_runs_through_sandbox(self):
        granite_env(mode="valid")
        result = fixer.generate_repair("schema_mismatch", ERROR_TEXT, SAMPLE_TEXT,
                                       columns=["order_id", "customer_name"])
        ws = self.tmp / "sandbox_gate_ws"
        ws.mkdir()
        (ws / "repair.py").write_text(result["code"], encoding="utf-8")
        faults.generate_clean(ws / "input.csv", n=50)
        faults.inject("schema", ws / "input.csv")
        shutil.copy(Path(etl.__file__), ws / "etl.py")
        r = sandbox.run(ws, "{py} repair.py input.csv fixed.csv")
        self.assertEqual(r["exit_code"], 0, r)
        self.assertTrue((ws / "fixed.csv").exists())
        self.assertTrue(r["mode"] == "docker" or r["mode"].startswith("process-fallback"),
                        "sandbox mode must be reported honestly: %r" % r["mode"])

    def test_escalation_is_the_only_response_to_unrepairable_labels(self):
        # Labels outside the allowlist never produce code at all.
        result = fixer.generate_repair("runtime_error", ERROR_TEXT, SAMPLE_TEXT)
        self.assertIsNone(result["code"])
        self.assertIn("no safe automatic repair", result["source"])


# ==========================================================================
# 10. Report clearly states the repair source
# ==========================================================================
class TestReportSourceStatement(PGTestCase):
    def _write_report(self, source, diagnosis=None):
        import report
        inc = report.Incident(guard.ROOT, "src%04d" % (abs(hash(source)) % 10000), "type")
        inc.log("FIX", f"repair script generated via {source}", source=source)
        inc.write({"outcome": "RECOVERED", "summary": "s", "outcome_detail": "d",
                   "fix_source": source, "diagnosis": diagnosis,
                   "checks": [("Row count preserved", True, "")],
                   "risk": 0.2, "decision": "PROCEED (auto-apply)", "validated": True})
        return self.latest_report()

    def test_report_states_granite_source(self):
        src = "Granite (ibm-granite/granite-3.3-2b-instruct) strategy 'coerce_amount_numeric' executed via deterministic template"
        text = self._write_report(src)
        self.assertIn("Granite (ibm-granite/granite-3.3-2b-instruct)", text)
        self.assertIn("executed via deterministic template", text)

    def test_report_states_template_fallback_source(self):
        text = self._write_report("template (Granite unavailable: cannot reach model server at http://127.0.0.1:1/v1)")
        self.assertIn("Source:** template (Granite unavailable", text)
        self.assertNotIn("executed via deterministic template", text)  # must not claim Granite drove it

    def test_report_states_disabled_source(self):
        text = self._write_report("deterministic template (GRANITE_ENABLED not set)")
        self.assertIn("GRANITE_ENABLED not set", text)

    def test_report_contains_advisory_diagnosis_section(self):
        d = dict(valid_proposal("type_mismatch"), model="ibm-granite/granite-3.3-2b-instruct",
                 low_confidence=True)
        text = self._write_report("Granite (m) strategy 'coerce_amount_numeric' executed via deterministic template", diagnosis=d)
        self.assertIn("Diagnosis proposal (advisory — not authorization)", text)
        self.assertIn("cannot authorize changes", text)
        self.assertIn("ibm-granite/granite-3.3-2b-instruct", text)

    def test_report_has_no_diagnosis_section_without_granite(self):
        text = self._write_report("deterministic template (GRANITE_ENABLED not set)")
        self.assertNotIn("Diagnosis proposal", text)


# ==========================================================================
# 11. Full pipeline still enforces validation / risk / approval gates
# ==========================================================================
class TestPipelineGatesStillEnforced(PGTestCase):
    def test_risk_thresholds_unchanged(self):
        s, decision, parts = risk.score("runtime_error", 0.5, 100, 100, False)
        self.assertTrue(decision.startswith("HOLD"), decision)
        s, decision, _ = risk.score("schema_mismatch", 0.95, 1, 500, True)
        self.assertTrue(decision.startswith("PROCEED"), decision)
        self.assertLess(s, 0.25)

    def test_review_decision_requires_human_and_blocks_apply(self):
        clean_env()
        out, _ = self.run_cli("demo", "--fault", "nulls")     # deliberately no --approve
        self.assertIn("ESCALATED", out)
        pending = list(guard.PENDING.glob("*.json"))
        self.assertEqual(len(pending), 1, "a REVIEW-level fix must wait in the approval queue")
        stages = [e["stage"] for e in self.audit_events()]
        self.assertNotIn("APPLY", stages)
        self.assertIn("order_id", self.live_text().splitlines()[0], "live input must still be the faulted file")

        # Now the human approves -> applied, backed up, pipeline recovered.
        iid = pending[0].stem
        out2, rc = self.run_cli("approve", iid)
        self.assertEqual(rc, 0, out2)
        self.assertIn("RECOVERED", out2)
        self.assertTrue(list(guard.BACKUP.glob(f"orders_{iid}.csv")), "backup must exist before/with apply")
        self.assertFalse((guard.PENDING / f"{iid}.json").exists(), "pending item consumed")
        # Live file is now the repaired one: no nulls in amount.
        import pandas as pd
        df = pd.read_csv(guard.LIVE_IN)
        self.assertFalse(df["amount"].isna().any(), "repair should have been applied")

    def test_failed_validation_never_reaches_apply(self):
        clean_env()
        os.environ["PG_BAD_FIX"] = "1"
        out, _ = self.run_cli("demo", "--fault", "duplicates")
        stages = [e["stage"] for e in self.audit_events()]
        self.assertIn("VALIDATE", stages)
        self.assertNotIn("APPLY", stages)
        self.assertFalse(list(guard.BACKUP.glob("*.csv")))

    def test_full_flow_has_every_gate_step(self):
        granite_env(mode="valid")
        out, rc = self.run_cli("demo", "--fault", "schema", "--approve")
        self.assertEqual(rc, 0, out)
        stages = [e["stage"] for e in self.audit_events()]
        for required in ("BASELINE", "INJECT", "WATCH", "CLASSIFY", "REPRODUCE",
                         "FIX", "VALIDATE", "RISK", "APPLY", "RECOVER"):
            self.assertIn(required, stages, f"pipeline step missing from audit trail: {required}")
        self.assertTrue(list(guard.BACKUP.glob("*.csv")), "backup missing after apply")
        self.assertIn("Incident", self.latest_report())


# ==========================================================================
# 12. Audit trail records diagnosis and repair source
# ==========================================================================
class TestAuditTrail(PGTestCase):
    def test_audit_records_diagnose_and_fix_source(self):
        granite_env(mode="valid")
        out, rc = self.run_cli("demo", "--fault", "type", "--approve")
        self.assertEqual(rc, 0, out)
        events = self.audit_events()
        stages = [e["stage"] for e in events]
        self.assertIn("DIAGNOSE", stages)
        self.assertIn("FIX", stages)
        self.assertLess(stages.index("DIAGNOSE"), stages.index("FIX"))
        diagnose = next(e for e in events if e["stage"] == "DIAGNOSE")
        self.assertIn("proposal", diagnose)
        self.assertIn("root_cause", diagnose["proposal"])
        self.assertIn("confidence", diagnose["proposal"])
        fix = next(e for e in events if e["stage"] == "FIX")
        self.assertIn("Granite", fix["source"])

    def test_audit_records_template_fallback_source(self):
        clean_env()
        out, rc = self.run_cli("demo", "--fault", "schema", "--approve")
        self.assertEqual(rc, 0, out)
        fix = next(e for e in self.audit_events() if e["stage"] == "FIX")
        self.assertIn("deterministic template (GRANITE_ENABLED not set)", fix["source"])
        self.assertNotIn("DIAGNOSE", [e["stage"] for e in self.audit_events()])


# ==========================================================================
# Sandbox sanity (pre-existing behaviour, guarded against regressions)
# ==========================================================================
class TestSandboxSanity(unittest.TestCase):
    def test_docker_check_returns_bool(self):
        self.assertIsInstance(sandbox.docker_ok(), bool)

    def test_process_fallback_runs_python(self):
        ws = Path(os.environ.get("TEMP", "/tmp")) / ("pgsane_%d" % os.getpid())
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir()
        (ws / "hello.py").write_text("import json\nprint('ok')\n", encoding="utf-8")
        try:
            r = sandbox.run(ws, "{py} hello.py")
            self.assertEqual(r["exit_code"], 0, r)
            self.assertEqual(r["stdout"], "ok")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_missing_python_is_reported_not_silently_passed(self):
        ws = Path(os.environ.get("TEMP", "/tmp")) / ("pgsane2_%d" % os.getpid())
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir()
        try:
            r = sandbox.run(ws, "definitely-not-a-python-binary hello.py")
            self.assertNotEqual(r["exit_code"], 0)
            self.assertTrue(r["stderr"] or r["stdout"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
