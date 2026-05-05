# Comparison Engine Design / Audit

## Статус

Этот документ является design/audit планом для будущего comparison engine в Corporate AI Assistant.

Comparison engine ещё не реализован. Текущий baseline умеет извлекать текст и часть структуры из TXT, text-layer PDF, DOCX, CSV, XLSX, PNG/JPG/JPEG OCR baseline и opt-in PDF OCR v1, но отдельного deterministic comparison pipeline в текущем HEAD не подтверждено.

Цель документа - безопасно спроектировать comparison engine без ломки текущего file-chat flow, parser quality gate, PDF OCR v1 default-off поведения и существующего runtime/API контракта.

Это не implementation plan для текущего patch, не API specification, не UI design и не live validation report.

## Phase 1 Implementation Status

Phase 1 source helpers prepared: `comparison_engine.py` добавляет normalized document model helpers для преобразования уже извлечённого parser text в JSON-serializable blocks.

Deterministic diff, API, UI, LLM summary, storage и production runtime integration ещё не реализованы. Текущий file-chat behavior не должен меняться из-за Phase 1.

## Phase 2 Implementation Status

Phase 2 source helpers prepared: `comparison_engine.py` добавляет deterministic diff над `NormalizedDocument` через `compare_normalized_documents()`.

API, UI, LLM summary, report generator, storage и production runtime integration ещё не реализованы. Текущий file-chat behavior не должен меняться из-за Phase 2.

## Phase 3 Implementation Status

Phase 3 source helpers prepared: `comparison_engine.py` добавляет Markdown report generator поверх `ComparisonResult`.

API, UI, LLM summary, storage и production runtime integration ещё не реализованы. LLM explanation остаётся future phase и не участвует в генерации v1 report.

## Comparison Quality Gate Status

Comparison quality gate prepared: `scripts/smoke/run_comparison_quality_gate.sh` запускает локальные unittest modules для normalized document model, deterministic diff и Markdown report generator.

По умолчанию gate не запускает parser gate, Docker, Ollama, GPU, API, UI или runtime integration. Для связанной проверки parser baseline можно отдельно включить `RUN_PARSER_GATE=1`; в этом режиме existing parser quality gate запускается через тот же `PYTHON`.

## Почему Нельзя Сравнивать Только Через LLM

LLM полезен для объяснения уже найденных различий, но не должен быть единственным механизмом поиска изменений:

- LLM может пропустить небольшое, но критичное изменение;
- LLM может галлюцинировать diff или перепутать source document;
- большие документы быстро упираются в prompt budget;
- юридические, финансовые и табличные документы требуют deterministic traceability;
- ответ должен ссылаться на вычисленные differences, а не на догадки по двум большим raw text blocks.

Правильный pipeline для v1:

```text
File A -> parser -> normalized blocks
File B -> parser -> normalized blocks
normalized blocks -> deterministic diff -> structured differences
structured differences -> optional LLM explanation / risk summary
```

LLM получает уже вычисленный diff и объясняет его. LLM не должен самостоятельно искать изменения в больших документах "на глаз".

## Текущий Foundation

Подтверждено аудитом текущего кода и docs:

- `parser_stage.parse_uploaded_file()` выбирает parser path по расширению: TXT, CSV, DOCX, XLSX, PDF, PNG/JPG/JPEG.
- `extract_documents_from_staging()` и `extract_documents_from_shared_staging()` возвращают documents как словари с `name` и plain `content`.
- `build_document_prompt()` собирает file-chat prompt из извлечённого текста; текущий file-chat ответ формирует LLM на основании prompt.
- В `app.py` endpoint `/api/chat_with_files` парсит файлы, применяет document budget и передаёт prompt в LLM job.
- Parser public cutover path готовит parser artifacts и child `file_chat` job, но normalized document model для diff не подтверждён.
- DOCX baseline содержит body text, tables, headers, footers, comments, tracked changes metadata и embedded images marker без OCR внутри DOCX.
- CSV baseline содержит bounded rows/columns/cells.
- XLSX baseline содержит sheets, rows, cells, cached formula values, formula metadata без выполнения формул, merged cells metadata, hidden sheets/rows/columns metadata.
- PDF text-layer поддержан; malformed/invalid PDF мапится в controlled errors.
- PDF OCR v1 реализован opt-in через `ENABLE_PDF_OCR=true`, default-off, live validation pending.
- Gold corpus и parser quality gate уже покрывают одиночные parser fixtures.

Не подтверждено:

- отдельная normalized document model;
- deterministic document/table diff;
- comparison artifacts;
- comparison-specific API endpoint;
- comparison UI;
- pair-based gold fixtures для `docx_v1/v2`, `xlsx_v1/v2`, `csv_v1/v2`, `pdf_v1/v2`.

