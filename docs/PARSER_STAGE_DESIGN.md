# Parser Stage Design

## Scope

This document is the canonical design for moving heavy file parsing outside the app request path.

It is based on the current implemented file-chat flow confirmed in P3.1 from:

- `app.py`
- `llm_gateway.py`
- `worker.py`
- `tests/test_upload_backend.py`
- `tests/test_file_chat_async_queue.py`

This is a target design document. It does not describe an already implemented parser stage.

## Current State Summary

Current file-chat behavior:

1. `app` receives multipart uploads on `/api/chat_with_files`
2. `app` validates count, extension, content type, and file size
3. `app` stages raw files in a temporary directory
4. `app` parses TXT, DOCX, PDF, and image uploads before queue
5. `app` applies document-budget trimming before queue
6. `app` builds the grounded document prompt before queue
7. `app` enqueues a file-chat job that already contains prompt text
8. `app` cleans temporary upload artifacts

Current queue boundary is therefore late: parsing, OCR, PDF extraction, and document trimming all happen before the LLM job is queued.

## Problem Statement

The current request path is too heavy for safe long-term file handling because it mixes:

- upload receive
- temporary file staging
- parser execution
- OCR execution
- PDF parse fallback logic
- document trimming
- prompt construction
- retry prompt construction
- cleanup
- queue handoff

This creates four architectural risks:

1. latency risk:
   request handlers perform CPU-heavy and I/O-heavy work before enqueue
2. failure-mixing risk:
   upload validation, parser failures, OCR dependency failures, and queue concerns are handled inside one request lifecycle
3. cleanup ownership risk:
   temporary staging cleanup is tightly coupled to request success/failure instead of a dedicated processing stage
4. queue-boundary risk:
   workers never see raw-file lifecycle, only already-built prompt text, so parser retry and parser observability are mixed with app behavior

## Design Goals

- move heavy parsing, OCR, and PDF processing out of the app request path
- keep the app responsible only for minimal safe validation and controlled staging
- introduce a clear parser-stage queue boundary before LLM inference
- keep raw files out of the LLM worker path
- make staging lifecycle and cleanup ownership explicit
- make parser failure, retry, and observability explicit
- stay compatible with the current Redis + scheduler + worker architecture
- minimize rollout risk by preserving the current queue/control-plane model

## Non-Goals

- no external RAG subsystem
- no durable document database
- no raw file bytes in Redis
- no redesign of the current auth/session model
- no runtime implementation in this step
- no attempt to make current app-side parsing "slightly better" instead of moving it out

## Evaluated Options

### Option A: Dedicated Parser Worker That Handles Full File Jobs End-to-End

Idea:

- `app` stages files and enqueues one raw-file job
- a dedicated parser worker parses files and also performs final LLM inference itself

Strengths:

- removes heavy parsing from the request path
- one async worker path owns the whole file-chat lifecycle

Weaknesses:

- parsing and inference remain coupled inside one worker role
- OCR/PDF CPU spikes can contend directly with LLM execution capacity
- queue observability remains mixed because parser-stage and inference-stage terminal states are still one job
- cleanup and retry semantics remain blurred inside one worker lifecycle

Fit for current repo:

- partially compatible with the current control plane
- weaker fit for the current worker model, because current workers are inference-oriented and build Ollama messages, not file-processing pipelines

Status:

- reject

### Option B: Separate Parser Queue Stage, But Reuse the Existing Chat Worker Pool

Idea:

- `app` stages files and enqueues a parser job
- existing worker infrastructure is extended so the same worker pool can execute parser jobs and then enqueue LLM jobs

Strengths:

- preserves the current queue/scheduler model
- creates an earlier queue boundary than today
- fewer new deployment roles than a fully separate parser service

Weaknesses:

- parser jobs and LLM jobs still compete for the same worker capacity
- OCR/PDF parsing can delay inference jobs
- worker responsibility becomes mixed
- parser isolation is weaker than a dedicated parser role

