"""Ephemeral server-owned assessment aliases and exact original body spans.

Only the isolated assessment uses aliases. Persistent IDs, router, final citations,
permissions and delivery ledger remain unchanged. No content is summarized/dropped.
"""

import re
import hashlib


def body_spans(body, target=1400):
    """Group complete paragraphs; retain every original character exactly once."""
    begin = 0
    for match in re.finditer(r"\n\s*\n", body):
        end = match.end()
        if end - begin >= target:
            yield begin, end
            begin = end
    if begin < len(body):
        yield begin, len(body)


def prepare_body_choices(tools):
    tools.assessment_aliases = {}
    tools.assessment_spans = {}
    tools.assessment_body_hashes = {}
    bodies = {}
    for sid, data in tools.source_evidence.items():
        if sid not in tools.sources or not data.get("body"):
            continue
        alias = f"R{len(tools.assessment_aliases) + 1}"
        tools.assessment_aliases[alias] = sid
        body = data["body"]
        tools.assessment_body_hashes[sid] = hashlib.sha256(body.encode()).hexdigest()
        marked = []
        for number, (start, end) in enumerate(body_spans(body), 1):
            eid = f"{alias}:E{number}"
            tools.assessment_spans[eid] = {"source_id": sid, "start": start, "end": end}
            marked.append(f"[SERVER PASSAGE {eid}]\n" + body[start:end])
        bodies[sid] = "".join(marked)
    return {
        "actual_source_bodies": bodies,
        "reference_choices": tools.assessment_aliases.copy(),
    }


def resolve_evidence(decision, tools):
    """Resolve EXACT allowlisted aliases/spans; no fuzzy ID correction or guessed reads."""
    aliases = tools.assessment_aliases
    if any(a not in aliases for a in decision.source_ids):
        return decision, ["UNKNOWN_ASSESSMENT_SOURCE_CHOICE"]
    records, reasons = [], set()
    for item in decision.coverage:
        sid = aliases.get(item.source_id)
        span = tools.assessment_spans.get(item.evidence_id)
        if sid is None or span is None:
            reasons.add("UNKNOWN_ASSESSMENT_EVIDENCE_CHOICE")
            continue
        if span["source_id"] != sid:
            reasons.add("EVIDENCE_SOURCE_MISMATCH")
            continue
        body = tools.source_evidence.get(sid, {}).get("body", "")
        if hashlib.sha256(
            body.encode()
        ).hexdigest() != tools.assessment_body_hashes.get(sid):
            reasons.add("ASSESSMENT_BODY_CHANGED")
            continue
        quote = body[span["start"] : span["end"]]
        if len(quote.strip()) < 12:
            reasons.add("EMPTY_OR_TRIVIAL_BODY_EVIDENCE")
            continue
        # Do not trust a model-supplied legacy quote on a live passage contract.
        if item.quote is not None:
            reasons.add("LIVE_QUOTE_NOT_SERVER_EVIDENCE")
            continue
        records.append(item.model_copy(update={"source_id": sid, "quote": quote}))
    return decision.model_copy(
        update={
            "source_ids": [aliases[a] for a in decision.source_ids],
            "coverage": records,
        }
    ), sorted(reasons)
