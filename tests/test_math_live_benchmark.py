"""Offline tests only; no real provider calls or untrusted code execution."""

import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
import yaml
from benchmarks.math_live_support import load_fixture, redact, token_totals

REPO = Path(__file__).resolve().parents[1]


def test_original_math_fixture_and_exact_plan():
    plan = json.loads((REPO / "benchmarks/math_live/plan.json").read_text())
    assert len(plan["turns"]) == 24
    assert [x["number"] for x in plan["turns"]] == list(range(1, 25))
    assert plan["turns"][22]["student_message"] == "صحح لي الحل الذي في الصورة."
    original = load_fixture(REPO, plan)
    assert len(original) == 1278353
    assert (
        hashlib.sha256(original).hexdigest()
        == "5369d565c65242bd9f224f14c7f2459d0e2296f45320362f947647b7e366bdb7"
    )
    assert plan["cost_guard"]["generation_requests_max"] == 128
    assert plan["cost_guard"]["reported_input_soft_stop"] == 2500000


def test_corrupt_fixture_rejected():
    plan = json.loads((REPO / "benchmarks/math_live/plan.json").read_text())
    plan["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        load_fixture(REPO, plan)


def test_token_unknowns_not_zero_or_double_counted():
    result = token_totals(
        [
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "cached_tokens": 4,
                "thinking_tokens": 1,
            },
            {"input_tokens": None, "output_tokens": None},
        ]
    )
    assert result["known_total_tokens"] == 12
    assert result["known_cached_tokens"] == 4
    assert result["known_thinking_tokens"] == 1
    assert result["unknown_usage_requests"] == 1
    assert result["unknown_cache_requests"] == 1
    assert result["unknown_thinking_requests"] == 1


@pytest.mark.parametrize(
    "row",
    [
        {"input_tokens": -1, "output_tokens": 2},
        {"input_tokens": 3, "output_tokens": 4, "total_tokens": 99},
    ],
)
def test_bad_counters_rejected(row):
    with pytest.raises(ValueError):
        token_totals([row])


def test_export_redacts_credentials_and_hidden_model_fields():
    secret = "synthetic-test-credential-with-enough-length"
    payload = {
        "authorization": secret,
        "api_key": secret,
        "plain": "message " + secret,
        "other": "AQ." + "X" * 40,
        "parts": [
            {"thought": True, "text": "hidden"},
            {"text": "public", "thoughtSignature": "private"},
        ],
        "extra_content": {"google": {"thought_signature": "private"}},
        "thinking_tokens": 7,
    }
    clean = redact(payload, [secret])
    encoded = json.dumps(clean)
    assert (
        secret not in encoded and "hidden" not in encoded and "private" not in encoded
    )
    assert clean["thinking_tokens"] == 7
    assert clean["parts"] == [{"text": "public"}]


def report_module():
    spec = importlib.util.spec_from_file_location(
        "math_live_report_test", REPO / "benchmarks/report_math_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_report_is_partial_not_success(tmp_path):
    evidence = report_module().make_evidence(tmp_path)
    assert evidence["executed_turns"] == 0 and not evidence["complete_run"]
    assert evidence["tokens"]["requests"] == 0
    assert evidence["missing_image_case_zero_provider_requests"] is None


def test_export_never_copies_private_db_key_or_runtime_secret(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    secret = "test-private-secret-0123456789"
    (private / "key").write_text(secret)
    (private / "platform.sqlite3").write_text("not a database")
    (tmp_path / "configuration.json").write_text(
        json.dumps({"url": "provider", "api_key": secret, "warning": secret})
    )
    monkeypatch.setenv("GEMINI_API_KEY_FILE", str(private / "key"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report_module().export(tmp_path)
    names = {p.name for p in (tmp_path / "public").iterdir()}
    assert "key" not in names and "platform.sqlite3" not in names
    assert all(secret not in p.read_text() for p in (tmp_path / "public").iterdir())


def test_manual_workflow_never_calls_provider_on_push_or_pull_request():
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/math-live-benchmark.yml").read_text()
    )
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch"}
    assert events["workflow_dispatch"]["inputs"]["mode"]["default"] == "preflight"
    assert events["workflow_dispatch"]["inputs"]["confirm_live"]["default"] is False
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["benchmark"]
    assert "private == true" in job["if"] and "default_branch" in job["if"]
    steps = job["steps"]
    live = next(s for s in steps if "original 24" in s.get("name", ""))
    assert (
        live["if"] == "inputs.mode == 'live'"
        and "secrets.GEMINI_API_KEY" in live["env"]["GEMINI_API_KEY"]
    )
    assert "unset GEMINI_API_KEY" in live["run"]
    assert all("GEMINI_API_KEY" not in s.get("env", {}) for s in steps if s is not live)
    upload = next(
        s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")
    )
    assert upload["with"]["path"].endswith("/public/")
    broker = next(s for s in steps if "loopback-only" in s.get("name", ""))
    assert "-p 127.0.0.1:18871:8080" in broker["run"]
    assert "GEMINI_API_KEY" not in broker["run"]
    assert "docker.sock" not in live["run"]


def test_portable_runner_imports_actual_backend_and_creates_only_test_data(
    tmp_path, monkeypatch
):
    # Local partial workspaces may not contain bac; full repository CI must run this.
    pytest.importorskip("bac.core.services")
    monkeypatch.setenv("MASAR_BENCHMARK_ROOT", str(tmp_path / "benchmark"))
    monkeypatch.setenv("PYTHON_SANDBOX_URL", "http://127.0.0.1:18871")
    monkeypatch.setenv("PYTHON_SANDBOX_TOKEN_FILE", str(tmp_path / "not-a-live-token"))
    monkeypatch.delenv("GEMINI_API_KEY_FILE", raising=False)
    spec = importlib.util.spec_from_file_location(
        "math_live_runner_test", REPO / "benchmarks/run_math_live.py"
    )
    from bac.agent.tools import Tools
    from bac.agent.full_index import FullIndexCoordinator

    before = (Tools.execute, Tools.answer, FullIndexCoordinator.__init__)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert before == (Tools.execute, Tools.answer, FullIndexCoordinator.__init__)
    assert len(runner.CASES) == 24 and runner.LEDGER == []
    services = runner.services()
    try:
        assert services.settings.data_dir == tmp_path / "benchmark/private/qa-data"
        assert services.settings.python_sandbox_url == "http://127.0.0.1:18871"
        assert services.db.rows("SELECT * FROM model_usage") == []
        assert services.db.rows("SELECT * FROM active_models") == []
    finally:
        services.close()
