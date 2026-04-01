# Architecture

## Scope

This document describes the currently implemented architecture of Corporate AI Assistant. It focuses on what exists in the repository today and explicitly distinguishes implemented behavior from planned work.

## System Overview

Corporate AI Assistant is a Docker Compose deployment made of:

- `nginx` for HTTPS ingress
- `app` for the FastAPI web/API plane
- `sso-proxy` for internal Kerberos/SPNEGO validation behind the reverse proxy
- `scheduler` for admission control and stale-job recovery
- `worker-chat`, `worker-siem`, and `worker-batch` for workload execution
- optional `worker-gpu` for GPU-targeted chat execution
- `redis` for chat history, rate limiting, queues, heartbeats, leases, job state, and event streams
- `ollama` for local model inference

External dependencies:

- Active Directory / Kerberos / LDAP
- browser clients over HTTPS

## Component Responsibilities

### `nginx`

- terminates TLS
- exposes ports `80` and `443`
- forwards regular traffic to the FastAPI app
- handles the dedicated `/auth/sso/login` entry through `auth_request`
- clears reserved identity headers on the normal application path

### `sso-proxy`

The `sso-proxy` service is an internal helper used only for trusted reverse-proxy SSO:

- receives `Authorization: Negotiate ...` from Nginx on the internal auth subrequest
- validates Kerberos/SPNEGO with the configured HTTP service keytab
- resolves user identity and AD groups through the existing Kerberos/LDAP integration
- returns normalized identity headers back to Nginx

It is not exposed directly to browser clients.

### `app`

The FastAPI application handles:

- login and session lifecycle
- Kerberos/LDAP-backed authentication integration
- CSRF enforcement
- password-based session issuance with rotated refresh tokens
- SSO-based session issuance from proxy-validated identity on the dedicated `/auth/sso/login` path
- canonical identity normalization for `DOMAIN\\user`, `user@REALM`, and plain usernames
- model selection and runtime model resolution through an explicit folder-based policy catalog (`model_policies/`)
- regular chat request intake
- file upload staging, parser jobs, and document processing
- health endpoints
- SSE event streaming to the browser

For file chat, the fresh-install baseline uses a parser-stage path: `app` performs validation and controlled staging, enqueues a parser root job, `worker-parser` prepares grounded document artifacts, and a downstream worker performs inference. The legacy app-side parsing path remains as a fallback only when the parser public cutover is disabled.

The parser-stage architecture and its design rationale are documented in [PARSER_STAGE_DESIGN.md](PARSER_STAGE_DESIGN.md).

The main app does not perform raw Kerberos/SPNEGO negotiation. Instead, it accepts trusted identity headers only on the dedicated SSO entry path and only when trusted proxy mode is enabled. Password login remains available as a fallback auth source.

The policy catalog is not a model storage directory. It only defines which exact model keys belong to which internal categories. Category access is resolved separately from `.env` group mapping: authenticated users receive `general`, while `coding` and `admin` are opened only by exact AD group matches from `MODEL_ACCESS_CODING_GROUPS` and `MODEL_ACCESS_ADMIN_GROUPS`. Users still choose a model manually from the allowed set returned by `/api/models`.

### `scheduler`

The scheduler is a dedicated runtime process that:

- maintains fresh scheduler heartbeat state
- evaluates workload capacity
- moves jobs from pending queues to dispatch queues
- requeues stale jobs when needed

It is part of the control plane, not the web/API plane.

### `worker-chat`, `worker-siem`, `worker-batch`

Workers:

- publish worker heartbeats
- claim jobs from the dispatch queues
- enforce target-kind compatibility
- build model messages from job history and prompts
- call Ollama
- emit job events and terminal job status

The repository currently uses one worker implementation with workload-specific configuration via environment variables.

### `worker-parser`

`worker-parser` is the dedicated parser pool for file-chat root jobs. It:

- reads raw uploads from the shared parser staging area
- performs TXT/DOCX/PDF/image extraction
- enforces parser-side file-processing limits and budgets
- emits parser-stage observability
- enqueues the downstream LLM child job
- cleans raw staged files when they are no longer needed

