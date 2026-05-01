# PDF OCR Design / Audit

## Статус

Этот документ является design/audit планом для будущего внедрения PDF OCR в Corporate AI Assistant.

PDF OCR ещё не реализован. Текущий baseline: PDF с текстовым слоем поддержан, scanned/image-only PDF явно отклоняется controlled error: `PDF не содержит извлекаемого текстового слоя; OCR для PDF пока не поддержан`.

Цель документа - безопасно спроектировать PDF OCR для scanned/image-only PDF без нарушения текущего parser quality gate, существующего text-layer PDF поведения и demo / pilot validation readiness.

Этот документ не является implementation patch, runtime patch, dependency change, live validation report или production certification.

## Текущий PDF Pipeline

Текущий upload/parser entrypoint:

- `parse_uploaded_file(path)` определяет расширение файла;
- для `.pdf` вызывает `extract_text_from_pdf(path)`;
- `extract_documents_from_staging(...)` и `extract_documents_from_shared_staging(...)` проходят через `parse_uploaded_file(...)`;
- parser public cutover использует `worker-parser`, staging root и `prepare_parser_job_artifacts(...)`;
- legacy file-chat path выполняет parsing через `asyncio.to_thread(extract_documents_from_staging, staged_files)`.

Фактический PDF extraction path:

- сначала используется `pypdf.PdfReader`;
- считается `page_count = len(reader.pages)`;
- если `page_count > MAX_PDF_PAGES`, выбрасывается controlled error `PDF-документ превышает лимит страниц`;
- текст собирается через `page.extract_text()`;
- результат проходит через `trim_document_content(...)`;
- если после trim текст пустой, выбрасывается `pdf_no_text_layer_detail()`;
- malformed/invalid PDF map'ится в controlled error `Не удалось извлечь текст из PDF`.

Fallback path:

- в коде есть fallback на `import fitz` и `fitz.open(path)`;
- fallback читает `document[index].get_text()` и применяет тот же page limit;
- `fitz` fallback покрыт unit tests через mock;
- наличие PyMuPDF/`fitz` в runtime dependencies не подтверждено: в audit подтверждены `pypdf`, `pytesseract`, `Pillow` и системный `tesseract-ocr`, но не `PyMuPDF`.

Текущие лимиты, влияющие на PDF:

- `FILE_PROCESSING_MAX_FILE_SIZE_BYTES = 50 MB`;
- `FILE_PROCESSING_MAX_TOTAL_SIZE_BYTES = 500 MB`;
- `FILE_PROCESSING_MAX_FILES = 10`;
- `FILE_PROCESSING_MAX_DOCUMENT_CHARS = 12000`;
- `FILE_PROCESSING_MAX_PDF_PAGES = 20`;
- `PARSER_JOB_TIMEOUT_SECONDS = 300`;
- `PARSER_STAGING_TTL_SECONDS = 3600`.

Текущий scanned/image-only behavior:

- PDF без извлекаемого text layer не идёт в OCR;
- image OCR path не вызывается для PDF;
- тест `test_extract_text_from_pdf_rejects_empty_text_layer_without_ocr` явно защищает этот контракт;
- gold corpus содержит `pdf_scanned_no_text_layer` как expected controlled failure.

## Текущий Image OCR Pipeline

Image OCR уже существует для отдельных image uploads:

- `parse_uploaded_file(path)` отправляет `.png`, `.jpg`, `.jpeg` в `extract_text_from_image(path)`;
- `extract_text_from_image(...)` импортирует `pytesseract` и `PIL.Image`;
- Dockerfile устанавливает системный `tesseract-ocr`;
- `requirements.txt` содержит `pytesseract` и `Pillow`;
- изображение открывается через Pillow;
- перед OCR проверяется `IMAGE_OCR_MAX_DIMENSION`;
- `prepare_image_for_ocr(...)` переводит изображение в grayscale, применяет autocontrast и bounded upscale;
- `pytesseract.image_to_string(...)` вызывается с timeout `IMAGE_OCR_TIMEOUT_SECONDS`;
- результат проходит через `trim_document_content(...)`.

Текущие image OCR лимиты:

- `FILE_PROCESSING_IMAGE_MAX_DIMENSION = 2000`;
- `FILE_PROCESSING_OCR_TIMEOUT_SECONDS = 30.0`;
- `FILE_PROCESSING_MAX_DOCUMENT_CHARS = 12000`;
- общий upload file size и total size limits применяются до parser stage.

Controlled errors:

- oversized image -> controlled dimension error;
- OCR timeout -> controlled timeout error;
- invalid image payload -> controlled image parse error;
- missing OCR/Pillow dependency -> `OCR parser unavailable on server`.

## Gaps

Подтверждённые gaps:

- scanned/image-only PDF OCR не реализован;
- нет page rendering OCR path для PDF;
- нет feature flag для PDF OCR;
- нет отдельных PDF OCR page limits;
- нет отдельного render DPI limit;
- нет отдельного rendered image dimension limit для PDF pages;
- нет total PDF OCR timeout;
- нет OCR language/config knobs для PDF;
- нет confidence/quality metadata;
- нет PDF OCR observability полей: attempted/succeeded/failed pages, timeout count, OCR chars;
- нет positive scanned PDF OCR fixture;
- нет live regression после Office parser patches;
- PyMuPDF/`fitz` как runtime dependency не подтверждён.

Не подтверждено:

- что `fitz` реально доступен в production container;
- что текущий `tesseract-ocr` package содержит нужные language packs кроме default;
- что текущий parser worker pool достаточно изолирован для тяжёлой PDF OCR нагрузки;
- что текущие smoke specs покрывают будущий PDF OCR positive path.

## Recommended Architecture

### Feature Flag

Добавить будущий runtime/config flag:

```text
ENABLE_PDF_OCR=false
```

Default должен оставаться `false`. При `false` текущий controlled error для scanned/image-only PDF сохраняется без изменений.

### Trigger

PDF OCR должен включаться только если обычный text-layer extraction вернул пустой текст или no text layer.

Text-layer PDF не должен идти через OCR. Это нужно сохранить как explicit invariant и покрыть тестом, чтобы не ухудшить latency и качество текущих PDF.

Malformed PDF не должен превращаться в OCR candidate. Если PDF parser не смог открыть документ или document structure broken, ошибка должна оставаться `Не удалось извлечь текст из PDF`.

### Page Rendering

Для OCR нужен безопасный page renderer, но dependency decision должен быть отдельным маленьким шагом.

Рекомендуемый candidate:

- рассмотреть PyMuPDF/`fitz`, потому что в коде уже есть fallback import и unit-level abstraction;
- использовать его для rendering только если dependency будет явно добавлена и принята;
- не добавлять `poppler`, `ghostscript`, `pdf2image` или `ocrmypdf` без отдельного dependency/security решения.

До dependency decision PDF OCR implementation начинать не нужно.

### OCR

PDF OCR page path должен переиспользовать текущий image OCR preprocessing helper, если это возможно без размывания лимитов:

- render limited PDF pages в images;
- проверить rendered image dimensions;
- применить `prepare_image_for_ocr(...)`;
- вызвать `pytesseract.image_to_string(...)` с timeout per page;
- не делать external SaaS/network calls;
- не сохранять OCR text в неожиданных местах вне parser artifacts.

### Limits

Нужны отдельные будущие настройки:

```text
PDF_OCR_MAX_PAGES
PDF_OCR_RENDER_DPI
PDF_OCR_MAX_RENDERED_IMAGE_DIMENSION
PDF_OCR_TIMEOUT_SECONDS_PER_PAGE
PDF_OCR_TOTAL_TIMEOUT_SECONDS
PDF_OCR_MAX_CHARS
PDF_OCR_LANGUAGES
```

Рекомендованный стартовый профиль для v1:

- OCR pages меньше или равен текущему `MAX_PDF_PAGES`;
- render DPI bounded, например 150-200;
- rendered image dimension bounded не выше текущего image OCR guardrail без отдельного решения;
- timeout per page bounded;
- total timeout меньше `PARSER_JOB_TIMEOUT_SECONDS`;
- output всё равно режется через общий `trim_document_content(...)`.

Existing upload limits должны продолжать применяться до rendering.

### Output Format

Рекомендуемый формат extracted text:

```text
PDF OCR Page 1
<ocr text>

PDF OCR Page 2
<ocr text>
```

Если отдельная page OCR failed, допустим controlled note по странице:

```text
PDF OCR Page 3
[PDF_OCR_PAGE_FAILED: timeout]
```

Если все OCR pages failed или результат пустой, вернуть controlled PDF OCR error, а не пустой документ.

### Errors

Ожидаемые будущие error semantics:

- OCR disabled -> текущий `pdf_no_text_layer_detail()`;
- OCR enabled, renderer unavailable -> controlled PDF OCR unavailable error;
- OCR enabled, per-page timeout -> controlled page failure и aggregate result или controlled OCR timeout;
- OCR enabled, no text after OCR -> controlled no OCR text extracted error;
- malformed PDF -> текущий malformed PDF error;
- page count over limit -> текущий page limit error или более строгий PDF OCR page limit error.

### Observability

Добавить будущие parser observability fields без секретов и без raw text:

- `pdf_ocr_enabled`;
- `pdf_page_count`;
- `pdf_ocr_pages_attempted`;
- `pdf_ocr_pages_succeeded`;
- `pdf_ocr_pages_failed`;
- `pdf_ocr_chars`;
- `pdf_ocr_timeout_count`;
- `pdf_ocr_render_ms`;
- `pdf_ocr_total_ms`.

Логи не должны содержать raw OCR text, secrets, cookies, tokens или bootstrap secret contents.

### Security

Security guardrails:

