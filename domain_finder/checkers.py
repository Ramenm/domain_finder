from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import Iterable, Dict, Tuple, Optional

import requests
import whois  # type: ignore
from rich.progress import Progress, BarColumn, TimeElapsedColumn, TimeRemainingColumn, SpinnerColumn
from rich.console import Console

console = Console()


@dataclass(frozen=True)
class CheckResult:
    domain: str
    available: bool
    source: str  # "rdap" | "whois"
    checked_at: float


def _rdap_is_available(domain: str, session: Optional[requests.Session] = None, timeout: float = 10.0) -> bool:
    """
    RDAP: 404 -> свободен, 200 -> зарегистрирован.
    """
    sess = session or requests.Session()
    url = f"https://rdap.org/domain/{domain}"
    try:
        resp = sess.get(url, timeout=timeout)
        if resp.status_code == 404:
            return True
        if resp.status_code == 200:
            return False
        # На всякий случай — в сомнительных статусах считаем "занят", чтобы не давать ложноположительных.
        return False
    except Exception:
        return False


def _whois_is_available(domain: str) -> bool:
    """
    WHOIS через python-whois. Работает медленнее и менее стабильно, используйте как запасной вариант.
    """
    try:
        data = whois.whois(domain)
        # В разных реализациях это может быть dict или объект:
        def _get(attr: str):
            if isinstance(data, dict):
                return data.get(attr)
            return getattr(data, attr, None)

        # Если видим признаки регистрации — считаем занят:
        dn = _get("domain_name")
        created = _get("creation_date")
        emails = _get("emails")
        if dn or created or emails:
            return False
        return True
    except Exception:
        # Ошибки WHOIS трактуем как "не удалось подтвердить" => считаем ЗАНЯТ.
        return False


def _check_single(
    domain: str,
    prefer_rdap: bool = True,
    session: Optional[requests.Session] = None,
    rdap_timeout: float = 10.0,
    whois_fallback: bool = False,
) -> CheckResult:
    if prefer_rdap:
        ok = _rdap_is_available(domain, session=session, timeout=rdap_timeout)
        if ok is True:
            return CheckResult(domain, True, "rdap", time.time())
        if ok is False and not whois_fallback:
            return CheckResult(domain, False, "rdap", time.time())
        # если RDAP не дал 404 (занят/сомнительно) и разрешён fallback — проверим WHOIS
        if whois_fallback:
            w = _whois_is_available(domain)
            return CheckResult(domain, w, "whois", time.time())
        return CheckResult(domain, False, "rdap", time.time())
    # если предпочитаем WHOIS:
    w = _whois_is_available(domain)
    return CheckResult(domain, w, "whois", time.time())


def check_domains_concurrent(
    domains: Iterable[str],
    prefer_rdap: bool = True,
    max_workers: int = 20,
    rdap_timeout: float = 10.0,
    whois_fallback: bool = False,
) -> Dict[str, CheckResult]:
    """
    Параллельно проверяет список доменов. Возвращает словарь domain -> CheckResult.
    """
    domains = list(dict.fromkeys(domains))
    results: Dict[str, CheckResult] = {}

    with requests.Session() as session:
        # Лёгкий пул потоков
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool, Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            BarColumn(),
            "{task.completed}/{task.total}",
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Проверка доменов…", total=len(domains))
            fut_to_domain: Dict[concurrent.futures.Future[CheckResult], str] = {}

            for d in domains:
                fut = pool.submit(
                    _check_single,
                    d,
                    prefer_rdap,
                    session,
                    rdap_timeout,
                    whois_fallback,
                )
                fut_to_domain[fut] = d

            for fut in concurrent.futures.as_completed(fut_to_domain):
                res = fut.result()
                results[res.domain] = res
                progress.advance(task)

    return results
