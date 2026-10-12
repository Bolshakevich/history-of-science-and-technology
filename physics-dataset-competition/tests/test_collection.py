# SPDX-License-Identifier: GPL-3.0-or-later
"""Тесты сбора: парсинг API, право-гейт загрузки, манифест.

Сеть не используется: клиенты парсят фикстурные payload'ы, а ``download.fetch_candidate``
проверяется на отклонение не-redistributable / не-https входов.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
SRC = MODULE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from physics_ds.collection import (  # noqa: E402
    arxiv,
    crossref,
    http,
    internet_archive,
    manifest,
    ntrs,
    openalex,
)
from physics_ds.collection.download import (  # noqa: E402
    FetchOutcome,
    fetch_candidate,
    is_allowed_url,
    write_fetch_manifest,
)

FIXTURES = MODULE_ROOT / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- openalex ----------------------------------------------------------------


def test_openalex_normalizes_work() -> None:
    payload = _load("openalex_works.json")
    work = payload["results"][0]
    cand = openalex.normalize_work(work, domain="AERO", query="airfoil")
    assert cand["service"] == "openalex"
    assert cand["title"].startswith("Wind tunnel")
    assert cand["year"] == 1935
    assert cand["oa_url"] == "https://arxiv.org/pdf/2401.00001"
    assert cand["license"] == "cc-by"  # канонический SPDX-id
    assert cand["is_oa"] is True
    assert cand["provenance_service"] == "openalex.org"
    assert cand["abstract"].startswith("Measured drag")


# --- arxiv -------------------------------------------------------------------


def test_arxiv_parses_atom_feed() -> None:
    xml = (FIXTURES / "arxiv_feed.xml").read_bytes()
    rows = arxiv.parse_feed(xml, domain="AERO", query="airfoil")
    assert len(rows) == 2
    first = rows[0]
    assert first["service_id"] == "2401.00001v1"
    assert first["oa_url"] == "http://arxiv.org/pdf/2401.00001v1"
    assert first["license"] == "cc-by-4.0"
    assert first["year"] == 2024
    assert first["doi"] == "10.1234/arxiv.example"
    # без элемента лицензии права неизвестны
    assert rows[1]["license"] is None


def test_arxiv_single_request_does_not_sleep() -> None:
    slept: list[float] = []

    # arxiv.py связывает get при импорте (from .http import get), поэтому
    # патчим именно модуль arxiv, а не http.
    original = arxiv.get

    def fake_get(url, **kwargs):  # noqa: ARG001
        return (FIXTURES / "arxiv_feed.xml").read_bytes()

    arxiv.get = fake_get  # type: ignore[assignment]
    try:
        rows = arxiv.search("airfoil", domain="AERO", limit=2, sleep=slept.append)
    finally:
        arxiv.get = original  # type: ignore[assignment]
    assert len(rows) == 2
    assert slept == []  # одиночный запрос не спит


def test_arxiv_pagination_sleeps_three_seconds() -> None:
    slept: list[float] = []
    pages = [
        (FIXTURES / "arxiv_feed.xml").read_bytes(),
        (FIXTURES / "arxiv_feed.xml").read_bytes(),
    ]
    calls = {"n": 0}

    original = arxiv.get

    def fake_get(url, **kwargs):  # noqa: ARG001
        body = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return body

    arxiv.get = fake_get  # type: ignore[assignment]
    try:
        # page_size=2 => две страницы по 2 записи
        arxiv.search("airfoil", domain="AERO", limit=4, page_size=2, sleep=slept.append)
    finally:
        arxiv.get = original  # type: ignore[assignment]
    assert slept == [arxiv.POLITE_DELAY_SECONDS]


# --- crossref ----------------------------------------------------------------


def test_crossref_metadata_only() -> None:
    payload = _load("crossref_works.json")
    items = payload["message"]["items"]
    closed = crossref.normalize_item(items[0], domain="STR", query="fatigue")
    assert closed["oa_url"] is None
    assert closed["is_oa"] is False
    assert closed["license"] is None  # нет свободной лицензии
    assert closed["year"] == 1995

    oa = crossref.normalize_item(items[1], domain="STR", query="fatigue")
    assert oa["license"] == "cc-by"
    assert oa["oa_url"] is None  # Crossref не даёт проверенный URL загрузки


def test_crossref_metadata_is_not_redistributable() -> None:
    payload = _load("crossref_works.json")
    item = crossref.normalize_item(
        payload["message"]["items"][0], domain="STR", query="q"
    )
    outcome = fetch_candidate(item, out_dir=Path("__unused__"))
    assert outcome.status == "skipped"
    assert "redistributable" in outcome.reason


# --- download gating ---------------------------------------------------------


def test_download_rejects_non_https() -> None:
    cand = {
        "service_id": "x",
        "title": "t",
        "license": "cc-by-4.0",
        "is_oa": True,
        "oa_url": "http://arxiv.org/pdf/1",
    }
    outcome = fetch_candidate(cand, out_dir=Path("__unused__"))
    assert outcome.status == "skipped"
    assert "https" in outcome.reason


def test_download_rejects_non_allowlisted_host() -> None:
    cand = {
        "service_id": "x",
        "title": "t",
        "license": "cc-by-4.0",
        "is_oa": True,
        "oa_url": "https://evil.example.com/paper.pdf",
    }
    outcome = fetch_candidate(cand, out_dir=Path("__unused__"))
    assert outcome.status == "skipped"
    assert "allow-list" in outcome.reason


def test_is_allowed_url() -> None:
    assert is_allowed_url("https://arxiv.org/pdf/1")[0] is True
    assert is_allowed_url("http://arxiv.org/pdf/1")[0] is False
    assert is_allowed_url("https://example.org/x.pdf")[0] is False
    assert is_allowed_url("")[0] is False


def test_download_writes_bytes_and_hashes(tmp_path: Path, monkeypatch) -> None:
    from physics_ds.collection import download as dl

    def fake_get(url, **kwargs):  # noqa: ARG001
        return b"%PDF-1.4 test-body"

    monkeypatch.setattr(dl.http, "get", fake_get)
    cand = {
        "service_id": "2401.00001v1",
        "title": "t",
        "license": "cc-by-4.0",
        "is_oa": True,
        "oa_url": "https://arxiv.org/pdf/2401.00001v1",
        "provenance_service": "export.arxiv.org",
    }
    outcome = fetch_candidate(cand, out_dir=tmp_path)
    assert outcome.status == "downloaded"
    assert outcome.sha256 is not None and len(outcome.sha256) == 64
    assert Path(outcome.path).read_bytes() == b"%PDF-1.4 test-body"


# --- manifest ----------------------------------------------------------------


def test_manifest_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cand.jsonl"
    count = manifest.write(
        path, [{"service": "openalex", "title": "a"}, {"service": "arxiv"}]
    )
    assert count == 2
    rows = manifest.read(path)
    assert rows[0]["service"] == "openalex"
    assert rows[0]["title"] == "a"
    # канонический набор полей присутствует (даже если None)
    assert "oa_url" in rows[0]


def test_fetch_manifest_writer(tmp_path: Path) -> None:
    path = tmp_path / "fetch.jsonl"
    n = write_fetch_manifest(
        path,
        [FetchOutcome(service_id="x", status="skipped", reason="r")],
    )
    assert n == 1
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "skipped"


# --- internet_archive --------------------------------------------------------


def test_internet_archive_normalizes_doc() -> None:
    payload = json.loads(
        (FIXTURES / "internet_archive_search.json").read_text(encoding="utf-8")
    )
    doc = payload["response"]["docs"][0]
    cand = internet_archive.normalize_doc(doc, domain="AERO", query="mechanics")
    assert cand["service"] == "internet_archive"
    assert cand["service_id"] == "naturalphilosophy00hers"
    assert cand["year"] == 1831
    assert cand["license"] == "public-domain"
    assert cand["copyright_status"] == "public-domain"
    assert cand["oa_url"].endswith("naturalphilosophy00hers_djvu.txt")


def test_internet_archive_maps_cc0() -> None:
    payload = json.loads(
        (FIXTURES / "internet_archive_search.json").read_text(encoding="utf-8")
    )
    doc = payload["response"]["docs"][1]
    cand = internet_archive.normalize_doc(doc, domain="AERO", query="aerodynamik")
    assert cand["license"] == "cc0"
    assert cand["year"] == 1921


# --- ntrs --------------------------------------------------------------------


def test_ntrs_normalizes_public_report() -> None:
    payload = json.loads((FIXTURES / "ntrs_search.json").read_text(encoding="utf-8"))
    item = payload["results"][0]
    cand = ntrs.normalize_item(item, domain="AERO", query="airfoil")
    assert cand["service"] == "ntrs"
    assert cand["service_id"] == "19630011950"
    assert cand["license"] == "public-domain"
    assert cand["copyright_status"] == "public-domain"
    assert cand["oa_url"].endswith("19630011950.txt")
    assert cand["authors"] == ["M F Platzer"]
    assert cand["abstract"].startswith("Chordwise pressure")


def test_ntrs_skips_non_public_distribution(monkeypatch) -> None:
    payload = json.loads((FIXTURES / "ntrs_search.json").read_text(encoding="utf-8"))

    def fake_post(url, data, **kwargs):  # noqa: ARG001
        return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(ntrs, "_post", fake_post)
    rows = ntrs.search("airfoil", domain="AERO", limit=10)
    # Из двух записей остаётся только PUBLIC.
    assert len(rows) == 1
    assert rows[0]["service_id"] == "19630011950"


# --- http retry --------------------------------------------------------------


def test_retry_delay_returns_seconds_without_sleeping() -> None:
    """Регрессия: _retry_delay возвращает число секунд и НЕ вызывает sleep сам."""

    class _Resp:
        headers: dict[str, str] = {}

    calls: list[float] = []

    def fake_sleep(seconds: float) -> None:  # noqa: ARG001
        calls.append(seconds)

    delay = http._retry_delay(
        _Resp(), attempt=0, max_retry_after=30.0, sleep=fake_sleep
    )
    assert isinstance(delay, float)
    assert delay == 1.0  # 2**0
    assert calls == []  # задержка только вычислена, не применена