### `worker-gpu`

`worker-gpu` is an optional Compose profile. It is meant to process `target_kind=gpu` chat jobs when:

- the `gpu` profile is enabled
- the host provides working GPU container support
- GPU-targeted routing is enabled

If GPU routing is requested but no GPU worker is active, the current implementation falls back to CPU.

### `redis`

Redis is the current control plane and lightweight storage layer. It is used for:

- chat history
- rate limiting
- login/logout token state
- job payloads and job status
- queue state
- dispatch and processing queues
- scheduler and worker heartbeats
- event streams

### `ollama`

Ollama is the local inference runtime. The application expects at least one model to be installed there.

## Request Paths

### Regular chat path

1. the browser sends a chat request to `app`
2. the app validates auth, CSRF, and rate limits
3. chat history is loaded from Redis and trimmed by history governance
4. a job is enqueued through the LLM gateway
5. the scheduler admits the job to a target
6. a worker claims the job and performs inference through Ollama
7. job events are streamed back to the browser
8. terminal state is stored in Redis and the assistant reply is appended to chat history

### SSO login path

1. the user opens the login page and explicitly chooses the SSO entry path
2. `nginx` performs an internal auth subrequest to `sso-proxy`
3. `sso-proxy` validates the Kerberos/SPNEGO negotiation and resolves AD-backed identity
4. `nginx` forwards only the validated internal identity headers to `app`
5. `app` normalizes the identity through the same session contract used by password login
6. `app` issues its normal access/refresh cookies with `auth_source=sso`
7. subsequent `/api/models`, `/api/switch-model`, chat, and file-chat requests use the regular cookie/session flow

### File-chat path

1. the browser uploads files and a user request to `app`
2. the app validates file count, file size, total size, extension, and content-type
3. if parser public cutover is enabled, the app writes uploads into the shared parser staging area and enqueues a parser root job
4. `worker-parser` extracts document text from supported file types, enforces parser-side limits, applies document trimming, and enqueues the downstream LLM child job
5. a regular worker performs grounded inference through the standard model path
6. root/child terminal state is mirrored back to the browser-facing file-chat contract
7. raw staged artifacts are cleaned according to parser lifecycle rules

Legacy fallback:

- when parser public cutover is disabled, the app keeps the older request-local staging and parsing path
- non-file chat never uses the parser path

Important characteristics:

- there is no separate RAG subsystem
- there is no external document database
- extracted document text is used inside the current job lifecycle

## Supported File Types

The currently implemented file parsing path supports:

- `.txt`
- `.pdf`
- `.docx`
- `.png`
- `.jpg`
- `.jpeg`

PDF extraction uses a parser chain already present in the application runtime. Image files use the OCR path built into the container image.

## Data and Storage Model

### Chat history

Chat history is currently stored in Redis through `AsyncChatStore`.

Current properties:

- bounded history retention
- no separate SQL database
- no long-term archival backend in this repository
- the primary history model is already per-thread: `chat:{username}:{thread_id}`
- the backend maintains a server-side thread registry and uses it as the source of truth for thread list bootstrap
- the UI thread list and active-thread bootstrap are already synchronized with backend truth through `/chat`, `GET /api/threads`, `POST /api/threads`, and `GET /api/threads/{thread_id}/messages`
- legacy `chat:{username}` remains only as a compatibility/migration bridge for the explicit `default` thread
- the bridge is deterministic: on the first `default` thread bootstrap/read/write/list, the legacy bucket is moved into `chat:{username}:default`, the old key is deleted, and no repeated re-migration occurs
- for the next durable storage step, PostgreSQL is selected as the target persistent relational database; the current runtime still remains Redis-based and DB integration is not implemented yet
- the ownership split for the next storage step is fixed separately: Redis remains the owner of queue/control-plane/transient state, while the persistent relational DB is the target durable owner for dialog/message/meta entities
- the quota direction for the next policy/storage step is also defined separately: current rate limiting and queue admission already exist, but they are not treated as a full quota platform
- the queue/concurrency control direction for the next reliability step is also fixed separately: current queue backpressure, scheduler admission, timeout/cancel/recovery, and observability already exist, but part of the control contract remains topology-derived and is only now being formalized at the docs level
- the operator dashboard direction for the next operations step is also fixed separately: the current runtime already exposes health/readiness, queue depth, active jobs, and queue-wait surfaces, but this is still not equivalent to a ready operator KPI dashboard
- a session-scoped active-thread pointer plus archive/restore as platform capabilities are still not implemented

