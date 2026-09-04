"""Prompt templates for diversified domain generation."""

from __future__ import annotations

STRATEGY_GUIDANCE = {
    "brandable": "Invent distinctive pronounceable brand words; avoid generic keyword stuffing.",
    "semantic_compound": "Combine two concise topic-relevant concepts into natural compounds.",
    "short_technical": "Prefer compact technical names with clear product or tool associations.",
    "phonetic": "Favor smooth, easy-to-say names with simple spelling and strong recall.",
    "action_result": "Use names suggesting the user's action, outcome, speed, or benefit.",
    "abbreviation": "Create readable abbreviation-inspired names, not opaque random initials.",
}


def build_prompt(
    topic: str,
    tlds: list[str],
    count: int,
    min_len: int = 4,
    max_len: int = 15,
    strategy: str | None = None,
) -> str:
    """Build a compact prompt that encourages diversity and machine-readable output."""
    tlds_str = ", ".join(f".{t.lower().lstrip('.')}" for t in tlds)
    guidance = STRATEGY_GUIDANCE.get(strategy or "", "Generate varied short memorable names.")
    return (
        f"Generate {count} unique domain candidates for topic {topic!r}.\n"
        f"Strategy: {strategy or 'general'} — {guidance}\n"
        f"Allowed TLDs: {tlds_str}. Label length: {min_len}-{max_len}.\n"
        "Use ASCII letters/digits; internal hyphens are allowed but avoid them when possible. "
        "No subdomains. Avoid near-duplicates and trivial spelling variants.\n"
        "Return ONLY a JSON array of domain strings, with no prose or markdown."
    )