В коде есть conversation shadow compare для Redis/PostgreSQL read-cutover parity. Это не document comparison engine и не должно смешиваться с новым feature block.

## Target Architecture

### Input Pair

Comparison engine принимает пару документов:

- File A / baseline;
- File B / revised.

Для v1 лучше явно называть роли `baseline` и `revised`, а не полагаться на порядок загрузки без подтверждения.

### Parse

Каждый файл должен проходить через существующие parser paths. Важно не ломать `parse_uploaded_file()` и не менять file-chat prompt contract в первом implementation phase.

Unsupported или broken input должен возвращать controlled error до diff stage.

### Normalize

После parser stage нужен новый normalized document layer. Он должен извлекать устойчивые блоки из уже поддержанных форматов:

- paragraphs;
- tables;
- sheet rows;
- key/value pairs;
- parser metadata;
- OCR page blocks, если source был PDF OCR.

Normalized layer не должен требовать LLM, GPU или live server.

### Deterministic Diff

Diff engine должен работать до LLM и возвращать structured differences:

- added;
- removed;
- changed;
- unchanged optional;
- moved later, не обязательно в v1.

Для v1 допустим conservative block-level и row/cell-level diff без semantic legal scoring.

### LLM Explanation

LLM stage должен быть вторичным:

- получает structured diff, а не два raw documents целиком;
- делает краткое human-readable explanation;
- выделяет risk highlights;
- не придумывает изменения, которых нет в deterministic diff.

### Output

Минимальный output set:

- structured JSON artifact;
- human-readable markdown report;
- optional LLM summary над structured diff.

## Normalized Document Model v1

Минимальная модель:

```text
Document
  id
  filename
  format
  parser_version
  blocks[]

Block
  block_id
  type: paragraph | table | sheet | row | key_value | metadata | ocr_page
  source
    page
    sheet
    section
    row_number
  text
  cells optional
  normalized_text
  hash
  order_index

TableRow
  sheet_or_table_name
  row_index
  columns
  cells
  key_candidate optional

Metadata
  headers
  footers
  comments
  tracked_changes
  formulas
  merged_cells
  hidden_sheets_rows_columns
  ocr_source_markers
```

`block_id` должен быть deterministic для одного parser output при одинаковом input. Для v1 допустимо строить его из format, order index, source path и hash, если это не раскрывает sensitive content в artifact names.

## DOCX Comparison v1

Scope:

- paragraphs;
- tables;
- headers;
- footers;
- comments;
- tracked changes metadata.

Out of scope v1:

- legal semantic scoring;
- moved section detection;
- Word layout fidelity;
- comments threading;
- OCR inside DOCX.

Diff output:

- added paragraph;
- removed paragraph;
- changed paragraph;
- changed table row;
- added/removed table row;
- metadata differences.

DOCX comparison должен использовать уже извлечённые body/table/metadata blocks и не требовать layout-perfect Word rendering.

## XLSX Comparison v1

Scope:

- sheet presence;
- row/cell values;
- formula metadata;
- merged cells metadata;
- hidden sheets/rows/columns metadata.

Out of scope v1:

- charts;
- pivots;
- macros;
- styles;
- recalculating formulas;
- `.xls`.

Diff output:

- added sheet;
- removed sheet;
- changed cell;
- changed formula;
- changed row;
- changed metadata.

Keying strategy:

- v1: order-based rows and cells;
- later: optional header-based key detection;
- no "smart BI" or semantic analytics in v1.

## CSV Comparison v1

Scope:

- header row;
- bounded rows/columns;
- added/removed rows;
- changed cell values.

Out of scope v1:

- type inference as a product claim;
- fuzzy business-key detection;
- multi-file joins;
- BI analytics.

CSV comparison can share table normalization with XLSX row/cell blocks.

## PDF Comparison v1

Scope:

- text-layer PDF blocks;
- PDF OCR v1 text output only when explicitly enabled and after live validation;
- page/source markers when available.

Out of scope v1:

- layout-perfect PDF diff;
- scanned table reconstruction;
- image comparison;
- handwriting;
- production OCR quality guarantee.

PDF OCR source markers should be preserved so reports can distinguish text-layer extraction from OCR-derived text.

## API / UI Strategy

На этом design шаге API/UI не реализуются.

Recommended phases:

- Phase 1: parser-only library and tests;
- Phase 2: CLI/internal test harness;
- Phase 3: API endpoint behind feature flag;
- Phase 4: UI integration;
- Phase 5: live regression.

Future feature flag:

```text
ENABLE_COMPARISON_ENGINE=false
```

