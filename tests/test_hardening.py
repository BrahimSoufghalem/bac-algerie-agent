import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from bac.agent.engine import AgentEngine
from bac.agent.tools import Tools
from bac.agent.models import TableBlock
from bac.core.db import DB
from tests.test_agent import chat_and_config
from tests.test_library import seeded, process_and_publish


def test_transaction_safe_claim_and_no_paid_restart(services):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    run = engine.enqueue(chat, user, "Question")
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: engine.claim(), range(8)))
    job = next(x for x in claims if x)
    assert len([x for x in claims if x]) == 1
    services.db.execute(
        "UPDATE agent_runs SET lease_until=? WHERE id=?", (time.time() - 1, run)
    )
    assert engine.claim() is None
    assert services.db.one("SELECT status FROM agent_runs")["status"] == "INTERRUPTED"
    with pytest.raises(RuntimeError, match="LEASE_LOST"):
        engine.emit(job, "delta", {"text": "stale worker"})


def test_future_db_version_rejected(services):
    services.db.execute("INSERT INTO migrations VALUES(999,?)", (time.time(),))
    with pytest.raises(RuntimeError, match="newer"):
        DB(services.db.path)


def test_table_shape_limits():
    with pytest.raises(ValueError):
        TableBlock(headers=["a"], rows=[["1", "2"]])
    with pytest.raises(ValueError):
        TableBlock(headers=["a"], rows=[["x" * 4001]])


@pytest.mark.asyncio
async def test_snapshot_unchanged_after_raw_source_reprocessing_and_revocation(
    services,
):
    lib, r, owner = seeded(services)
    doc = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(doc["id"], "lesson")[0]["id"]
    before = lib.node(node)["content"]
    raw = services.extraction_db.one(
        "SELECT content_file FROM nodes WHERE kind='lesson'"
    )
    services.extraction_store.write(raw["content_file"], b"changed raw content")
    assert lib.node(node)["content"] == before
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    payload = tools.load(node)
    asset = payload["assets"][0]["id"]
    with pytest.raises(ValueError, match="not actually loaded"):
        tools.answer(
            {"blocks": [{"type": "text", "text": "x"}], "source_ids": ["invented"]}
        )
    services.db.execute(
        "UPDATE documents SET status='ARCHIVED' WHERE id=?", (doc["id"],)
    )
    with pytest.raises(ValueError, match="revoked"):
        tools.answer({"blocks": [{"type": "image", "asset_id": asset}]})
