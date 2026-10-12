#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Массовый сбор первоисточников: поиск по официальным API и загрузка на диске.

Оркеструет адаптеры из ``physics_ds.collection`` для массовой выкачки
первоисточников по заранее заданным темам и доменам. Каждый шаг
право-гейтирован (``rights.classifier``), вежлив (rate-limit в http.py) и
детерминирован (SHA-256, манифест append-only).

Команды:
  topics  — показать встроенный каталог тем поиска по доменам;
  mass    — выполнить поиск по темам и (опционально) загрузку в bronze.

Использование:
  python scripts/acquire_batch.py topics
  python scripts/acquire_batch.py mass --domain AERO --services openalex,arxiv,ntrs,internet_archive \\
      --limit 10 --out-manifest .local/physics-bronze/candidates.jsonl [--fetch --out-dir .local/physics-bronze]

Границы (как в collect.py):
  * search — metadata-only, ничего не скачивает;
  * fetch — только redistributable=True, только https, только allow-list;
  * байты — только в локальную директорию вне git;
  * секреты (``*_MAILTO``, токены) не печатаются.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
SRC = MODULE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from physics_ds.collection import (  # noqa: E402
    arxiv,
    crossref,
    internet_archive,
    manifest,
    ntrs,
    openalex,
)
from physics_ds.collection.download import (  # noqa: E402
    fetch_candidate,
    write_fetch_manifest,
)

DOMAINS = ("AERO", "STR", "RADAR", "CTRL")
ALL_SERVICES = ("openalex", "arxiv", "crossref", "ntrs", "internet_archive")

# Встроенный каталог тем поиска по доменам физического датасета.
TOPIC_CATALOG: dict[str, list[str]] = {
    "AERO": [
        "airfoil lift drag polar wind tunnel",
        "boundary layer transition reynolds number",
        "compressible flow mach number aerodynamic coefficients",
        "wing pressure distribution pressure coefficient",
    ],
    "STR": [
        "tensile test stress strain curve yield strength",
        "fatigue S-N curve cycles to failure",
        "elastic modulus young's modulus metal alloy",
        "fracture toughness material properties temperature",
    ],
    "RADAR": [
        "radar cross section monostatic bistatic",
        "antenna radiation pattern gain directivity",
        "scattering angle frequency polarization measurement",
        "RCS measurement anechoic chamber",
    ],
    "CTRL": [
        "PID controller step response step response settling time",
        "transfer function frequency response bode nyquist",
        "closed loop stability phase margin gain margin",
        "state space system identification experiment",
    ],
}


def _search_service(service: str, query: str, domain: str, limit: int) -> list[dict]:
    """Вызвать один адаптер; возвращает кандидатов. Не секретнит ошибки."""
    if service == "openalex":
        return openalex.search(query, domain=domain, limit=limit)
    if service == "arxiv":
        return arxiv.search(query, domain=domain, limit=limit)
    if service == "crossref":
        return crossref.search(query, domain=domain, limit=limit)
    if service == "ntrs":
        return ntrs.search(query, domain=domain, limit=limit)
    if service == "internet_archive":
        return internet_archive.search(query, domain=domain, limit=limit)
    raise ValueError(f"неизвестный сервис: {service!r}")


def cmd_topics(_args: argparse.Namespace) -> int:
    print(json.dumps(TOPIC_CATALOG, ensure_ascii=False, indent=2))
    return 0


def cmd_mass(args: argparse.Namespace) -> int:
    services = [s.strip() for s in args.services.split(",") if s.strip()]
    unknown = [s for s in services if s not in ALL_SERVICES]
    if unknown:
        print(
            json.dumps(
                {"error": f"неизвестные сервисы: {unknown}"}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2

    topics = (
        args.topics.split(";") if args.topics else TOPIC_CATALOG.get(args.domain, [])
    )
    if not topics:
        print(
            json.dumps(
                {"error": f"нет тем для домена {args.domain}"}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2

    all_rows: list[dict] = []
    errors: list[dict] = []
    for topic in topics:
        for service in services:
            try:
                rows = _search_service(service, topic, args.domain, args.limit)
                for row in rows:
                    row.setdefault("domain", args.domain)
                    row.setdefault("query", topic)
                all_rows.extend(rows)
            except Exception as exc:  # noqa: BLE001 — ошибка источника не фатальна
                errors.append({"service": service, "topic": topic, "error": str(exc)})

    # Дедупликация по (service, service_id) — детерминированно, порядок сохраняем.
    seen: set[tuple] = set()
    unique: list[dict] = []
    for row in all_rows:
        key = (row.get("service"), str(row.get("service_id")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    count = manifest.write(args.out_manifest, unique)

    report: dict = {
        "command": "mass",
        "domain": args.domain,
        "services": services,
        "topics": len(topics),
        "candidates": count,
        "out_manifest": str(args.out_manifest),
        "errors": errors,
        "note": "metadata-only; загрузка — только с флагом --fetch",
    }

    if args.fetch:
        out_dir = Path(args.out_dir)
        outcomes = [
            fetch_candidate(row, out_dir=out_dir)
            for row in unique[: args.max_items or None]
        ]
        fetch_manifest = out_dir / "fetch-manifest.jsonl"
        write_fetch_manifest(fetch_manifest, outcomes)
        downloaded = [o for o in outcomes if o.status == "downloaded"]
        report["fetch"] = {
            "requested": len(outcomes),
            "downloaded": len(downloaded),
            "skipped": len(outcomes) - len(downloaded),
            "out_dir": str(out_dir),
            "fetch_manifest": str(fetch_manifest),
        }

    print(json.dumps(report, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Массовый сбор первоисточников по официальным API."
    )
    sub = ap.add_subparsers(dest="command", required=True)

    pt = sub.add_parser("topics", help="Показать каталог тем поиска по доменам.")
    pt.set_defaults(func=cmd_topics)

    pm = sub.add_parser("mass", help="Массовый поиск и (опц.) загрузка по темам.")
    pm.add_argument("--domain", choices=DOMAINS, required=True)
    pm.add_argument(
        "--services",
        default="openalex,arxiv,crossref",
        help="Список сервисов через запятую.",
    )
    pm.add_argument(
        "--topics",
        default="",
        help="Свои темы через ';' (по умолчанию — каталог домена).",
    )
    pm.add_argument("--limit", type=int, default=10, help="Кандидатов на тему/сервис.")
    pm.add_argument(
        "--out-manifest",
        default=".local/physics-bronze/candidates.jsonl",
        help="JSONL-манифест кандидатов.",
    )
    pm.add_argument(
        "--fetch",
        action="store_true",
        help="Загрузить разрешённые OA-источники ЛОКАЛЬНО (вне git).",
    )
    pm.add_argument(
        "--out-dir",
        default=".local/physics-bronze",
        help="Директория загрузки (при --fetch).",
    )
    pm.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Загрузить не более N (0 = все) при --fetch.",
    )
    pm.set_defaults(func=cmd_mass)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