Default должен оставаться off до отдельного implementation и validation approval.

## Security / Privacy

Comparison engine должен наследовать upload/security baseline:

- no external SaaS/API;
- no network calls for deterministic diff;
- no secrets in artifacts;
- bounded artifact size;
- reuse upload allowlist;
- reject unsupported formats with controlled errors;
- traceable source references without leaking full sensitive content in filenames, ids or logs;
- do not store sensitive comparison artifacts beyond configured retention policy;
- avoid raw document dumps in logs;
- produce synthetic/test artifacts during validation.

Будущий LLM summary не должен отправлять больше данных, чем требуется: предпочтительно передавать structured diff and bounded excerpts, not full source documents.

## Test Strategy

Future unit tests for normalized blocks:

- DOCX paragraphs/tables;
- DOCX headers/footers/comments/tracked changes metadata;
- XLSX rows/cells/formulas;
- XLSX merged/hidden metadata;
- CSV rows;
- PDF text-layer blocks;
- PDF OCR source markers behind opt-in flag.

Future deterministic diff tests:

- added paragraph;
- removed paragraph;
- changed paragraph;
- changed table cell;
- added/removed XLSX row;
- formula metadata changed;
- hidden row metadata changed;
- added/removed sheet.

Negative tests:

- unsupported `.xls`;
- mismatched formats, если v1 не поддерживает cross-format diff;
- broken input;
- empty documents;
- oversized inputs;
- parser controlled failure propagates cleanly.

Gold corpus extension:

- `docx_contract_v1` / `docx_contract_v2`;
- `xlsx_orders_v1` / `xlsx_orders_v2`;
- `csv_orders_v1` / `csv_orders_v2`;
- `pdf_text_v1` / `pdf_text_v2`.

Quality gate:

- add comparison-only test gate later;
- deterministic diff tests must not require LLM, live server, Ollama or GPU;
- existing parser quality gate must remain green by default.

## Phased Implementation Plan

### Phase 1 - Normalized Document Model Only

- no API;
- no UI;
- no LLM;
- parser output -> normalized blocks;
- tests on synthetic fixtures.

Phase 1 should be small enough to review as a parser-adjacent library change without changing file-chat behavior.

### Phase 2 - Deterministic Diff Engine

- block-level diff;
- table/cell diff;
- JSON artifact;
- deterministic tests.

### Phase 3 - Report Generator

- markdown report;
- no LLM required;
- tests compare stable report fragments.

### Phase 4 - LLM Summary Over Diff

- model receives structured diff, not raw documents;
- no guessing;
- summary and risk highlights only over computed differences.

### Phase 5 - API / UI

- feature flag;
- authenticated endpoint;
- file pair upload flow;
- controlled limits;
- no default-on exposure before validation.

### Phase 6 - Live GPU Validation

Only after deterministic engine passes local tests:

- include comparison engine in next GPU validation window;
- validate installer, models, file-chat, Office parser, PDF OCR v1 and comparison together;
- capture latency, metrics and artifacts;
- do not convert this into production capacity planning.

## PASS / FAIL Criteria For Future Implementation

PASS:

- deterministic diff matches expected changes on synthetic pairs;
- no LLM required for correctness;
- unsupported formats fail controlled;
- parser quality gate remains green;
- comparison tests do not require GPU;
- existing file-chat behavior remains unchanged unless explicitly testing comparison path.

FAIL:

- LLM is responsible for finding raw diffs;
- changes are hallucinated;
- unsupported files crash;
- comparison breaks existing file-chat;
- large artifacts leak sensitive data;
- tests require live server/GPU;
- implementation changes parser defaults without explicit approval.

## Что НЕ Входит В Comparison Engine v1

- юридическое заключение;
- автоматическое принятие решений;
- semantic legal scoring;
- BI analytics;
- pivot/chart diff;
- scanned table reconstruction;
- handwritten documents;
- OCR inside DOCX;
- production capacity benchmark.

## Open Questions

- Где хранить comparison artifacts и как долго?
- Нужен ли отдельный worker type или достаточно parser-adjacent execution на первом этапе?
- Какой API shape нужен после Phase 1/2?
- Какой max pair size и max artifact size выбрать?
- Нужен ли persistent DB для comparison reports?
- Как реализовать redaction/DLP later?
- Как отображать diff в UI без раскрытия лишнего текста?
- Разрешать ли cross-format diff в v1 или ограничить same-format pairs?

## Следующий Один Шаг

После принятия design выполнить Phase 1 implementation patch:

- добавить normalized document model helpers;
- не добавлять API/UI/LLM;
- не менять текущий file-chat behavior;
- добавить tests на synthetic fixtures.
