"""Trusted unit programs and explicit Docker-only isolation integration tests."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import httpx
import pytest
from bac.core.config import Settings
from bac.science.python_contract import PythonCode, validate_output
from bac.science.python_runner import PythonRunner
from bac.science.python_child import compute
from bac.science import sandbox_broker as broker

LIMITS = {"timeout": 15, "cpu_seconds": 10, "memory_mb": 512, "output_chars": 16000}


def request(code, inputs=None, **limits):
    return {"code": code, "inputs": inputs or {}, "limits": LIMITS | limits}


def test_ordinary_python_imports_functions_comprehensions_and_loops():
    # Fixed trusted code only; the application must NEVER call compute directly.
    result = compute(
        request(
            'import math\ndef square(x):\n    return x*x\nvalues = [square(i) for i in range(5)]\ni = 0\nwhile i < 2:\n    i += 1\nemit("values", values)\nemit("sqrt", math.sqrt(16))\nprint("done")\ncheck("specific integer result", values[-1] == 16, "integers only")'
        )
    )
    assert result["outputs"] == {"values": [0, 1, 4, 9, 16], "sqrt": 4.0}
    assert result["stdout"] == "done\n"
    assert validate_output(result)["status"] == "computed"  # Not a forged global pass.


def test_symbolic_domains_derivatives_primitive_limit_and_original_substitution():
    code = """import sympy as sp
