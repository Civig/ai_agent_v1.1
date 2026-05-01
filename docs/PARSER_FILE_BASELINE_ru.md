# Parser / File Support Baseline Status

## Статус

Текущий parser/file baseline находится в состоянии demo / pilot validation readiness.

Office file optimization v1.0 готов как source-level parser baseline и покрыт локальными unit/parser-quality проверками. Это не production certification, не final live benchmark и не подтверждение результата на следующем live/GPU validation window.

Этот документ фиксирует фактическое состояние после следующих изменений:

- `8d4de22 parser: add Office metadata extraction baseline`
- `7e383ce test(parser): add parser quality gate script`
- `640cf78 test(parser): validate gold corpus extraction`
- `52761f7 test(parser): add gold file corpus manifest`
- `c305526 parser: add CSV and XLSX baseline extraction`
- `ab43606 parser: preserve DOCX table structure`
- `db11261 parser: report PDFs without text layer explicitly`
- `09f1a6a parser: add safe OCR image preprocessing`

## Что поддержано сейчас

| Формат | Статус | Что поддержано | Ограничения |
| --- | --- | --- | --- |
| TXT | Поддержан | Text extraction. | Только plain text extraction, без отдельной semantic-разметки. |
| PDF text-layer | Поддержан | Text-layer extraction, page limit, malformed/invalid cases map to controlled errors. | Text-layer PDF не должен уходить в OCR; качество зависит от наличия извлекаемого текстового слоя. |
| Scanned / image-only PDF | Controlled reject by default; opt-in OCR v1 | По умолчанию explicit controlled detection и понятная ошибка для PDF без текстового слоя. При `ENABLE_PDF_OCR=true` доступен bounded PDF OCR v1 для первых страниц. | PDF OCR выключен по умолчанию; нет table reconstruction, layout-perfect extraction, handwriting recognition или production capacity guarantee. |
| DOCX | Поддержан | Body text, paragraphs, tables with row/cell structure, headers, footers, comments, tracked changes detection, embedded images detection. | OCR inside DOCX не поддержан; full Word semantics, complex content controls и legal compare не заявлены. |
| PNG / JPG / JPEG | Поддержан baseline | OCR baseline, safe preprocessing, dimension cap, OCR timeout. | OCR quality зависит от исходного изображения и OCR runtime; это не PDF OCR. |
| CSV | Поддержан | Rows/columns baseline extraction, bounded rows/columns/cells. | Нет advanced typing/semantic schema inference. |
| XLSX | Поддержан | Workbook/sheets/rows/cells baseline, cached formula values, formula metadata без выполнения формул, merged cells metadata, hidden sheets/rows/columns metadata. | Charts, pivots, macros и advanced Excel semantics не поддержаны. |
| XLS | Unsupported | Explicit unsupported upload type. | `.xls` support не реализован и не заявлен. |
| Comparison engine | Not implemented | Нет. | Full legal/document comparison engine не готов. |

## Что проверяется локально

Локальный parser quality baseline основан на синтетическом gold corpus:

- `tests/smoke/fixtures/gold/manifest.json`
- checksum/size metadata по fixtures
- positive и negative parser/file cases
- parser-only quality checks без LLM, GPU и live server
- parser quality gate script

Core gate:

```bash
PYTHON=/tmp/ai-agent-test-venv/bin/python bash scripts/smoke/run_parser_quality_gate.sh
```

Extended gate с installer contract tests:

```bash
RUN_INSTALLER_CONTRACT=1 PYTHON=/tmp/ai-agent-test-venv/bin/python bash scripts/smoke/run_parser_quality_gate.sh
```

Core gate запускает:

- `tests.test_gold_file_corpus`
- `tests.test_gold_parser_quality`
- `tests.test_upload_backend`
- `tests.test_smoke_kit`
- `tests.smoke_evaluator_test`

Extended gate дополнительно запускает:

- `tests.test_install_postgres_profile`
- `tests.test_install_model_selection`
- `tests.test_bootstrap_ollama_models_contract`

## Что НЕ готово

- PDF OCR включён только opt-in через `ENABLE_PDF_OCR=true` и остаётся v1 baseline, не full PDF intelligence.
- OCR inside DOCX.
- `.xls`.
- Advanced Excel charts/pivots/macros.
- Full legal/document comparison engine.
- Production-ready dashboard RBAC / claim model.
- Final live GPU regression после последних parser/file patches.

## Следующий validation step

Перед следующим feature-блоком нужно подготовить live regression plan для следующего GPU validation window и проверить на текущем HEAD:

- clean installer path;
- `/health/live`;
- `/health/ready`;
- selected hot models;
- chat smoke;
- file-chat smoke;
- TXT / PDF / DOCX / CSV / XLSX / PNG / JPG scenarios;
- negative cases: scanned PDF, malformed PDF, unsupported XLS;
- latency, cold start и warm response;
- отсутствие secrets в artifacts.

## Следующий feature decision

После docs/status sync и live regression plan нужно выбрать ровно один следующий крупный блок:

- PDF OCR v1 live validation;
- или comparison engine.

Оба блока одновременно в рамках следующего шага не планируются.
