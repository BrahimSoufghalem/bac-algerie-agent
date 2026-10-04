"""Offline network/queue contracts. No live calls, source corpus or real secrets."""

import asyncio
import json
from dataclasses import replace
import subprocess
import os
import sys
import time
import httpx
import pytest
from bac.ops.extraction import diagnose_extraction
from bac.vendor.bookforge.vision import provider as vision
from bac.vendor.bookforge.workers.queue import Queue
from tests.test_page_reextraction import seeded, drain, Vision


def provider(s, handler, timeout=1):
    settings = replace(s.extraction_settings, request_timeout=timeout)
    s.store.write("fixture.png", b"Controlled fixture image")
    image = s.store.path("fixture.png")
    return vision.OpenAICompatibleProvider(
        "PRIVATE-FIXTURE-KEY",
        "https://fixture.invalid/v1",
        "fixture",
        settings,
        transport=httpx.MockTransport(handler),
    ), image


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code",
    [
        (httpx.ConnectTimeout, "NETWORK_CONNECT_TIMEOUT"),
        (httpx.ReadTimeout, "NETWORK_READ_TIMEOUT"),
        (httpx.WriteTimeout, "NETWORK_WRITE_TIMEOUT"),
        (httpx.PoolTimeout, "NETWORK_POOL_TIMEOUT"),
        (httpx.ConnectError, "NETWORK_CONNECT_ERROR"),
        (httpx.ReadError, "NETWORK_READ_ERROR"),
        (httpx.WriteError, "NETWORK_WRITE_ERROR"),
        (httpx.RemoteProtocolError, "NETWORK_PROTOCOL_ERROR"),
    ],
)
async def test_network_errors_are_specific_redacted_single_attempt(
    services, kind, code
):
    calls = []

    def handler(request):
        calls.append(request.method)
        raise kind("PRIVATE ERROR BODY KEY URL", request=request)

    p, image = provider(services, handler)
    with pytest.raises(vision.ProviderError) as exc:
        await p.extract(image, 1, 100, 100)
    assert exc.value.code == code and exc.value.retryable
    assert "PRIVATE" not in str(exc.value) and calls == ["POST"]


class Trickling(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        for _ in range(100):
            await asyncio.sleep(0.01)
            yield b" "

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_total_deadline_closes_slow_response_even_if_it_keeps_sending_bytes(
    services,
):
    body = Trickling()
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, stream=body)

    p, image = provider(services, handler, 0.07)
    start = time.monotonic()
    with pytest.raises(vision.ProviderError) as exc:
        await p.extract(image, 1, 100, 100)
    assert exc.value.code == "NETWORK_REQUEST_DEADLINE"
    assert time.monotonic() - start < 0.8 and body.closed and calls == ["POST"]