- no external SaaS;
- no network calls from OCR path;
- bounded CPU and memory;
- bounded page count, DPI, dimensions, chars and timeouts;
- cleanup temp images/files;
- no secret values in artifacts/logs;
- raw uploaded files удаляются по текущему staging lifecycle;
- OCR diagnostics должны быть metadata-only;
- PDF bombs, huge embedded images and malformed PDFs должны завершаться controlled error;
- ПДн в OCR text не логировать.

### Backward Compatibility

Default path должен быть backward-compatible:

- `ENABLE_PDF_OCR=false` сохраняет текущий scanned PDF controlled error;
- text-layer PDF tests продолжают проходить;
- malformed PDF tests продолжают проходить;
- image OCR tests продолжают проходить;
- parser quality gate по умолчанию остаётся green;
- `tests/smoke/specs/file_chat_cases.json` не обязан покрывать PDF OCR до отдельного smoke update.

## Phased Implementation Plan

### Phase 1 - Feature Flag And Tests, No OCR Runtime

- добавить config flag `ENABLE_PDF_OCR=false`;
- сохранить current behavior by default;
- добавить tests, доказывающие flag=false path unchanged;
- добавить placeholder branch только для controlled "not implemented/enabled" semantics, если это нужно для будущего шага;
- не добавлять renderer и OCR runtime.

### Phase 2 - Renderer Decision

- выбрать renderer;
- если PyMuPDF/`fitz` принимается, явно добавить dependency в отдельном approved patch;
- если выбирается другой renderer, отдельно описать system packages, security profile and container impact;
- не смешивать dependency patch с OCR logic.

### Phase 3 - OCR Page Path

- render limited pages;
- validate rendered dimensions;
- preprocess page image;
- run `pytesseract` with per-page timeout;
- aggregate page text;
- return controlled errors;
- не делать external calls.

### Phase 4 - Gold Corpus / Parser Quality

- добавить scanned PDF OCR positive fixture;
- оставить current scanned no-text negative для `ENABLE_PDF_OCR=false`;
- добавить parser-only tests for `ENABLE_PDF_OCR=true`;
- OCR-dependent tests можно сделать optional/env-gated, если runtime Tesseract availability нестабилен;
- parser quality gate default должен оставаться deterministic.

### Phase 5 - Live GPU / Validation Window

- включить PDF OCR на validation host только после implementation tests;
- прогнать manual/live scanned PDF cases;
- сохранить artifacts;
- зафиксировать metrics: OCR pages, timeouts, latency, failures;
- report verdict `PASS`, `DEGRADED` или `FAIL`;
- не смешивать с comparison engine.

## Test Plan

Будущие tests:

- text-layer PDF unchanged;
- text-layer PDF не вызывает OCR;
- scanned PDF with flag=false -> current controlled error;
- scanned PDF with flag=true -> simple OCR success;
- PDF OCR page limit;
- PDF OCR render dimension limit;
- per-page OCR timeout;
- total OCR timeout;
- malformed PDF remains malformed PDF error;
- oversized rendered page -> controlled error;
- partial page OCR failure -> aggregate result with controlled note or controlled failure;
- no Tesseract installed -> controlled OCR unavailable error;
- parser quality gate default still green.

## PASS / FAIL Criteria

PASS:

- flag=false default не меняет поведение;
- text-layer PDF не ломается;
- text-layer PDF не уходит в OCR без нужды;
- scanned PDF OCR работает только при flag=true;
- malformed PDF behavior сохраняется;
- timeouts/errors controlled;
- temp files cleanup подтверждён tests/review;
- parser quality gate green.

FAIL:

- text-layer PDF уходит в OCR без нужды;
- parser quality gate ломается;
- OCR висит без timeout;
- unhandled exception;
- temp files leak;
- OCR требует external SaaS/network;
- raw OCR text или secrets появляются в logs/artifacts;
- flag=false меняет текущий scanned PDF controlled error.

## Что НЕ Входит В PDF OCR v1

- OCR внутри DOCX;
- comparison engine;
- table reconstruction from scanned PDFs;
- handwriting recognition;
- layout-perfect extraction;
- multilingual quality guarantee;
- production capacity benchmark;
- heavy load benchmark;
- SOC/SIEM integration.

## Open Questions

- Использовать ли PyMuPDF/`fitz` как renderer?
- Какие language packs нужны для v1: `eng`, `rus` или оба?
- Нужен ли отдельный PDF OCR worker pool или достаточно текущего parser worker pool?
- Где хранить OCR diagnostics: только logs/metadata или отдельный parser artifact?
- Включать ли PDF OCR в default pilot или оставить opt-in?
- Делать ли OCR-dependent tests обязательными или env-gated?

## Следующий Один Шаг

После принятия design выполнить маленький implementation patch Phase 1: feature flag + tests, без реального OCR rendering.

Если нужен более быстрый путь, Phase 1+2 можно объединить только после отдельного approval, потому что renderer dependency меняет runtime/container surface.