from sympy.calculus.util import continuous_domain
x = sp.symbols("x", real=True)
f = sp.log(x) + x**3
d = sp.diff(f, x)
primitive = sp.integrate(f, x)
check("derivative", bool(sp.simplify(d-(1/x+3*x**2)) == 0), "x>0")
check("primitive", bool(sp.simplify(sp.diff(primitive, x)-f) == 0), "x>0")
check("limit", bool(sp.limit(sp.sin(x)/x, x, 0) == 1), "punctured real domain")
original = (x*x-1)/(x-1)
domain = continuous_domain(original, x, sp.S.Reals)
check("excluded pole is preserved", not bool(domain.contains(1)), "original denominator")
roots = sp.solveset(x*x-4, x, domain=sp.S.Reals)
check("candidate substitution", all(bool((x*x-4).subs(x, r) == 0) for r in roots), "original polynomial")
emit("derivative", str(d))
emit("domain", str(domain))
emit("roots", [str(r) for r in roots])"""
    output = validate_output(compute(request(code)))
    assert output["status"] == "computed"
    assert len(output["checks"]) == 5 and all(
        c["status"] == "passed" for c in output["checks"]
    )
    assert output["outputs"]["roots"] == ["-2", "2"]


@pytest.mark.parametrize(
    "condition,status", [(True, "computed"), (False, "failed"), (None, "inconclusive")]
)
def test_check_scope_and_failure_propagation(condition, status):
    assert (
        validate_output(
            compute(
                request('check("claim", inputs["condition"])', {"condition": condition})
            )
        )["status"]
        == status
    )


@pytest.mark.parametrize(
    "code",
    [
        'emit("x", float("nan"))',
        'emit("x", float("inf"))',
        'emit("x", "z"*20000)',
        'print("z"*4097)',
        'check("claim", 1)',
        'raise ValueError("bad input")',
    ],
)
def test_bootstrap_rejects_nonfinite_oversized_or_invalid_results(code):
    with pytest.raises(ValueError):
        compute(request(code))


def chart():
    return {
        "title": "x²",
        "x_label": "x",
        "y_label": "f(x)",
        "kind": "line",
        "series": [{"label": "f", "x": [0, 1, 2], "y": [0, 1, 4]}],
    }


def test_chart_and_geometry_are_validated_not_trusted_html():
    output = validate_output(
        {"outputs": {"chart": chart()}, "checks": [], "stdout": ""}
    )
    assert (
        output["chart"]["series"][0]["y"][-1] == 4 and "chart" not in output["outputs"]
    )
    for bad in [
        chart() | {"svg": "<script>"},
        chart() | {"series": [{"label": "bad", "x": [1, 0], "y": [0, 1]}]},
        chart() | {"series": [{"label": "bad", "x": [0, 1], "y": [float("inf"), 1]}]},
    ]:
        with pytest.raises(ValueError):
            validate_output({"outputs": {"chart": bad}})
    with pytest.raises(ValueError):
        validate_output({"status": "passed", "outputs": {}})
    with pytest.raises(ValueError):
        validate_output({"outputs": {"diagram": {"html": "untrusted"}}})


def configured(tmp_path):
    token = tmp_path / "token"
    token.write_text("a" * 64)
    return replace(
        Settings(),
        python_sandbox_url="http://internal.invalid",
        python_sandbox_token_file=token,
    )


def test_client_auth_payload_authoritative_hash_and_no_proxy(tmp_path):
    settings = configured(tmp_path)

    def handler(req):
        assert req.headers["authorization"] == "Bearer " + "a" * 64
        payload = json.loads(req.content)
        assert set(payload) == {"code", "inputs", "limits"}  # No source state/AI keys.
        assert req.url.path == "/execute"
        return httpx.Response(
            200, json={"outputs": {"value": 4}, "checks": [], "stdout": ""}
        )

    runner = PythonRunner(settings, transport=httpx.MockTransport(handler))
    result = runner.execute({"code": 'emit("value", 2+2)'})
    assert result["outputs"]["value"] == 4
    assert result["code_sha256"] == hashlib.sha256(b'emit("value", 2+2)').hexdigest()
    assert result["limits"]["language"] == "python" and result["status"] == "computed"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(302, headers={"location": "https://external.invalid"}),
        httpx.Response(200, text="not JSON"),
        httpx.Response(200, text="x" * 80001),
        httpx.Response(200, json={"outputs": {}, "result_id": "forged"}),
    ],
)
def test_client_failures_never_credit_output(tmp_path, response):
    result = PythonRunner(
        configured(tmp_path), httpx.MockTransport(lambda r: response)
    ).execute({"code": "pass"})
    assert "error" in result and "outputs" not in result


def test_client_fail_closed_unconfigured_missing_token_and_input_budget(tmp_path):
    assert (
        PythonRunner(Settings()).execute({"code": "pass"})["error"]
        == "SCIENTIFIC_SANDBOX_UNAVAILABLE"
    )
    missing = replace(
        configured(tmp_path), python_sandbox_token_file=tmp_path / "missing"
    )
    assert (
        PythonRunner(missing).execute({"code": "pass"})["error"]
        == "SCIENTIFIC_SANDBOX_UNAVAILABLE"
    )
    assert (
        PythonRunner(replace(Settings(), max_tool_chars=1000)).execute(
            {"code": "pass"}
        )["error"]
        == "SCIENTIFIC_INPUT_LIMIT"
    )
    with pytest.raises(ValueError):
        PythonCode(code="pass", shell="sh")


def test_broker_only_fixed_image_no_network_no_host_mounts():
    command = broker.container_command("test-id", LIMITS)
    assert "--network=none" in command and "--read-only" in command
    assert "--cap-drop=ALL" in command and "--user=65534:65534" in command
    assert not any(
        x in command
        for x in ("-v", "--volume", "--mount", "--privileged", "--network=host")
    )
    assert command[-1] == broker.IMAGE and command.count("docker") == 1
    for bad in [
        request("pass") | {"image": "bad"},
        request("pass", timeout=999),
        request("pass", memory_mb=9999),
        request("pass", cpu_seconds=True),
        request("pass", timeout=2, cpu_seconds=10),
    ]:
        assert broker.execute(bad)["error"] == "SCIENTIFIC_INPUT_LIMIT"


@pytest.mark.parametrize(
    "program,expected",
    [
        ("import time; time.sleep(30)", "SCIENTIFIC_TIMEOUT"),
        ('import os; os.write(1, b"x"*100000)', "SCIENTIFIC_OUTPUT_LIMIT"),
        ('print("invalid json")', "SCIENTIFIC_PROCESS_FAILURE"),
        ("raise SystemExit(1)", "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT"),
    ],
)
def test_broker_deadlines_caps_always_force_container_cleanup(
    monkeypatch, program, expected
):
    # Fixed trusted simulator of Docker CLI IO, not execution of request['code'].
    calls = []
    monkeypatch.setattr(
        broker,
        "container_command",
        lambda name, limits: [sys.executable, "-I", "-c", program],
    )
    monkeypatch.setattr(
        broker.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd)
    )
    result = broker.execute(request("not executed on host", timeout=2, cpu_seconds=1))
    assert result["error"] == expected
    assert calls[-1][:3] == ["docker", "rm", "--force"]
    assert calls[-1][-1].startswith("masar-python-")
    assert broker.SLOTS.acquire(blocking=False)
    broker.SLOTS.release()


def test_broker_auth_http_and_token_permissions(tmp_path, monkeypatch):
    import threading

    token_path = tmp_path / "auth" / "token"
    # Avoid root chown in this trusted unit test; deployment tests check actual ownership.
    monkeypatch.setattr(broker.os, "getuid", lambda: 10001)
    token = broker.initialize_token(token_path)
    assert token_path.stat().st_mode & 0o777 == 0o400
    assert token_path.parent.stat().st_mode & 0o777 == 0o700
    assert broker.initialize_token(token_path) == token
    monkeypatch.setattr(broker.Handler, "token", token)
    monkeypatch.setattr(
        broker,
        "execute",
        lambda value: {"outputs": {"ok": True}, "checks": [], "stdout": ""},
    )
    server = broker.Server(("127.0.0.1", 0), broker.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_address[1])
    try:
        with httpx.Client(trust_env=False) as client:
            assert client.post(url + "/execute", json={}).status_code == 401
            assert (
                client.post(
                    url + "/execute", json={}, headers={"Authorization": "Bearer wrong"}
                ).status_code
                == 401
            )
            assert client.post(
                url + "/execute", json={}, headers={"Authorization": "Bearer " + token}
            ).json()["outputs"]["ok"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def python_services(tmp_path):
    from bac.core.services import Services

    services = Services(replace(Settings(), data_dir=tmp_path / "data"))
    yield services
    services.close()


def tools_fixture(services):
    from bac.agent.tools import Tools
    from bac.core.auth import create_user
    from bac.core.db import uid

    user_id = create_user(
        services.db, "python@example.com", "Strong-password-1", "Student"
    )
    services.db.execute(
        "UPDATE users SET study_track='experimental_sciences' WHERE id=?", (user_id,)
    )
    chat = uid("chat")
    now = time.time()
    services.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
        (chat, user_id, "Python", now, now, "mathematics"),
    )
    user = services.db.one("SELECT * FROM users WHERE id=?", (user_id,))
    return Tools(services, user, chat)


def test_only_one_advertised_science_tool_preserves_library_and_final_contract(
    python_services,
):
    from bac.science.registry import CONTRACTS

    tools = tools_fixture(python_services)
    names = {x["function"]["name"] for x in tools.definitions()}
    assert (
        "run_python" in names
        and not set(CONTRACTS) & names
        and "plot_from_result" not in names
    )
    assert {
        "render_answer",
        "get_lesson_full",
        "inspect_source_image",
        "list_private_uploads",
    } <= names


def test_real_result_pipeline_hash_graph_failure_ownership_and_cancel(python_services):
    from bac.agent.tools import Tools

    tools = tools_fixture(python_services)
    output = validate_output(
        {
            "outputs": {"chart": chart()},
            "checks": [{"label": "candidate", "status": "failed"}],
            "stdout": "",
        }
    )
    # Test provenance with a mock broker result, not a numerical/host execution fallback.
    tools.python_runner = SimpleNamespace(execute=lambda args: output)
    result = tools.execute("run_python", {"code": "trusted mock payload"})
    row = python_services.db.one(
        "SELECT * FROM scientific_results WHERE id=?", (result["result_id"],)
    )
    assert (
        row["tool"] == "run_python"
        and hashlib.sha256(row["output"].encode()).hexdigest() == row["output_sha256"]
    )
    answer, _ = tools.answer(
        {"blocks": [{"type": "graph", "result_id": result["result_id"]}]}
    )
    assert answer.blocks[0].result["output"]["chart"]["series"][0]["y"][-1] == 4
    assert any(b.type == "verification" for b in answer.blocks) and answer.warnings
    with pytest.raises(ValueError):
        Tools(python_services, tools.user, tools.chat).answer(
            {"blocks": [{"type": "graph", "result_id": result["result_id"]}]}
        )
    with pytest.raises(ValueError):
        tools.answer(
            {
                "blocks": [
                    {"type": "graph", "result_id": result["result_id"], "result": {}}
                ]
            }
        )
    tools.run_id = "not-an-active-run"
    assert (
        tools.execute("run_python", {"code": "pass"})["error"]
        == "SCIENTIFIC_RUN_NO_LONGER_ACTIVE"
    )
    tools.run_id = None
    tools.python_runner = SimpleNamespace(
        execute=lambda args: {"error": "SCIENTIFIC_TIMEOUT"}
    )
    before = len(python_services.db.rows("SELECT * FROM scientific_results"))
    assert "error" in tools.execute("run_python", {"code": "pass"})
    assert len(python_services.db.rows("SELECT * FROM scientific_results")) == before


def test_deployment_socket_and_network_ownership():
    import yaml

    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text())
    assert compose["networks"]["sandbox_net"]["internal"] is True
    for service in ("api", "worker"):
        volumes = compose["services"][service]["volumes"]
        assert all("docker.sock" not in v for v in volumes)
        assert "python_auth:/run/masar-sandbox:ro" in volumes
    assert "ports" not in compose["services"]["python-sandbox"]
    runtime = (root / "deploy/python-sandbox/runtime.Dockerfile").read_text()
    assert "COPY bac/ bac/" not in runtime and "/sandbox/child.py" in runtime


docker_only = pytest.mark.skipif(
    os.getenv("MASAR_PYTHON_DOCKER_TESTS") != "1",
    reason="Requires explicitly enabled real Docker isolation; no host fallback",
)


@docker_only
def test_docker_full_libraries_python_and_computed_graph():
    code = """import sympy as sp
