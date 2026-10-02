from bac.core.activity import PUBLIC_EVENTS, Activity
from bac.core.db import js
from bac.ops.diagnostics import diagnose_run, safe_diagnostic
from bac.agent.engine import AgentEngine
from tests.test_agent import chat_and_config


def test_diagnostic_scrubs_values_and_is_not_public(services):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "PRIVATE QUESTION")
    secret = "PRIVATE KEY / BOOK / USER"
    payload = safe_diagnostic(
        "plot_function",
        {
            "error": "TOOL_INPUT_OR_SOURCE_ERROR",
            "message": secret,
            "issues": [
                {"field": "lower", "type": "missing", "message": secret},
                {"field": secret, "type": secret},
            ],
        },
    )
    assert payload["issues"][0] == {"field": "lower", "type": "missing"}
    assert secret not in js(payload)
    run = engine.claim()
    assert run["id"] == rid
    engine.emit(
        run,
        "tool_diagnostic",
        payload
        | {
            "arguments": secret,
            "message": secret,
            "sources": secret,
        },
    )
    services.db.execute(
        "UPDATE agent_runs SET status='FAILED',error=? WHERE id=?", (secret, rid)
    )
    report = diagnose_run(services.db)
    assert report["error"] == "OTHER_FAILURE"
    assert report["diagnostics"][0]["stage"] == "diagram"
    assert "PRIVATE" not in js(report) and rid not in js(report)
    assert "plot_function" not in js(report)
    assert "tool_diagnostic" not in PUBLIC_EVENTS
    projection = Activity("public")
    projection.feed({"id": 1, "type": "tool_diagnostic", "payload": js(payload)})
    assert not projection.snapshot()["items"]


def test_diagnostic_missing_and_provider_failure(services):
    assert diagnose_run(services.db) == {"found": False}
    user, chat = chat_and_config(services)
    rid = AgentEngine(services).enqueue(chat, user, "PRIVATE QUESTION")
    services.db.execute(
        "UPDATE agent_runs SET status='FAILED',error='HTTP_503' WHERE id=?", (rid,)
    )
    assert diagnose_run(services.db, rid)["error"] == "HTTP_503"
    assert diagnose_run(services.db, rid)["diagnostics"] == []