Fit for current repo:

- viable as an intermediate migration step
- not the best steady-state fit for clean responsibility boundaries

Status:

- viable, but not recommended as the target design

### Option C: Dedicated Parser Stage With Parser Job, Parser Worker, and Downstream LLM Job

Idea:

- `app` performs only minimal validation and controlled staging
- `app` enqueues a parser job
- a dedicated parser worker reads staged files, extracts text, applies document-level trimming, and constructs the grounded prompt
- the parser worker then enqueues the downstream LLM job
- LLM workers receive only prompt/history/file metadata, not raw files

Strengths:

- moves heavy parsing fully out of the request path
- creates a clear queue boundary before inference
- keeps raw files out of LLM workers
- gives explicit ownership for parser retry, parser timeout, staging cleanup, and parser observability
- fits the existing queue/scheduler/worker architecture with the smallest architectural surprise

Weaknesses:

- introduces a new job kind and worker role
- needs parent/child job tracking between parser jobs and LLM jobs
- requires a controlled staging artifact layer rather than request-local temp directories

Fit for current repo:

- best fit
- it reuses the current Redis job model, scheduler, and worker lifecycle, but separates parser and inference responsibilities cleanly

Status:

- recommended

## Architectural Decision

Recommended design:

- introduce a dedicated parser stage before LLM inference
- implement it as a new parser job kind processed by a dedicated parser worker role
- keep LLM workers inference-only

This means the target file-chat architecture is:

1. app performs minimal validation and controlled staging
2. app enqueues parser job
3. parser worker parses and trims documents
4. parser worker enqueues downstream LLM job
5. LLM worker performs inference
6. parser-owned staging artifacts are cleaned according to parser/LLM terminal state rules

Why this is the best fit now:

- the repository already has a queue/scheduler/worker control plane
- the current main problem is that parsing happens too early, before queue
- the current workers already assume prompt-based inference, so keeping them prompt-only minimizes implementation risk
- a dedicated parser role gives the cleanest place for OCR, PDF fallback logic, parser timeouts, and staging cleanup ownership

## Target Flow

### Future Target Sequence

1. request arrives at `/api/chat_with_files`
2. app validates:
   - auth
   - CSRF
   - rate limit
   - file count
   - extension/content type pair
   - file size
3. app creates a controlled staging record
4. app writes raw uploads into a controlled staging artifact layer
5. app enqueues parser job
6. parser worker loads staged raw files
7. parser worker performs per-type extraction:
   - TXT
   - DOCX
   - PDF
   - OCR for supported images
8. parser worker applies document extraction limits and document-context trimming
9. parser worker builds:
   - final grounded prompt
   - retry prompt if needed
   - sanitized file metadata
10. parser worker enqueues downstream LLM job
11. parser worker deletes raw staged files when they are no longer needed
12. LLM worker performs inference using prompt/history only
13. terminal cleanup removes any remaining parser-stage artifacts

### Line of Responsibility

- app:
  receive, validate, stage, enqueue parser job
- parser stage:
  type-aware extraction, OCR, PDF parsing, document trimming, prompt assembly, parser observability, raw-file cleanup ownership
- LLM stage:
  history budget, final total prompt budget, inference, response generation

## Trust Boundaries

### App Is Allowed To

- accept uploads
- sanitize filenames
- enforce file count/type/size rules
- write raw files into a controlled staging area
- enqueue parser jobs

### App Must Not Do

- OCR
- PDF parsing
- DOCX extraction
- prompt assembly from extracted file content
- parser retry logic

### Parser Stage Is Allowed To

- read staged raw files
- run TXT/DOCX/PDF/image parsers
- apply document extraction limits
- build grounded file-chat prompt
- emit parser-stage observability
- decide parser terminal status and parser cleanup
- enqueue downstream LLM job

### LLM Workers Must Not Do