import numpy as np
from scipy.integrate import quad
from pint import UnitRegistry
x=sp.symbols("x", positive=True)
f=sp.log(x)+x**3
primitive=sp.integrate(f,x)
check("primitive derivative", bool(sp.simplify(sp.diff(primitive,x)-f)==0), "x>0")
check("sin(x)/x limit", bool(sp.limit(sp.sin(x)/x,x,0)==1))
value,error=quad(lambda t:t*t,0,1)
check("numerical integral", abs(value-1/3)<1e-10, "absolute tolerance 1e-10")
u=UnitRegistry()
emit("speed", (36*u.kilometer/u.hour).to(u.meter/u.second).magnitude)
xs=np.linspace(-2,2,41)
ys=xs**2
emit("chart", {"title":"x²","x_label":"x","y_label":"f(x)","kind":"line","series":[{"label":"x²","x":xs.tolist(),"y":ys.tolist()}]})"""
    output = broker.execute(request(code))
    assert "error" not in output, output
    checked = validate_output(output)
    assert checked["outputs"]["speed"] == 10
    assert checked["chart"]["series"][0]["y"][-1] == 4
    assert all(c["status"] == "passed" for c in checked["checks"])


@docker_only
def test_docker_no_network_no_host_files_no_secrets_read_only_and_temporary_files():
    code = """import os, socket
