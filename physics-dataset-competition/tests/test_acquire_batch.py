#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Тесты массового сбора: каталог тем, дедупликация, ошибки источников.

Сеть не используется: ``_search_service`` подменяется фикстурами.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
SRC = MODULE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SPEC = importlib.util.spec_from_file_location(
    "acquire_batch", MODULE_ROOT / "scripts" / "acquire_batch.py"
)
assert _SPEC and _SPEC.loader
acquire_batch = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(acquire_batch)


def test_topic_catalog_covers_all_domains() -> None:
    for domain in acquire_batch.DOMAINS:
        assert domain in acquire_batch.TOPIC_CATALOG
        assert len(acquire_batch.TOPIC_CATALOG[domain]) >= 1


def test_mass_deduplicates_and_reports_errors(tmp_path: Path, monkeypatch) -> None:
    def fake_search(service, query, domain, limit):  # noqa: ARG001
        if service == "arxiv":
            raise RuntimeError("сеть недоступна")
        return [
            {"service": service, "service_id": "dup", "title": "A"},
            {"service": service, "service_id": "dup", "title": "A-повтор"},
        ]

    monkeypatch.setattr(acquire_batch, "_search_service", fake_search)
    out = tmp_path / "cand.jsonl"
    rc = acquire_batch.main(
        [
            "mass",
            "--domain",
            "AERO",
            "--services",
            "openalex,arxiv",
            "--topics",
            "one-topic",
            "--limit",
            "5",
            "--out-manifest",
            str(out),
        ]
    )
    assert rc == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    # openalex вернул дубликат service_id='dup' — после дедупликации одна строка.
    assert len(rows) == 1
    assert rows[0]["service"] == "openalex"


def test_mass_rejects_unknown_service(tmp_path: Path, capsys) -> None:
    rc = acquire_batch.main(
        [
            "mass",
            "--domain",
            "AERO",
            "--services",
            "openalex,not-a-service",
            "--out-manifest",
            str(tmp_path / "x.jsonl"),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "неизвестные сервисы" in err


def test_topics_command_prints_catalog(capsys) -> None:
    rc = acquire_batch.main(["topics"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "AERO" in payload