The target server-side thread/session model for the next implementation step is defined in [THREAD_SESSION_MODEL.md](THREAD_SESSION_MODEL.md), the storage direction is defined in [PERSISTENT_STORAGE_DIRECTION.md](PERSISTENT_STORAGE_DIRECTION.md), the ownership split is defined in [STORAGE_OWNERSHIP_SPLIT.md](STORAGE_OWNERSHIP_SPLIT.md), the quota direction is defined in [QUOTA_MODEL_DIRECTION.md](QUOTA_MODEL_DIRECTION.md), the queue/concurrency control direction is defined in [QUEUE_CONCURRENCY_CONTROL_DIRECTION.md](QUEUE_CONCURRENCY_CONTROL_DIRECTION.md), and the operator dashboard direction is defined in [OPERATOR_DASHBOARD_DIRECTION.md](OPERATOR_DASHBOARD_DIRECTION.md).

### Job state

Job state is stored in Redis and includes:

- pending / admitted / running / completed / failed / cancelled status
- target assignment
- lease and heartbeat-related metadata
- event stream entries used by SSE consumers

### Uploaded files

Uploaded files are staged temporarily for parsing. The parser path uses a shared staging root mounted into `app` and `worker-parser`; the repository does not implement a durable attachment store.

## Context Governance

The current implementation includes prompt-size governance:

- history is trimmed separately
- document context is trimmed separately
- final prompt size is trimmed separately

This is intended to prevent uncontrolled prompt growth while preserving user intent and document labels as much as possible.

## CPU/GPU Routing Readiness

The repository includes a basic CPU/GPU routing layer:

- default mode is CPU
- `GPU_ENABLED=true` requests GPU routing
- workers expose their `target_kind`
- jobs carry `target_kind`
- if no GPU worker is available, the gateway downgrades the job to CPU

Current limits:

- there is no auto-detection of GPU capability for routing decisions
- GPU success depends on the host being able to start GPU-enabled containers

## Observability Baseline

The repository now exposes a baseline observability model through:

- health endpoints
- structured application logs
- structured worker logs
- queue and terminal job logs

Current examples include:

- upload receive timing
- parse timing
- queue wait timing
- inference timing
- total job timing
- file count and document character counts
- routing target
- normalized error types

No full metrics stack is packaged in the repository.

## Implemented vs Planned

### Implemented

- Docker Compose-based deployment
- AD/Kerberos/LDAP authentication path
- proxy-terminated AD SSO with password fallback
- queue/scheduler/worker control plane
- regular SSE chat
- async file chat through parser root jobs plus downstream queue/worker inference
- PDF/text/docx/image document extraction
- dedicated `worker-parser` service with shared parser staging
- file-processing limits, budgets, and malformed/heavy-file controlled failures
- CPU/GPU routing readiness with CPU fallback
- Redis-backed chat history and job state
- baseline upload validation and structured observability logs

### Planned or not yet implemented

- runtime integration of a dedicated persistent relational database for dialog/message/meta entities
- a runtime boundary between durable conversation/meta storage and the Redis control plane
- a dedicated runtime quota layer with per-user/per-group enforcement
- server-side thread/session storage model implementation
- HA Redis / Sentinel profile
- packaged external monitoring stack
- antivirus or sandbox-based file scanning
- standalone RAG subsystem
- Kubernetes deployment artifacts

## Related Documents

- [Install Guide](INSTALL_en.md)
- [Administration and Operations](ADMIN_en.md)
- [Troubleshooting](TROUBLESHOOTING_en.md)
- [Security Baseline](SECURITY_en.md)
- [Server-side thread/session model](THREAD_SESSION_MODEL.md)
- [README.md](../README.md)
