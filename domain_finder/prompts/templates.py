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
            f"(только второй уровень) на тематику: {topic!r}. "
        )
        rules = (
            f"- Количество: {count}.\n"
            f"- Допустимые зоны: {tlds_str}.\n"
            f"- Длина второй части (до точки): от {min_len} до {max_len} символов.\n"
            "- Пиши только домены, каждый на новой строке или через запятую.\n"
            "- Никаких пояснений, предисловий и постскриптумов.\n"
            "- Не используй подчёркивания, пробелы, эмодзи и не начинай/не заканчивай дефисом.\n"
            "- Разрешены только латинские буквы и цифры, дефис внутри.\n"
            "- Не добавляй поддомены (только один '.' в домене).\n"
        )
        footer = "Верни только домены без дополнительного текста."
    else:
        header = (
            "Generate a list of unique, short, memorable second-level domain names "
            f"for the topic: {topic!r}. "
        )
        rules = (
            f"- Amount: {count}.\n"
            f"- Allowed TLDs: {tlds_str}.\n"
            f"- Length of the second-level label: {min_len} to {max_len} chars.\n"
            "- Output only domains, one per line or comma-separated.\n"
            "- No explanations or extra text.\n"
            "- Use only ASCII letters and digits; hyphen allowed inside, not at the ends.\n"
            "- Exactly one dot (no subdomains).\n"
        )
        footer = "Return domains only, without any extra text."

    return f"{header}\n{rules}\n{footer}"

