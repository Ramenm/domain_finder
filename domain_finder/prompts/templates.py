"""Prompt templates for domain generation."""

from typing import List


def build_prompt(
    topic: str,
    tlds: List[str],
    count: int,
    language: str = "ru",
    min_len: int = 4,
    max_len: int = 15,
) -> str:
    """
    Build a prompt for LLM to generate domain names.

    Args:
        topic: Topic/theme for domain generation
        tlds: List of allowed TLDs
        count: Number of domains to generate
        language: Language for prompt ('ru' or 'en')
        min_len: Minimum label length
        max_len: Maximum label length

    Returns:
        Formatted prompt string
    """
    tlds_str = ", ".join(f".{t.lower().lstrip('.')}" for t in tlds)
    lang = language.lower().strip()

    if lang.startswith("ru"):
        header = (
            "Сгенерируй список уникальных, коротких и запоминающихся доменных имён "
            f"второго уровня на тематику: {topic!r}. "
        )
        rules = (
            f"- Количество доменов: {count}.\n"
            f"- Допустимые доменные зоны: {tlds_str}.\n"
            f"- Длина второй части домена (без TLD): от {min_len} до {max_len} символов.\n"
            "- Выводи только домены, каждый на новой строке или через запятую.\n"
            "- Без пояснений, предисловий и дополнительного текста.\n"
            "- Не используй подчёркивания, пробелы, эмодзи; не начинай и не заканчивай дефисом.\n"
            "- Разрешены только латинские буквы и цифры; дефис допустим только внутри имени.\n"
            "- Не добавляй поддомены (в домене должен быть ровно один символ '.').\n"
        )
        footer = "Верни только список доменов без дополнительного текста."
    else:
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

