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
- file upload staging and document parsing
- health endpoints
- SSE event streaming to the browser

For file chat, the app performs upload staging and text extraction before the job is queued. Model inference is executed by workers, not directly in the request handler.

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
2. the app stages uploads in a temporary directory
3. safe filename handling and upload validation run before parsing
4. document text is extracted from supported file types
5. document context governance trims oversized document payloads
6. a file-aware job is enqueued into the same queue/worker lifecycle
7. the worker performs grounded inference through the regular model path
8. temporary upload artifacts are cleaned up

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

### Job state

Job state is stored in Redis and includes:

- pending / admitted / running / completed / failed / cancelled status
- target assignment
- lease and heartbeat-related metadata
- event stream entries used by SSE consumers

### Uploaded files

Uploaded files are staged temporarily for parsing. The repository does not implement a durable attachment store.

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

- parse timing
- queue wait timing
- inference timing
- total job timing
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
- async file chat through the queue/worker path
- PDF/text/docx/image document extraction
- CPU/GPU routing readiness with CPU fallback
- Redis-backed chat history and job state
- baseline upload validation and structured observability logs

### Planned or not yet implemented

- dedicated persistent database for chat history
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
- [README.md](../README.md)
