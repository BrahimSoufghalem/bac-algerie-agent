"""Subject-neutral task identity and student provenance. Never infer mastery/coverage."""

import re
from bac.agent.grounding import normalized
from bac.agent.answer_quality import explicit_plot


def history_requested(question):
    text = normalized(question)
    return bool(
        re.search(
            r"(?:لخص|راجع|اذكر).*?(?:اخطائي|اخطاء|محادثتنا|المحادثة)|summari[sz]e.*(?:conversation|mistakes)|resume.*(?:erreurs|conversation)",
            text,
        )
        and re.search(r"اخطائي|محادث|انا|my |our |conversation|mes |notre ", text)
    )


def history_only(question):
    return history_requested(question) and not re.search(
        r"تمرين|اشرح|احسب|حل|درس جديد|exercise|explain|calculate|solve|exercice|explique",
        normalized(question),
    )


def task_kind(question):
    text = normalized(question)
    if history_requested(question):
        return "history_summary" if history_only(question) else "mixed_history"
    if explicit_plot(question):
        return "plot"
    if re.search(r"لم افهم|ما فهمتش|مفهمتش|الخطوة|النقطة|follow.up|second step", text):
        return "follow_up"
    if re.search(r"احسب|حساب|calculate|compute|calculer|اشتق|مشتقة", text):
        return "calculation"
    return "explanation"


def task_state(tools, current_id=None, history=None):
    # Only student messages supplied by the authenticated server are givens/history.
    # Reference examples NEVER appear in this namespace.
    prior = [
        h for h in (history or []) if h["role"] == "user" and h["id"] != current_id
    ]
    return {
        "current_request_message_id": current_id,
        "goal_kind": task_kind(tools.question),
        "current_request": tools.question,
        "student_message_ids": [current_id] if current_id else [],
        "recent_student_givens": [
            {
                "message_id": h["id"],
                "quote": h["content"],
                "historical_not_pending": True,
            }
            for h in reversed(prior[:3])
        ],
        "source_examples_are_not_student_history": True,
        "current_corrections_override_history": True,
    }
