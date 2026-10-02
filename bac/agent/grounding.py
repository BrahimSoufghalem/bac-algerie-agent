"""Server-side evidence requirements, not a claim of semantic entailment."""

import re
import unicodedata


def normalized(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = value.translate(str.maketrans("أإآى", "اااي"))
    return " ".join(re.findall(r"[a-z\u0621-\u064a]+", value))


SOCIAL = {
    "hi",
    "hello",
    "hloo",
    "hey",
    "thanks",
    "thank you",
    "how are you",
    "bonjour",
    "salut",
    "merci",
    "اهلا",
    "اهلا مسار",
    "مرحبا",
    "مرحبا مسار",
    "السلام عليكم",
    "سلام",
    "سلام مسار",
    "كيف حالك",
    "كيف حالك مسار",
    "واش راك",
    "واش راك مسار",
    "شكرا",
    "شكرا مسار",
    "صباح الخير",
    "مساء الخير",
}
LESSON = re.compile(
    r"درس|فيزياء|قذف|شاقول|قانون|تعلم|"
    r"\blesson\b|\bexplain\b|\bphysics\b|\bcours\b|\bexplique"
)


def social_question(question):
    return len(question) <= 100 and normalized(question) in SOCIAL


def require_grounding(answer, tools):
    """Only called for an actual agent run; locators never grant source credit."""
    kind = answer.response_kind
    if kind in ("clarification", "refusal", "conversation"):
        if (
            len(answer.blocks) != 1
            or answer.blocks[0].type != "text"
            or len(answer.blocks[0].text) > 600
            or re.search(r"\$|\\[([]", answer.blocks[0].text)
            or answer.source_ids
            or answer.warnings
        ):
            raise ValueError(
                "Non-teaching replies must be one short plain-text block, without math, sources or extra warnings"
            )
        if kind == "conversation" and not social_question(tools.question):
            raise ValueError(
                "Conversation mode is only for a simple greeting/thanks, not teaching"
            )
        if kind == "clarification" and not re.search(r"[?؟]", answer.blocks[0].text):
            raise ValueError(
                "Clarification must ask for the missing topic, source passage or data"
            )
        return
    if kind == "calculation":
        if not tools.scientific:
            raise ValueError(
                "Calculation mode requires actual results computed in this run"
            )
        # A calculator route must not bypass the evidence gate for a lesson/follow-up.
        if not LESSON.search(normalized(tools.study_context)) and re.search(
            r"\d|جمع|طرح|ضرب|قسمة|احسب|حساب|تحقق|مثال|علمي|"
            r"\bcalculate\b|\bcompute\b|\bverify\b",
            tools.study_context.casefold(),
        ):
            return
    if not answer.source_ids or any(
        source_id not in tools.delivered_sources for source_id in answer.source_ids
    ):
        raise ValueError(
            "REFERENCE_READ_REQUIRED: Teaching requires relevant actually-read source_ids. "
            "Search/metadata/TOC snippets do not count. Read a matching full lesson/section/part/bundle "
            "or relevant private page. Reuse actual restored sources when relevant. If no relevant "
            "source is available, ask a short clarification instead of teaching from model memory. "
            "Do not automatically cite an unrelated previous topic."
        )
