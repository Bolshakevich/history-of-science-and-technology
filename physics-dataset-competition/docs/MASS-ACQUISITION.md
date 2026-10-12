# Массовый сбор первоисточников (физический датасет)

Модуль массового сбора научных статей, отчётов и исторических книг по 4 доменам
(**AERO**, **STR**, **RADAR**, **CTRL**) через официальные API. Система
право-гейтирована, вежлива к источникам и детерминирована.

## Источники (адаптеры)

| Адаптер | API | Что даёт |
|---|---|---|
| `openalex` | `api.openalex.org/works` | Open Access статьи, аннотации, PDF-ссылки |
| `arxiv` | `export.arxiv.org/api/query` | Препринты (физика, гидроаэродинамика, управление) |
| `crossref` | `api.crossref.org/works` | DOI, метаданные издателя, лицензии |
| `ntrs` | `ntrs.nasa.gov/api/citations/search` | Отчёты NACA/NASA (Public Domain) |
| `internet_archive` | `archive.org/advancedsearch.php` | Книги в общественном достоянии (до 1930 г.) |

## Использование

```bash
# Каталог встроенных тем поиска по доменам
python scripts/acquire_batch.py topics

# Массовый поиск (только метаданные) + опциональная загрузка в bronze
python scripts/acquire_batch.py mass \
    --domain AERO \
    --services openalex,arxiv,crossref,ntrs,internet_archive \
    --limit 10 \
    --out-manifest .local/physics-bronze/candidates.jsonl \
    --fetch --out-dir .local/physics-bronze
```

## Право-гейт и безопасность

- Скачиваются **только** материалы с `redistributable=True` (PD / CC0 / CC-BY);
- Только `https` и только хосты из allow-list (`download.py`);
- Байты кладутся **локально** (`.local/physics-bronze/`, вне git);
- Манифест содержит поля `abstract` (оригинал) и `abstract_ru` (перевод);
- Секреты (`OPENALEX_MAILTO`, `HF_TOKEN`) не логируются и не коммитятся;
- **Персональные данные слушателей не собираются и не хранятся.**

## Интеграция с харнессом

После сбора `manifest.jsonl` агент с `scientific-extraction-harness` в пакетном
режиме обходит манифест, извлекает числовые значения и условия эксперимента,
переводит аннотацию (`abstract` → `abstract_ru`) и валидирует записи по
`configs/schema/record.schema.json` (или `universal-record.schema.json`).

## CI

Workflow `.github/workflows/mass-acquisition.yml` по расписанию собирает
метаданные по всем доменам (без загрузки байтов), проверяет отсутствие токенов
и выгружает манифесты как артефакты.
