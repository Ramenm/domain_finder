"""Prompt templates for domain generation."""


def build_prompt(
    topic: str,
    tlds: list[str],
    count: int,
    min_len: int = 4,
    max_len: int = 15,
) -> str:
    """
    Build a prompt for LLM to generate domain names.

    Args:
        topic: Topic/theme for domain generation
        tlds: List of allowed TLDs
        count: Number of domains to generate
        min_len: Minimum label length
        max_len: Maximum label length

    Returns:
        Formatted prompt string
    """
    tlds_str = ", ".join(f".{t.lower().lstrip('.')}" for t in tlds)

    header = (
        "Generate a list of unique, short, and memorable second-level domain names "
        f"for the topic: {topic!r}. "
    )
    rules = (
        f"- Number of domains: {count}.\n"
        f"- Allowed TLDs: {tlds_str}.\n"
        f"- Length of the second-level label (without TLD): {min_len} to {max_len} characters.\n"
        "- Output only domains, one per line or comma-separated.\n"
        "- No explanations, introductions, or additional text.\n"
        "- Use only ASCII letters and digits; hyphen allowed only inside the label, not at the ends.\n"
        "- Exactly one dot in the domain (no subdomains).\n"
    )
    footer = "Return only the list of domains without any additional text."

    return f"{header}\n{rules}\n{footer}"