check("platform files unavailable", not os.path.exists("/app/data"))
check("docker socket unavailable", not os.path.exists("/var/run/docker.sock"))
check("auth token unavailable", not os.path.exists("/run/masar-sandbox/token"))
check("provider secrets absent", not any("KEY" in k or "TOKEN" in k for k in os.environ))
try:
    open("/sandbox/modified", "w").write("bad")
    readonly = False
except OSError:
    readonly = True
check("read-only runtime", readonly)
try:
    socket.create_connection(("1.1.1.1",443), timeout=0.3)
    offline = False
except OSError:
    offline = True
check("network disabled", offline)
with open("/tmp/work", "w") as f:
    f.write("temporary")
check("temporary Python files allowed", open("/tmp/work").read() == "temporary")"""
    output = broker.execute(request(code))
    assert "error" not in output, output
    assert all(c["status"] == "passed" for c in output["checks"])
    second = broker.execute(
        request('import os\ncheck("no previous file", not os.path.exists("/tmp/work"))')
    )
    assert second["checks"][0]["status"] == "passed"


@docker_only
@pytest.mark.parametrize(
    "code,limits,errors",
    [
        (
            "while True: pass",
            {"timeout": 2, "cpu_seconds": 1},
            {"SCIENTIFIC_TIMEOUT", "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT"},
        ),
        ('import os\nos.write(1,b"x"*100000)', {}, {"SCIENTIFIC_OUTPUT_LIMIT"}),
        (
            "data=[bytearray(1024*1024) for _ in range(2048)]",
            {"memory_mb": 128},
            {
                "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR",
                "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT",
            },
        ),
        (
            'import subprocess,time\nsubprocess.Popen(["python","-c","import time; time.sleep(60)"])\ntime.sleep(60)',
            {"timeout": 2, "cpu_seconds": 1},
            {"SCIENTIFIC_TIMEOUT"},
        ),
    ],
)
def test_docker_resource_caps_and_grandchild_cleanup(code, limits, errors):
    output = broker.execute(request(code, **limits))
    assert output.get("error") in errors, output
    active = subprocess.check_output(
        ["docker", "ps", "-q", "--filter", "name=masar-python-"], text=True
    )
    assert active.strip() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", [False, True])
async def test_agent_uses_python_and_rejects_retired_calls(
    python_services, monkeypatch, retired
):
    from bac.agent.engine import AgentEngine
    from bac.core.db import uid, js

    tools = tools_fixture(python_services)
    cfg = uid("cfg")
    python_services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "agent",
            js({"base_url": "https://example.org/v1", "model": "fake"}),
            python_services.vault.encrypt("fake"),
            time.time(),
        ),
    )
    python_services.db.execute(
        "INSERT OR REPLACE INTO active_models VALUES(?,?)", ("agent", cfg)
    )
    monkeypatch.setattr(
        PythonRunner,
        "execute",
        lambda self, args: validate_output(
            {
                "outputs": {"actual": 4},
                "checks": [{"label": "proposed equality", "status": "failed"}],
                "stdout": "",
            }
        ),
    )

    class Scripted:
        step = 0

        async def stream(self, messages, definitions):
            self.step += 1
            names = {d["function"]["name"] for d in definitions}
            assert "run_python" in names and "calculate" not in names
            if self.step == 1:
                name = "calculate" if retired else "run_python"
                args = (
                    {"expression": "2+2"}
                    if retired
                    else {
                        "code": 'emit("actual",2+2)\ncheck("proposed equality",2+2==5)'
                    }
                )
            else:
                last = json.loads(messages[-1]["content"])
                if retired:
                    assert "error" in last and "result_id" not in last
                    args = {
                        "response_kind": "clarification",
                        "blocks": [
                            {"type": "text", "text": "ما النتيجة التي تريد مراجعتها؟"}
                        ],
                    }
                else:
                    args = {
                        "response_kind": "calculation",
                        "blocks": [
                            {
                                "type": "text",
                                "text": "الصحيح هو أربعة؛ النتيجة المقترحة غير صحيحة.",
                            },
                            {"type": "verification", "result_id": last["result_id"]},
                        ],
                    }
                name = "render_answer"
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": str(self.step),
                            "type": "function",
                            "function": {"name": name, "arguments": js(args)},
                        }
                    ],
                },
            }

    python_services.chat_factory = lambda cfg, key: Scripted()
    engine = AgentEngine(python_services)
    run_id = engine.enqueue(tools.chat, tools.user, "تحقق من 2+2=5")
    await engine.process(engine.claim())
    run = python_services.db.one(
        "SELECT status,error FROM agent_runs WHERE id=?", (run_id,)
    )
    assert run["status"] == "COMPLETED", run
    rows = python_services.db.rows(
        "SELECT * FROM scientific_results WHERE run_id=?", (run_id,)
    )
    assert len(rows) == (0 if retired else 1)
    if not retired:
        assert rows[0]["tool"] == "run_python"
