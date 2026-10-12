"""Bounded dialogue and publication-scoped read memory; no paid summarizer."""

import json

from bac.core.db import js
from bac.agent.provider import ModelError


def history_text(row):
    """Retain previous public equations/tables, never old computed result IDs."""
    text = row["content"]
    if row["role"] == "assistant":
        extras = []
        for block in json.loads(row.get("blocks") or "[]"):
            if block["type"] == "equation":
                extras.append("Equation: " + block["latex"])
            elif block["type"] == "table":
                extras.append(
                    "Table: " + js({"headers": block["headers"], "rows": block["rows"]})
                )
        if extras:
            text += "\n\n" + "\n".join(extras)
    return text


def recent_dialogue(rows, current_id, max_chars=6000, max_messages=4):
    """Newest whole prior exchanges in chronological order; current request separate."""
    selected = []
    used = 0
    for row in rows:
        if row["id"] == current_id:
            continue
        message = {"message_id": row["id"], "role": row["role"], "content": history_text(row)}
        size = len(js(message))
        if len(selected) >= max_messages or used + size > max_chars:
            break
        selected.append(message)
        used += size
    result = list(reversed(selected))
    # Do not leave an assistant reply without its earlier user question at a boundary.
    if result and result[0]["role"] == "assistant":
        result.pop(0)
    return result


def message_chars(message):
    """Text/tool context budget; image transport bytes have separate hard limits."""
    if isinstance(message.get("content"), list):
        view = message | {
            "content": [b for b in message["content"] if b.get("type") == "text"]
        }
        return len(js(view))
    return len(js(message))


def fit_history(messages, tools, limit):
    """Drop oldest whole historical turns, never current request, policy or references."""
    historical = list(getattr(tools, "history_messages", []))
    while sum(message_chars(m) for m in messages) > limit and historical:
        old = historical.pop(0)
        if old is getattr(tools, "current_message", None):
            break
        messages[:] = [m for m in messages if m is not old]
        # If a user question is evicted, evict its now-orphaned assistant reply too.
        if historical and historical[0]["role"] == "assistant":
            old = historical.pop(0)
            messages[:] = [m for m in messages if m is not old]
    if sum(message_chars(m) for m in messages) > limit:
        raise ModelError("CONTEXT_BUDGET_EXCEEDED")


def reusable_references(s, tools, mapping):
    """Persistent IDs/versions, remapped to this scoped catalogue's temporary aliases.

    Only full immutable book reads qualify. Parts are not complete lessons, and
    atomic bundles must be reverified because a separately linked solution can change.
    No source body is returned or credited by metadata alone.
    """
    by_id = {n["id"]: alias for alias, n in mapping.items()}
    reusable = {}
    rows = s.db.rows(
        "SELECT * FROM loaded_context WHERE conversation_id=? "
        "ORDER BY loaded_at DESC,node_id LIMIT 12",
        (tools.chat,),
    )
    for row in rows:
        alias = by_id.get(row["node_id"])
        if alias is None:
            continue  # Scoped catalogue already checks current publication/access.
        node = mapping[alias]
        if (
            row["version_id"] == node["version_id"]
            and row.get("scope", "full") == "full"
            and row.get("scope_id") in (None, node["id"])
            and node["kind"]
            not in {
                "book",
                "unit",
                "front_matter",
                "index",
                "exam",
                "exercise_collection",
            }
        ):
            reusable[alias] = {
                "id": alias,
                "title": node["title"],
                "kind": node["kind"],
                "active": bool(row.get("active", 1)),
                "delivered_in_current_context": node["id"] in tools.delivered_sources,
            }
    return reusable
