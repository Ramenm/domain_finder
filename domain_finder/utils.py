from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

console = Console()

DOMAIN_RE = re.compile(
    r"\b(?P<label>[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)\.(?P<tld>[a-zA-Z]{2,24})\b"
)


def normalize_domain_token(
    token: str,
    allowed_tlds: List[str],
    force_tld: Optional[str] = None,
    min_len: int = 4,
    max_len: int = 63,
) -> Optional[str]:
    """
    Нормализует строку к домену вида 'label.tld' (только один '.'), фильтрует по ограничениям длины и TLD.
    """
    token = token.strip().lower()
    token = token.strip(",.;:()[]<>\"'`")

    # Если токен не содержит точки — добавим force_tld/первый доступный
    if "." not in token:
        use_tld = (force_tld or (allowed_tlds[0] if allowed_tlds else "com")).lstrip(".")
        label = token
        candidate = f"{label}.{use_tld}"
    else:
        candidate = token

    m = DOMAIN_RE.fullmatch(candidate)
    if not m:
        return None

    label = m.group("label")
    tld = m.group("tld")
    if len(label) < min_len or len(label) > max_len:
        return None

    # Ограничиваем TLD:
    if allowed_tlds:
        allowed = {t.lstrip(".").lower() for t in allowed_tlds}
        if tld not in allowed:
            if force_tld:
                return f"{label}.{force_tld.lstrip('.')}"
            return None

    # Исключим поддомены (ровно одна точка)
    if candidate.count(".") != 1:
        return None

    # Не допускаем дефис в начале/конце
    if label.startswith("-") or label.endswith("-"):
        return None

    return f"{label}.{tld}"


def extract_domains_from_text(
    text: str,
    allowed_tlds: List[str],
    limit: int,
    min_len: int = 4,
    max_len: int = 15,
    force_tld: Optional[str] = None,
) -> List[str]:
    """
    Достаём домены из ответа модели. Поддерживаются форматы: по одному в строке, через запятую, со списками.
    """
    # Быстрая очистка
    cleaned = re.sub(r"[|•\t]", " ", text)
    # Заменим переносы на запятые, чтобы одинаково парсить и CSV и построчный вывод:
    cleaned = cleaned.replace("\n", ",")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    uniq: Dict[str, None] = {}
    for p in parts:
        dom = normalize_domain_token(
            p, allowed_tlds=allowed_tlds, force_tld=force_tld, min_len=min_len, max_len=max_len
        )
        if dom:
            uniq[dom] = None
        if len(uniq) >= limit:
            break
    return list(uniq.keys())


@dataclass
class CacheEntry:
    available: bool
    source: str
    checked_at: float


class CacheManager:
    def __init__(self, path: str = "domains_cache.json") -> None:
        self.path = Path(path)
        self.data: Dict[str, CacheEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.data = {}
            return
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {
                k: CacheEntry(**v) if isinstance(v, dict) and "available" in v else CacheEntry(bool(v), "unknown", time.time())
                for k, v in obj.items()
            }
        except Exception:
            self.data = {}

    def save(self) -> None:
        self.path.write_text(
            json.dumps({k: asdict(v) for k, v in self.data.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, domain: str) -> Optional[CacheEntry]:
        return self.data.get(domain)

    def set(self, domain: str, available: bool, source: str) -> None:
        self.data[domain] = CacheEntry(available=available, source=source, checked_at=time.time())

    def known(self) -> Dict[str, CacheEntry]:
        return self.data

    def clear(self) -> None:
        self.data = {}
        self.save()


class ResultWriter:
    def __init__(self, txt_path: str = "results.txt", csv_path: Optional[str] = "results.csv") -> None:
        self.txt_path = Path(txt_path)
        self.csv_path = Path(csv_path) if csv_path else None

        # Убедимся, что файлы существуют
        if not self.txt_path.exists():
            self.txt_path.write_text("", encoding="utf-8")
        if self.csv_path and not self.csv_path.exists():
            self.csv_path.write_text("domain,available,source,checked_at\n", encoding="utf-8")

    def append_available(self, domain_records: Iterable[Tuple[str, str, float]]) -> None:
        """
        domain_records: итератор кортежей (domain, source, checked_at)
        """
        with self.txt_path.open("a", encoding="utf-8") as f_txt:
            for domain, source, ts in domain_records:
                f_txt.write(f"{domain}\n")

        if self.csv_path:
            with self.csv_path.open("a", encoding="utf-8") as f_csv:
                for domain, source, ts in domain_records:
                    f_csv.write(f"{domain},true,{source},{int(ts)}\n")

    @staticmethod
    def show_table(available: List[str]) -> None:
        table = Table(title="Доступные домены", show_lines=True)
        table.add_column("#", justify="right")
        table.add_column("Домен", justify="left")
        for i, d in enumerate(available, start=1):
            table.add_row(str(i), d)
        console.print(table)