@pytest.mark.asyncio
async def test_dns_inside_total_deadline_and_redacted_dns_failure(
    services, monkeypatch
):
    p, image = provider(services, lambda request: httpx.Response(200), 0.07)
    p.transport = None

    async def stuck(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(vision, "validate_base_url", stuck)
    with pytest.raises(vision.ProviderError) as exc:
        await p.extract(image, 1, 100, 100)
    assert exc.value.code == "NETWORK_REQUEST_DEADLINE"

    async def failed(*args):
        raise vision.ModelDNSFailure("PRIVATE HOST/KEY")

    monkeypatch.setattr(vision, "validate_base_url", failed)
    with pytest.raises(vision.ProviderError) as exc:
        await p.extract(image, 1, 100, 100)
    assert exc.value.code == "NETWORK_DNS_ERROR" and "PRIVATE" not in str(exc.value)


@pytest.mark.asyncio
async def test_connect_write_pool_timeouts_do_not_expand_with_large_read_budget(
    services,
):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "pdf_page": 1,
                                    "width": 100,
                                    "height": 100,
                                    "elements": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    p, image = provider(services, handler, 600)
    doc, _ = await p.extract(image, 1, 100, 100)
    assert doc.pdf_page == 1
    assert seen == [{"connect": 30, "read": 600, "write": 60, "pool": 10}]


@pytest.mark.asyncio
async def test_restored_worker_cap_downshift_fences_old_lease_and_preserves_cached_work(
    services,
):
    s = services
    lib, r, owner, calls = await seeded(s, published=False)
    bid = lib.version(r["version_id"])["bookforge_id"]
    s.extraction_db.execute(
        "UPDATE jobs SET status='PENDING' WHERE kind='page' AND book_id=?", (bid,)
    )
    s.extraction_db.execute("UPDATE pages SET status='PENDING' WHERE book_id=?", (bid,))
    s.extraction_db.execute(
        "DELETE FROM jobs WHERE kind='structure' AND book_id=?", (bid,)
    )
    s.extraction_db.execute("UPDATE books SET status='PROCESSING' WHERE id=?", (bid,))
    s.extraction_db.execute("UPDATE settings SET workers=8 WHERE id=1")
    settings = replace(s.extraction_settings, max_workers=1, min_request_interval=0)
    q1, q2 = Queue(s.extraction_db, settings), Queue(s.extraction_db, settings)
    old = q1.claim()
    assert old and old["raw_file"]
    assert q2.claim() is None  # Global cap is one, including across engines.
    s.extraction_db.execute(
        "UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, old["id"])
    )
    fresh = q2.claim()
    assert fresh and fresh["lease_token"] != old["lease_token"]
    assert not q1.heartbeat(old)
    s.extraction_engine.settings = settings
    s.extraction_engine.queue.settings = settings
    s.extraction_queue.settings = settings
    await s.extraction_engine.process(fresh)
    await drain(s)
    assert (
        len(calls) == 3
    )  # Recover cached response; do not resend completed provider work.
    assert all(p["status"] == "SUCCESS" for p in lib.version(r["version_id"])["pages"])


@pytest.mark.asyncio
async def test_engine_native_custom_request_deadline_releases_slot_and_can_retry(
    services,
):
    s = services
    lib, r, owner, calls = await seeded(s, published=False)
    queued = lib.reextract_page(r["version_id"], 2, None, owner)

    class Stuck:
        cancelled = False

        async def extract(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                self.cancelled = True

    stuck = Stuck()
    s.extraction_engine.provider_factory = lambda cfg, key: stuck
    settings = replace(s.extraction_engine.settings, request_timeout=0.07)
    s.extraction_engine.settings = settings
    s.extraction_engine.queue.settings = settings
    job = s.extraction_queue.claim()
    await s.extraction_engine.process(job)
    current = s.extraction_db.one("SELECT * FROM jobs WHERE id=?", (queued["job_id"],))
    assert current["status"] == "PENDING" and current["lease_token"] is None
    assert current["last_error"] == "NETWORK_REQUEST_DEADLINE" and stuck.cancelled
    s.extraction_db.execute(
        "UPDATE jobs SET available_at=0 WHERE id=?", (queued["job_id"],)
    )
    s.extraction_engine.provider_factory = lambda cfg, key: Vision(
        calls, cfg["model"], key
    )
    await drain(s)
    assert lib.version(r["version_id"])["pages"][1]["status"] == "SUCCESS"
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_safe_diagnostic_zero_calls_read_only_stage_and_worker_cap(services):
    s = services
    lib, r, owner, calls = await seeded(s, published=False)
    lib.reextract_page(r["version_id"], 2, None, owner)
    s.extraction_db.execute("UPDATE settings SET workers=8 WHERE id=1")
    job = s.extraction_queue.claim()
    s.extraction_db.execute(
        "UPDATE jobs SET last_error='NETWORK_READ_TIMEOUT' WHERE id=?", (job["id"],)
    )
    s.extraction_db.event(
        "EXTRACTION_STAGE:provider_request", job["book_id"], job["target_id"]
    )
    s.extraction_db.execute(
        "INSERT INTO engine_heartbeats VALUES(?,?)", ("PRIVATE WORKER", time.time())
    )
    s.extraction_db.execute(
        "UPDATE jobs SET last_error=? WHERE kind='structure'", ("PRIVATE RAW ERROR",)
    )
    before = s.extraction_db.rows("SELECT * FROM jobs")
    report = diagnose_extraction(s.store.root, 1, 600, 240)
    assert report["effective_workers"] == 1 and report["configured_workers"] == 8
    assert report["running_jobs"][0]["stage"] == "provider_request"
    assert report["running_jobs"][0]["stage_elapsed_seconds"] >= 0
    assert report["last_error_task_counts"]["NETWORK_READ_TIMEOUT"] == 1
    assert report["processing_run_uses_current_config"] == [True]
    text = json.dumps(report)
    for private in [
        owner,
        r["document_id"],
        r["version_id"],
        job["id"],
        job["book_id"],
        job["target_id"],
        "PRIVATE",
        "example.org",
        "PRIVATE-TEST-KEY",
    ]:
        assert private not in text
    assert report["provider_requests"] == report["database_changes"] == 0
    assert s.extraction_db.rows("SELECT * FROM jobs") == before and len(calls) == 3
    env = os.environ | {
        "DATA_DIR": str(s.store.root),
        "EXTRACTION_WORKERS": "1",
        "REQUEST_TIMEOUT": "600",
    }
    done = subprocess.run(
        [sys.executable, "-m", "bac.cli", "diagnose-extraction"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert done.returncode == 0
    cli = json.loads(done.stdout)
    assert cli["effective_workers"] == 1 and cli["request_deadline_seconds"] == 600
    assert "PRIVATE" not in done.stdout


def test_missing_diagnostic_does_not_create_state_files(tmp_path):
    assert diagnose_extraction(tmp_path, 2, 180, 240)["found"] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_missing_lease_recovered_but_live_lease_never_reset(services):
    s = services
    lib, r, owner, calls = await seeded(s, published=False)
    bid = lib.version(r["version_id"])["bookforge_id"]
    s.extraction_db.execute(
        "UPDATE jobs SET status='PENDING' WHERE kind='page' AND book_id=?", (bid,)
    )
    s.extraction_db.execute("UPDATE settings SET workers=2 WHERE id=1")
    first = s.extraction_queue.claim()
    second = s.extraction_queue.claim()
    s.extraction_db.execute(
        "UPDATE jobs SET lease_until=NULL WHERE id=?", (first["id"],)
    )
    fresh = s.extraction_queue.claim()
    assert fresh["id"] == first["id"] and fresh["lease_token"] != first["lease_token"]
    assert not s.extraction_queue.heartbeat(first)
    assert s.extraction_queue.heartbeat(second)
    assert fresh["raw_file"] == first["raw_file"]
    assert len(calls) == 3


def test_total_request_deadline_must_be_positive_and_finite(services):
    for timeout in [float("inf"), float("nan"), 0, -1]:
        with pytest.raises(ValueError):
            replace(services.extraction_settings, request_timeout=timeout)


@pytest.mark.asyncio
async def test_native_dns_failure_is_not_misclassified_as_bad_extraction(
    services, monkeypatch
):
    from bac.agent.anthropic_vision import AnthropicVision
    from bac.agent.anthropic import AnthropicChat

    async def failed(self, *args):
        raise vision.ModelDNSFailure("PRIVATE HOST ERROR")
        yield  # Preserve async-generator interface without a network call.

    monkeypatch.setattr(AnthropicChat, "_stream", failed)
    p = AnthropicVision(
        {
            "base_url": "https://fixture.invalid/v1",
            "model": "fixture",
            "protocol": "anthropic",
        },
        "PRIVATE-KEY",
        services.extraction_settings,
    )
    services.store.write("fixture.png", b"Controlled fixture image")
    with pytest.raises(vision.ProviderError) as exc:
        await p.extract(services.store.path("fixture.png"), 1, 100, 100)
    assert exc.value.code == "NETWORK_DNS_ERROR" and exc.value.retryable
    assert "PRIVATE" not in str(exc.value)