- read raw files
- inspect staging paths
- run OCR
- run PDF/DOCX parsers
- own raw staging cleanup

### Raw File Boundary

- raw file bytes remain inside the staging layer and parser stage only
- raw file bytes must never be serialized into Redis jobs

### Extracted Text Boundary

- extracted text belongs to parser stage
- downstream LLM workers should receive only the prompt contract they need

## Staging Model

## Recommended Model

Use a controlled staged artifact layer instead of request-local `TemporaryDirectory`.

Recommended target properties:

- shared staging root mounted for `app` and parser worker
- no staging mount in regular LLM workers
- staging object identified by `staging_id`, not by absolute host path in queue payloads
- raw files stored under a parser-owned staging namespace
- parser-generated metadata stored separately from raw files

Example logical structure:

- `staging/<staging_id>/raw/<sanitized-file>`
- `staging/<staging_id>/meta/request.json`
- `staging/<staging_id>/meta/parser.json`

### Lifecycle Rules

- app creates staging record and raw files
- parser stage owns staged raw-file lifecycle after enqueue
- on parser failure:
  - keep staging long enough for bounded retry / inspection
  - mark parser terminal failure explicitly
- on successful LLM-job enqueue:
  - raw files should be deleted as soon as no parser retry requires them
- orphan protection:
  - add TTL-based janitor cleanup for abandoned staging IDs

### Why Not Request-Local Temp Directories

Request-local temp directories are appropriate only while parsing happens in the app itself. Once parsing moves to another async stage, raw files need a controlled handoff boundary rather than process-local temp state.

## Payload Design

### Parser Job Input Payload

Required fields:

- `job_kind=parse`
- `request_id` or root file-chat job id
- `username`
- `requested_model`
- `message`
- `history_snapshot` or history reference
- `staging_id`
- sanitized file metadata:
  - display name
  - sanitized storage name
  - size
  - normalized content type

Must not include:

- raw file bytes
- absolute local temp paths
- extracted text

### Parser Job Output Payload

Parser stage should produce:

- parser terminal status
- extracted document summary metrics
- final grounded prompt
- retry prompt
- sanitized file metadata for user-visible response / observability
- downstream LLM enqueue request

### LLM Job Input Payload

Required fields:

- `job_kind=file_chat`
- `username`
- resolved model info
- grounded `prompt`
- trimmed `history`
- `file_chat` metadata:
  - `retry_prompt`
  - `files: [{name, size}]`
  - optional parser provenance fields such as `parser_job_id` or `staging_id`

Must not include:

- raw file bytes
- raw-file staging paths
- parser-only local filesystem details

### Queue Visibility Rules

- raw file bytes must never go into Redis
- absolute staged file paths should not be queue-visible
- queue-visible file reference should be `staging_id` only
- only parser workers may resolve `staging_id` into physical file paths

## File-Type Handling Ownership

- TXT:
  - target owner: parser stage
  - reason: still part of document extraction, even if lightweight
- DOCX:
  - target owner: parser stage
  - reason: XML extraction is file parsing, not request validation
- PDF:
  - target owner: parser stage
  - reason: parser chain and page-loop logic are exactly the heavy path to remove from request handling
- images/OCR:
  - target owner: parser stage
  - reason: OCR is the highest-risk CPU path and should never remain in the request handler

App should only validate file metadata and stage bytes. LLM workers should consume prompt-only payloads.

## Trimming Ownership

Recommended ownership split:

- per-file extraction limits:
  - parser stage
- parser-specific limits such as PDF page count and OCR preprocessing:
  - parser stage
- cumulative document-context limit:
  - parser stage
- final total prompt budget across history + prompt:
  - LLM gateway / LLM stage

This removes the current conceptual duplication where document trimming is split across app helpers and then prompt trimming runs again at LLM preparation time.

### Final Prompt Assembly

Final grounded document prompt should be assembled in parser stage, not in app.

Reason:

- parser stage owns extracted document text
- parser stage is the right boundary for file-derived prompt construction
- LLM workers should remain prompt consumers, not file interpreters

## Failure, Retry, and Observability Model

### Parser Failure Classes

- validation rejection before parser enqueue
- parser dependency missing
- malformed file
- parser timeout
- OCR failure
- PDF parse failure
- partial extraction with bounded success

### Retry Model

- app should not retry parsing synchronously
- parser-stage retry should be explicit and bounded
- parser retries should not recreate uploads from the browser
- downstream LLM retry remains separate and should only use parser-produced prompt artifacts

### Cleanup Ownership

- app owns cleanup only if staging creation fails before parser enqueue
- parser stage owns raw staging cleanup after parser enqueue
- janitor owns stale orphan cleanup by TTL

### Minimal Observability Signals

- parser queue depth
- parser queue wait ms
- parser execution ms
- parse failure type
- file count
- parser success/failure by type
- staging cleanup success/failure
- downstream LLM enqueue success/failure

## Security and Safety Design

- path traversal:
  - keep current sanitized filename behavior
  - never trust original browser filename for physical storage path
- content-type spoofing:
  - keep extension + normalized content-type gate in app pre-validation
- oversized files:
  - reject in app before parser enqueue
- parser crash containment:
  - isolate parser execution from the web request path
- OCR/PDF isolation:
  - keep OCR and parser libraries confined to parser stage, not app request handling and not LLM workers
- no raw file leakage:
  - no raw bytes in queue
  - no raw-file access in chat workers
- data minimization:
  - delete raw staged files once parser retry no longer requires them

## Migration Plan

### Phase 0: Docs and Decision

- change scope:
  - design docs only
- compatibility strategy:
  - none required
- rollback strategy:
  - none required
- risk:
  - low

### Phase 1: Introduce Parser Job Schema

- change scope:
  - add parser job kind, parser payload contract, and parent/child job linkage
- compatibility strategy:
  - keep current app-side parsing as active path behind existing file-chat endpoint
- rollback strategy:
  - disable parser job creation and keep legacy path
- risk:
  - medium

### Phase 2: Move Parsing Out of App Path

- change scope:
  - app performs only minimal validation + controlled staging + parser enqueue
  - parser worker performs extraction and enqueues LLM job
- compatibility strategy:
  - retain current file-chat response contract while root job id maps to parser/LLM stages
- rollback strategy:
  - route file-chat back to legacy app-side parsing if parser stage is disabled
- risk:
  - medium-high

### Phase 3: Remove Legacy App-Side Parsing

- change scope:
  - remove parser helpers from request path
  - keep only app-side validation/staging
- compatibility strategy:
  - parser stage becomes canonical path
- rollback strategy:
  - revert to Phase 2 release if parser rollout is unstable
- risk:
  - medium

### Phase 4: Cleanup and Observability Hardening

- change scope:
  - add janitor/sweeper for staged artifacts
  - add parser-specific counters, timings, and failure metrics
  - remove temporary compatibility shims
- compatibility strategy:
  - additive hardening
- rollback strategy:
  - disable janitor or parser-specific metrics paths without changing core flow
- risk:
  - low-medium

## Likely Implementation Impact

Expected implementation-step changes are likely to touch:

- `app.py`
- `llm_gateway.py`
- `worker.py`
- `config.py`
- upload/file tests
- queue/scheduler tests
- architecture and operations docs
- a new parser worker module or parser job handler

This forecast is included only to scope future work. It is not an implementation patch.

## Final Recommendation

Adopt Option C as the target architecture:

- app performs minimal validation and controlled staging only
- parser jobs become the first async boundary for file-chat
- a dedicated parser worker owns extraction, OCR, PDF parsing, document trimming, prompt assembly, and raw-file cleanup
- downstream LLM jobs remain prompt-only and inference-only

This is the clearest way to remove heavy file processing from the request path while staying aligned with the repository's current Redis + scheduler + worker architecture.
