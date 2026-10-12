# SPDX-License-Identifier: GPL-3.0-or-later
"""Клиент NASA Technical Reports Server (NTRS) API (stdlib-only).

Поиск исторических и современных технических отчётов NACA/NASA:
аэродинамика, прочность конструкций, радиолокация, системы управления.

API (POST JSON): ``https://ntrs.nasa.gov/api/citations/search``.
Текстовый full-text отчёта — ``/api/citations/<id>/downloads/<id>.txt``
(host ``ntrs.nasa.gov`` уже в allow-list ``download.py``).

Права: работы Правительства США (US Government Works) находятся в
общественном достоянии; поле ``distribution == PUBLIC`` обязательно.
"""

from __future__ import annotations

import json
from typing import Any

from .http import get  # noqa: F401  (реэкспорт для совместимости импорта)

SEARCH_URL = "https://ntrs.nasa.gov/api/citations/search"
BASE_URL = "https://ntrs.nasa.gov"
SERVICE = "ntrs"


def _as_year(item: dict[str, Any]) -> int | None:
    for key in ("publicationDate", "distributionDate", "submittedDate"):
        value = item.get(key)
        if isinstance(value, str) and value[:4].isdigit():
            try:
                return int(value[:4])
            except ValueError:
                continue
    return None


def _authors(item: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for aff in item.get("authorAffiliations") or []:
        name = (aff.get("meta") or {}).get("author", {}).get("name")
        if name:
            authors.append(name)
    return authors


def _oa_url(item: dict[str, Any]) -> str | None:
    """Предпочесть текстовый full-text (для авто-извлечения), иначе PDF."""
    downloads = item.get("downloads")
    if isinstance(downloads, list) and downloads:
        links = (downloads[0] or {}).get("links") or {}
        rel = links.get("fulltext") or links.get("pdf") or links.get("original")
        if rel:
            return f"{BASE_URL}{rel}" if rel.startswith("/") else rel
    return None


def normalize_item(item: dict[str, Any], *, domain: str, query: str) -> dict[str, Any]:
    """Преобразовать отчёт NTRS в канонического кандидата манифеста."""
    identifier = item.get("id")
    return {
        "service": SERVICE,
        "service_id": identifier,
        "title": item.get("title"),
        "authors": _authors(item),
        "abstract": item.get("abstract"),
        "year": _as_year(item),
        "language": "en",
        "oa_url": _oa_url(item),
        "landing_url": f"{BASE_URL}/citations/{identifier}" if identifier else None,
        "license": "public-domain",
        "source_url": f"{BASE_URL}/citations/{identifier}" if identifier else None,
        "publisher": "NASA",
        "copyright_status": "public-domain",
        "source_type": "report",
        "is_oa": True,
        "domain": domain,
        "query": query,
        "provenance_service": "ntrs.nasa.gov",
    }


def search(query: str, *, domain: str, limit: int = 10) -> list[dict[str, Any]]:
    """Найти отчёты в NTRS. Метаданные only.

    NTRS ищет по POST, но ``http.get`` даёт только GET; используем
    документированный GET-совместимый путь поиска через query-параметр не
    поддерживается, поэтому применяем официальный POST через urllib в
    :func:`_post`.
    """
    payload = {"q": query, "page": {"size": max(1, min(int(limit), 100)), "from": 0}}
    body = _post(SEARCH_URL, payload)
    data = json.loads(body.decode("utf-8"))
    results = data.get("results") or []
    out: list[dict[str, Any]] = []
    for item in results:
        if str(item.get("distribution", "")).upper() != "PUBLIC":
            continue
        out.append(normalize_item(item, domain=domain, query=query))
    return out[:limit]


def _post(url: str, payload: dict[str, Any], *, timeout: float = 30.0) -> bytes:
    """Минимальный POST JSON (stdlib); ошибки — без утечки секретов."""
    import urllib.error
    import urllib.request

    from .http import USER_AGENT, HttpError

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} для {url}") from None
    except urllib.error.URLError as exc:
        raise HttpError(f"сетевая ошибка для {url}: {exc.reason}") from None
