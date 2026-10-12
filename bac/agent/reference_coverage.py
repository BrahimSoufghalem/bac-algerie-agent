"""Conservative negative checks + actual-body evidence; not a semantic correctness oracle.

Metadata can reject obvious mismatches, never certify sufficiency. Unknown wording
still requires the tutor's structured support/conditions assessment. No source/student
text is written to the audit log.
"""

import re
from bac.agent.grounding import normalized

PATTERNS = {
    "probability": r"احتمال|بايز|\b(?:الحدث|حدث|الحادث|حادث)\b|probabil|bayes|conditional|intersection",
    "sequences": r"متتالي|متجاورت|حد الثاني|الحد الثاني|sequence|suite|recurrence",
    "derivatives": r"مشتق|اشتقاق|تغيرات|قيم حدية|قيمة عظمي|قيمة صغري|derivat|derivee|differentiat",
    "logarithms": r"لوغاريتم|لوغاريثم|logarith|نيبيري|\bln\b",
    "integrals": r"تكامل|دالة اصلية|دوال اصلية|integral|primitive",
    "limits": r"نهايات|نهاية دالة|مقارب|مجال|limit|continuity|استمراري",
}


def topics(text):
    plain = normalized(text)
    found = {k for k, p in PATTERNS.items() if re.search(p, plain)}
    if re.search(r"\bP\s*\(.*?[AB]", text, re.I):
        found.add("probability")
    if re.search(r"\bu(?:_\{?(?:n|[0-9])|\(?n|[0-9])", text, re.I):
        found.add("sequences")
    if re.search(r"[fg]\s*(?:'|\^\{?\\prime)|d[fy]\s*/\s*dx", text):
        found.add("derivatives")
    return found


def current_topics(tools):
    explicit = topics(tools.question)
    if explicit:
        return explicit
    # Only resolve referential follow-ups, not an unspecified NEW topic from all history.
    if re.search(
        r"لم افهم|ما فهمتش|ما فهمتهاش|الخطوة|النقطة|نفس|احتفظ|بدل|الشرطي|اكمل|الحسابين|الدالة|مشتقة g|ارسم g|لخص الاخطاء|follow.up|second step",
        normalized(tools.question),
    ):
        for item in reversed(tools.router_history):
            if item.get("role") == "user" and (
                found := topics(item.get("content", ""))
            ):
                return found
    return set()


def in_subject_math_request(tools):
    """Narrow recovery hint, NEVER sufficiency or answer authorization.

    Fixed product scope is independent of currently loaded bodies. Foreign subject
    and clearly non-study intent remain with the model's refusal policy.
    """
    if tools.study_scope.subject != "mathematics":
        return False
    text = normalized(tools.question)
    if re.search(
        r"فيزياء|كهرباء|قذف|حرب باردة|تاريخ|قصيدة|اغنية|اختراق|physics|poem|song|hack",
        text,
    ):
        return False
    if current_topics(tools):
        return True
    math_expression = re.search(
        r"\b[fg]\s*\(\s*x\s*\)|\bu(?:_\{?n|\(?n|[0-9])", tools.question, re.I
    )
    return bool(
        math_expression
        and re.search(r"احسب|ادرس|ارسم|صحح|تحقق|حدد|calculate|plot|differentiat", text)
    )


def canonical_quote(value):
    # Compatibility only for old recorded quotations. One duplicated TeX escape
    # before a closed command list, not arbitrary decoding or matrix row breaks.
    return re.sub(
        r"(?<!\\)\\{2}(?=(?:frac|cap|cup|overline|infty|leq|geq|times|cdot|ln|prime|subset|emptyset|mathbb|sqrt)\b)",
        r"\\",
        flat(value or ""),
    )


def flat(value):
    return " ".join(value.split())


def requirements(tools):
    required = current_topics(tools)
    text = normalized(tools.question)
    obligations = []
    if (
        "sequences" in required
        and re.search(r"متزايد|متناقص|رتيب|monoton|increas|decreas", text)
        and re.search(r"تقارب|نهاية|converg|limit", text)
    ):
        obligations.append("monotone_convergence_requires_bound")
    return {"topics": sorted(required), "conditions": obligations}


def coverage_reasons(decision, tools):
    """Return reason codes only. ID validity is checked separately by the caller."""
    reasons = set()
    needs = requirements(tools)
    required = set(needs["topics"])
    evidence = getattr(tools, "source_evidence", {})
    if decision.gaps:
        reasons.add("REPORTED_SUPPORT_GAP")
    if not decision.coverage:
        reasons.add("MISSING_BODY_SUPPORT")
    supported_ids = set()
    goal_topics = set()
    for support in decision.coverage:
        data = evidence.get(support.source_id, {})
        body = data.get("body", "")
        if support.source_id not in decision.source_ids:
            reasons.add("SUPPORT_OUTSIDE_SELECTED_SET")
            continue
        if (
            not body
            or not support.quote
            or canonical_quote(support.quote) not in canonical_quote(body)
        ):
            reasons.add("QUOTE_NOT_IN_ACTUAL_BODY")
            continue
        supported_ids.add(support.source_id)
        if support.role == "current_goal":
            actual_topics = topics(body)
            local_topics = topics(data.get("local_metadata", ""))
            goal_topics.update(actual_topics & topics(support.quote))
            # Local metadata/hierarchy identify obvious errors but cannot grant evidence.
            if required and not required & topics(support.quote):
                reasons.add("CURRENT_GOAL_QUOTE_TOPIC_MISMATCH")
            if required and not required & actual_topics:
                reasons.add("CURRENT_GOAL_BODY_TOPIC_MISMATCH")
            if (
                required
                and local_topics
                and not required & local_topics
                and not required & topics(support.quote)
            ):
                reasons.add("LOCAL_METADATA_TOPIC_MISMATCH")
    if set(decision.source_ids) - supported_ids:
        reasons.add("SELECTED_SOURCE_WITHOUT_BODY_SUPPORT")
    if not any(s.role == "current_goal" for s in decision.coverage):
        reasons.add("MISSING_CURRENT_GOAL_SUPPORT")
    if required - goal_topics:
        reasons.add("CURRENT_GOAL_NOT_SUPPORTED")
    if "monotone_convergence_requires_bound" in needs["conditions"]:
        # The bound is an indispensable theorem hypothesis; monotonicity alone is insufficient.
        quotes = " ".join(s.quote or "" for s in decision.coverage)
        if not re.search(r"محدود|محصور|major|minor|bounded|borne", normalized(quotes)):
            reasons.add("MISSING_CONVERGENCE_BOUND_CONDITION")
    return sorted(reasons)


def reject_support(tools, reasons):
    """Owner-only audit: enum codes/IDs, no quotes, questions or internal reasoning."""
    tools.coverage_validated = False
    tools.covered_sources.clear()
    tools.references_ready = False
    tools.s.db.audit(
        tools.user["id"],
        "context_support_rejected",
        tools.run_id,
        {"reason_codes": sorted(set(reasons)), "source_ids": sorted(tools.sources)},
    )
