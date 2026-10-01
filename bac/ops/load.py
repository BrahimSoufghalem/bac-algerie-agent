"""Deterministic SQLite/ASGI stress probe, isolated temp data; NO model network calls."""

import argparse, asyncio, json, statistics, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import httpx
from bac.core.services import Services
from bac.core.config import Settings
from bac.core.auth import create_user, new_session
from bac.core.db import uid, js
from bac.agent.engine import AgentEngine


async def benchmark(requests=200, concurrency=8, runs=40):
    with tempfile.TemporaryDirectory(prefix="masar-load-") as root:
        from bac.api.main import create_app

        s = Services(
            replace(Settings(), data_dir=Path(root), agent_workers=concurrency)
        )
        try:
            cfg = uid("cfg")
            s.db.execute(
                "INSERT INTO model_configs VALUES(?,?,?,?,?)",
                (
                    cfg,
                    "agent",
                    js(
                        {
                            "base_url": "https://example.invalid/v1",
                            "model": "load-no-network",
                        }
                    ),
                    s.vault.encrypt("fixture"),
                    time.time(),
                ),
            )
            s.db.execute("INSERT INTO active_models VALUES(?,?)", ("agent", cfg))
            jobs = []
            sessions = []
            for i in range(runs):
                u = create_user(
                    s.db, f"load{i}@example.invalid", "Load-test-password-123", "Load"
                )
                chat = uid("chat")
                s.db.execute(
                    "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (chat, u, "Load", time.time(), time.time()),
                )
                jobs.append(
                    AgentEngine(s).enqueue(
                        chat,
                        s.db.one("SELECT * FROM users WHERE id=?", (u,)),
                        "Local load probe",
                    )
                )
                sessions.append(new_session(s.db, u, s.settings)[0])
            app = create_app(s)
            semaphore = asyncio.Semaphore(concurrency)
            timings = []
            statuses = []

            async def request(i):
                async with semaphore:
                    started = time.perf_counter()
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app), base_url="http://load.local"
                    ) as c:
                        response = await c.get(
                            "/api/conversations",
                            headers={"Cookie": "bac_session=" + sessions[i % runs]},
                        )
                    statuses.append(response.status_code)
                    timings.append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            await asyncio.gather(*(request(i) for i in range(requests)))
            seconds = time.perf_counter() - started
            # Race claims/fenced completions, no inference: assess durable queue uniqueness.
            claimed = []

            def worker():
                engine = AgentEngine(s)
                while True:
                    job = engine.claim()
                    if job is None:
                        if s.db.one("SELECT 1 FROM agent_runs WHERE status='QUEUED'"):
                            time.sleep(0.002)
                            continue
                        return
                    claimed.append(job["id"])
                    s.db.execute(
                        "UPDATE agent_runs SET status='COMPLETED',lease_token=NULL,lease_until=NULL,finished_at=? WHERE id=? AND lease_token=?",
                        (time.time(), job["id"], job["lease_token"]),
                    )

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(lambda _: worker(), range(concurrency)))
            sorted_ms = sorted(timings)
            result = {
                "mode": "isolated SQLite + in-process ASGI; no provider/network/proxy",
                "requests": requests,
                "concurrency": concurrency,
                "elapsed_seconds": round(seconds, 3),
                "requests_per_second": round(requests / seconds, 2),
                "p50_ms": round(statistics.median(timings), 2),
                "p95_ms": round(
                    sorted_ms[min(len(sorted_ms) - 1, int(len(sorted_ms) * 0.95))], 2
                ),
                "http_errors": sum(x != 200 for x in statuses),
                "queue_jobs": runs,
                "queue_claims": len(claimed),
                "duplicate_claims": len(claimed) - len(set(claimed)),
                "missing_jobs": len(set(jobs) - set(claimed)),
                "paid_calls": 0,
            }
            if (
                result["http_errors"]
                or result["duplicate_claims"]
                or result["missing_jobs"]
            ):
                raise RuntimeError("Load probe failed: " + json.dumps(result))
            return result
        finally:
            s.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--requests", type=int, default=200)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--runs", type=int, default=40)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    if not (
        10 <= a.requests <= 10000 and 1 <= a.concurrency <= 16 and 1 <= a.runs <= 200
    ):
        p.error("Probe bounds: requests10–10000, concurrency1–16, runs1–200")
    result = asyncio.run(benchmark(a.requests, a.concurrency, a.runs))
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
