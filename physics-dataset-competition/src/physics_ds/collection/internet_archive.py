# SPDX-License-Identifier: GPL-3.0-or-later
"""Клиент Internet Archive Advanced Search API (stdlib-only).

Поиск исторических книг и монографий в общественном достоянии (до 1930 года):
классические труды по естественной философии, механике, аэродинамике.

API: ``https://archive.org/advancedsearch.php`` — только метаданные (docs).
Загрузка текстового OCR-слоя (``_djvu.txt``) — отдельной командой fetch по
allow-list хоста ``archive.org``/``ia.us.archive.org`` (см. download.py).

Права: элементы с ``rights``/``licenseurl`` в открытых лицензиях или
общественном достоянии. Материалы без явного общедоступного статуса
отсеиваются ``rights.classifier`` при загрузке.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from .http import get

SEARCH_URL = "https://archive.org/advancedsearch.php"
SERVICE = "internet_archive"

# Поля, запрашиваемые из Solr-индекса Archive.org.
_FIELDS = [
    "identifier",
    "title",
    "creator",
    "year",
    "date",
    "language",
    "licenseurl",
    "rights",
    "mediatype",
    "collection",
]


def _as_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:4].isdigit():
        try:
            return int(value[:4])
        except ValueError:
            return None
    return None


def _djvu_url(identifier: str) -> str:
    """Прямая ссылка на текстовый OCR-слой (DjVu text) элемента."""
    return f"https://archive.org/download/{identifier}/{identifier}_djvu.txt"


def normalize_doc(doc: dict[str, Any], *, domain: str, query: str) -> dict[str, Any]:
    """Преобразовать документ Archive.org в канонического кандидата манифеста."""
    identifier = doc.get("identifier")
    return {
        "service": SERVICE,
        "service_id": identifier,
        "title": doc.get("title"),
        "authors": doc.get("creator"),
        "year": _as_year(doc.get("year") or doc.get("date")),
        "language": doc.get("language"),
        "oa_url": _djvu_url(str(identifier)) if identifier else None,
        "landing_url": f"https://archive.org/details/{identifier}"
        if identifier
        else None,
        "license": _map_license(doc.get("licenseurl"), doc.get("rights")),
        "source_url": f"https://archive.org/details/{identifier}"
        if identifier
        else None,
        "copyright_status": "public-domain",
        "source_type": "book",
        "is_oa": True,
        "domain": domain,
        "query": query,
        "provenance_service": "archive.org",
    }


def _map_license(licenseurl: Any, rights: Any) -> str:
    """Определить SPDX-подобный идентификатор лицензии/прав."""
    text = f"{licenseurl or ''} {rights or ''}".lower()
    # CC0 проверяем ДО общего «publicdomain»: URL CC0 содержит 'publicdomain/zero'.
    if "creativecommons.org/publicdomain/zero" in text or "cc0" in text:
        return "cc0"
    if "by-sa" in text:
        return "cc-by-sa"
    if "creativecommons.org/licenses/by/" in text or "by/4.0" in text:
        return "cc-by"
    if (
        "publicdomain" in text
        or "public domain" in text
        or "no known copyright" in text
    ):
        return "public-domain"
    return "unknown"


def search(
    query: str,
    *,
    domain: str,
    limit: int = 10,
    year_to: int | None = 1930,
) -> list[dict[str, Any]]:
    """Найти тексты в Archive.org. Метаданные only; сеть — один GET.

    ``year_to`` ограничивает верхнюю границу года (по умолчанию 1930 —
    эпоха, для которой общественное достояние наиболее вероятно).
    """
    q = f"mediatype:texts AND ({query})"
    if year_to is not None:
        q += f" AND year:[* TO {int(year_to)}]"
    pairs: list[tuple[str, str]] = [
        ("q", q),
        ("rows", str(max(1, min(int(limit), 100)))),
        ("page", "1"),
        ("output", "json"),
    ]
    for field in _FIELDS:
        pairs.append(("fl[]", field))
    body = get(f"{SEARCH_URL}?{urlencode(pairs)}")
    payload = json.loads(body.decode("utf-8"))
    docs = (payload.get("response") or {}).get("docs") or []
    out: list[dict[str, Any]] = []
    for doc in docs:
        out.append(normalize_doc(doc, domain=domain, query=query))
    return out[:limit]
