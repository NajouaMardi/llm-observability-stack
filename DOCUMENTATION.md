# LLM Observability Stack — Full Documentation

**Version:** 1.0  
**Date:** April 2026  
**Stack:** Bifrost · Langfuse v3 · ClickHouse · MinIO · Ollama · Redis Stack · PostgreSQL

---

## Table of Contents

1. [Production Readiness Assessment](#1-production-readiness-assessment)
2. [Architecture](#2-architecture)
3. [Services Reference](#3-services-reference)
4. [First-Time Setup](#4-first-time-setup)
5. [Sending Requests](#5-sending-requests)
6. [Bifrost Configuration In Depth](#6-bifrost-configuration-in-depth)
   - 6.1 [Providers & API Keys](#61-providers--api-keys)
   - 6.2 [Routing Rules & Fallback Chains](#62-routing-rules--fallback-chains)
   - 6.3 [Semantic Cache](#63-semantic-cache)
   - 6.4 [OpenTelemetry Tracing](#64-opentelemetry-tracing)
7. [Monitoring & Alerting](#7-monitoring--alerting)
8. [Langfuse Observability](#8-langfuse-observability)
9. [Data Export](#9-data-export)
10. [Database Access](#10-database-access)
11. [ClickHouse Single-Node Setup](#11-clickhouse-single-node-setup)
12. [Data Retention](#12-data-retention)
13. [Useful Commands](#13-useful-commands)
14. [Troubleshooting](#14-troubleshooting)
15. [Production Enhancement Options](#15-production-enhancement-options)
16. [Known Limitations](#16-known-limitations)

---

## 1. Production Readiness Assessment

### Verdict

**This stack is production-ready for low-to-medium traffic self-hosted deployments.** It is fully functional, all services are wired together, and the stack has been verified end-to-end including fallback routing, semantic caching, OTEL tracing, and Discord alerting.

### What is hardened

| Area | Status |
|---|---|
| Health checks on all services | All containers have Docker healthchecks |
| Dependency ordering | Bifrost waits for DB, Redis, Ollama, and Langfuse to be healthy before starting |
| Persistent state | All data is stored in named Docker volumes — survives container restarts |
| Provider fallback routing | Configured, tested, and verified end-to-end |
| Semantic caching | Active with correct vector index dimension (768) |
| Distributed tracing | OTEL → Langfuse v3 verified working |
| Real-time alerting | Discord alerts for health, errors, latency, cost, fallbacks, budgets |
| ClickHouse single-node | Built-in Keeper configured — no external ZooKeeper needed |
| MinIO export URLs | `MINIO_SERVER_URL` configured for browser-accessible presigned links |
| Restart policies | `restart: unless-stopped` on all stateful services |

### What requires hardening before internet-facing deployment

| Gap | Risk | Recommended Fix |
|---|---|---|
| Bifrost DB credentials hardcoded as `bifrost`/`bifrost` | DB accessible with known credentials if network is breached | Move to `.env` with strong randomised passwords |
| No TLS/HTTPS on any service | Traffic in plaintext between clients and gateway | Add Nginx or Traefik reverse proxy with Let's Encrypt |
| No container resource limits | A runaway container (e.g. ClickHouse) can starve others | Add `deploy.resources.limits` in `docker-compose.yml` |
| No backup strategy | Volume loss = permanent data loss | Schedule `pg_dump`, MinIO bucket snapshots |
| Ollama models manually pulled after reset | Stack boots without embedding model after full reset | Document or automate the `ollama pull` step |
| MinIO is single-node | Blob storage is a single point of failure | Use managed S3 (AWS/GCS/Azure) for critical deployments |
| All services on one Docker network | No network isolation | Separate into frontend/backend networks |

---

## 2. Architecture

```
Your Application
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                   Bifrost Gateway :8080                   │
│                                                          │
│  • OpenAI-compatible REST API                            │
│  • CEL-based routing rules with ordered fallback chains  │
│  • Semantic cache (Redis Stack + nomic-embed-text/768d)  │
│  • Full request/response logging → Postgres              │
│  • OTEL trace export → Langfuse v3                       │
└──────────┬───────────────────────────┬────────────────────┘
           │                           │
  ┌────────▼────────┐       ┌──────────▼──────────────────────────────┐
  │  LLM Providers  │       │  Langfuse v3 :3001                       │
  │                 │       │                                          │
  │  OpenAI         │       │  langfuse-web    — UI, API, OTEL ingress │
  │  Gemini         │       │  langfuse-worker — async event processor │
  │  OpenRouter     │       │  langfuse-db     — Postgres metadata     │
  │  Ollama (local) │       │  clickhouse      — trace/event store     │
  └─────────────────┘       │  langfuse-redis  — job queue             │
                            │  minio           — blob/export store     │
                            └──────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                 bifrost-monitor (sidecar)                 │
│  Polls Bifrost every 60s                                 │
│  Sends Discord alerts on threshold breach:               │
│  health · errors · latency · cost · fallbacks · budgets  │
└──────────────────────────────────────────────────────────┘

Supporting infrastructure:
  bifrost-db     — Postgres (Bifrost logs, config, routing rules)
  bifrost-redis  — Redis Stack (semantic cache vector index)
  adminer :8081  — Database admin UI
```

### Data Flow

1. App sends request to `http://bifrost:8080/v1/chat/completions`
2. Bifrost evaluates routing rules (CEL expressions)
3. Semantic cache is checked — if hit, response returned immediately
4. If cache miss, request forwarded to primary provider
5. If primary fails → automatic fallback to next provider in chain
6. Response returned to app; request logged to Postgres; OTEL span sent to Langfuse
7. Langfuse worker ingests span from MinIO into ClickHouse
8. Monitor sidecar polls metrics and fires Discord alerts on threshold breach

---

## 3. Services Reference

| Service | Port | Image | Description |
|---|---|---|---|
| **bifrost** | 8080 | `maximhq/bifrost:latest` | LLM gateway — all requests go here |
| **langfuse-web** | 3001 | `langfuse/langfuse:3` | Observability UI, REST API, OTEL endpoint |
| **langfuse-worker** | — | `langfuse/langfuse-worker:3` | Async event processor and export runner |
| **minio** (S3 API) | 9000 | `minio/minio:latest` | S3-compatible blob store |
| **minio** (Console) | 9001 | `minio/minio:latest` | MinIO management UI |
| **ollama** | 11434 | `ollama/ollama:latest` | Local LLM runtime (embeddings) |
| **adminer** | 8081 | `adminer:latest` | Database admin UI |
| bifrost-db | — | `postgres:16-alpine` | Bifrost data: logs, config, keys, rules |
| langfuse-db | — | `postgres:16-alpine` | Langfuse metadata: users, projects, prompts |
| bifrost-redis | — | `redis/redis-stack:latest` | Vector index for semantic cache |
| langfuse-redis | — | `redis:7-alpine` | Job queue for langfuse-worker |
| clickhouse | — | `clickhouse/clickhouse-server:24.12-alpine` | Trace and event storage |
| bifrost-monitor | — | custom (./monitor) | Discord alerting sidecar |
| minio-init | — | `minio/mc:latest` | One-shot: creates MinIO buckets on first boot |

---

## 4. First-Time Setup

### Why two phases?

Bifrost needs a Langfuse API key (`LANGFUSE_AUTH`) to send OTEL traces. But Langfuse must be running before you can generate that key. This creates a chicken-and-egg dependency that requires a two-phase startup:

1. Start Langfuse → generate the API key → add it to `.env`
2. Start the full stack including Bifrost

> **Critical rule:** Bifrost reads `data/config.json` and seeds its database from `.env` **exactly once on first startup**. If `.env` is incomplete at that point, missing values won't be picked up until a full reset (`docker compose down -v`). Always have `.env` complete before first boot.

---

### Phase 1 — Start Langfuse and generate the API key

**Step 1 — Create `.env`** with all values except `LANGFUSE_AUTH`:

```env
# LLM Provider Keys
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...

# Langfuse
LANGFUSE_SALT=<random-32-char-string>
NEXTAUTH_SECRET=<random-32-char-string>

# ClickHouse
CLICKHOUSE_PASSWORD=<strong-password>

# MinIO
MINIO_ACCESS_KEY=minio-admin
MINIO_SECRET_KEY=<strong-password>

# Discord (optional)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Generate secure random strings on Windows PowerShell:
```powershell
[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

**Step 2 — Start Langfuse dependencies only:**

```bash
docker compose up -d langfuse-db langfuse-web clickhouse langfuse-redis minio minio-init
```

Wait ~30 seconds for all services to be healthy.

**Step 3 — Create a Langfuse API key:**

1. Open **http://localhost:3001**
2. Register an account (self-hosted — no external service)
3. Create an Organization and a Project
4. Go to **Settings → API Keys → Create new API key**
5. Copy the **Public Key** (`pk-lf-...`) and **Secret Key** (`sk-lf-...`)

**Step 4 — Base64-encode the key pair and add to `.env`:**

```bash
# Linux / Mac:
echo -n "pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY" | base64

# Windows PowerShell:
[Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY"))
```

Add the result to `.env`:
```env
LANGFUSE_AUTH=Basic <base64-output>
```

---

### Phase 2 — Start the full stack

```bash
docker compose up -d
```

Bifrost starts last — it waits for bifrost-db, bifrost-redis, ollama, and langfuse-web to be healthy. First full startup takes ~60 seconds.

**Verify:**
```bash
docker compose ps          # all services should show "Up" or "healthy"
curl http://localhost:8080/health   # should return {"status":"ok"}
```

**Pull the Ollama embedding model** (required for semantic cache — must be done once after every full reset):

```bash
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text
```

---

## 5. Sending Requests

Bifrost exposes an **OpenAI-compatible API** on port `8080`. Use `provider/model` format in the `model` field.

### curl

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="any-value"  # Required by SDK but ignored — Bifrost uses its own keys
)

response = client.chat.completions.create(
    model="openai/gpt-4o",   # provider/model format
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### Available Models Used For Testing

| Request Format | Provider | Notes |
|---|---|---|
| `openai/gpt-4o` | OpenAI | Has fallback chain configured |
| `openrouter/meta-llama/llama-4-maverick` | OpenRouter | Fallback #1 for gpt-4o |
| `gemini/gemini-2.0-flash` | Gemini | No fallback chain by default |
| `ollama/llama3.2:1b` | Ollama (local) | Fallback #2 for gpt-4o, free, no API key |
| `ollama/nomic-embed-text` | Ollama (local) | Embeddings only — used internally by semantic cache |

To add a new model: add it to the provider's `keys[].models` array in `data/config.json`, clear the config from DB if needed, and restart Bifrost.

---

## 6. Bifrost Configuration In Depth

All Bifrost configuration lives in `data/config.json`. This file is mounted into the container at `/app/data/config.json`. On startup, Bifrost reads this file and writes its contents to Postgres (`config_store`). On subsequent starts, **Postgres is the source of truth** — the file is only re-read if the DB entry is missing.

**This means:** editing `data/config.json` after first boot has no effect unless the corresponding DB rows are deleted first.

---

### 6.1 Providers & API Keys

Providers are configured under the `providers` key. Each provider has a `keys` array.

```json
"providers": {
  "openai": {
    "keys": [
      {
        "name": "openai-key-1",
        "value": "env.OPENAI_API_KEY",
        "models": ["gpt-4o"],
        "weight": 1
      }
    ]
  },
  "openrouter": {
    "keys": [
      {
        "name": "openrouter-key-1",
        "value": "env.OPENROUTER_API_KEY",
        "models": ["meta-llama/llama-4-maverick"],
        "weight": 1
      }
    ]
  },
  "gemini": {
    "keys": [
      {
        "name": "gemini-key-1",
        "value": "env.GEMINI_API_KEY",
        "models": ["gemini-2.0-flash"],
        "weight": 1
      }
    ]
  },
  "ollama": {
    "keys": [
      {
        "name": "ollama-key-1",
        "value": "dummy",
        "models": ["llama3.2:1b", "nomic-embed-text"],
        "weight": 1
      }
    ],
    "network_config": {
      "base_url": "http://ollama:11434"
    }
  }
}
```

**Field reference:**

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Identifier shown in Bifrost UI and request logs |
| `value` | Yes | API key value. Use `"env.VAR_NAME"` to read from environment (resolved at first boot only) |
| `models` | Yes | Models this key is authorised to serve |
| `weight` | Yes | Load-balancing weight when multiple keys are present for one provider |
| `network_config.base_url` | Ollama only | Internal URL of the Ollama service. Required — no default |

> **Common mistake:** Using `"api_key": "..."` instead of `"keys": [{"value": "..."}]`. The `api_key` field does not exist — Bifrost will silently ignore it and fail to authenticate.

> **Key resolution:** `"value": "env.OPENAI_API_KEY"` is resolved from the container environment **at first boot only** and stored in Postgres. Changing `.env` after first boot has no effect without a full reset (`docker compose down -v && docker compose up -d`).

---

### 6.2 Routing Rules & Fallback Chains

Routing rules are the most powerful feature in Bifrost. They determine:
- **Which requests** to intercept (via a CEL expression)
- **Where to send** them (primary target)
- **Where to fall back** if the primary fails (ordered fallback list)

Rules live under `governance.routing_rules` in `data/config.json`.

#### How fallback works

When a request matches a rule's `cel_expression`, Bifrost routes it to the primary `targets`. If the primary provider returns an error (401 auth failure, 429 rate limit, 5xx server error, timeout), Bifrost automatically retries with the next fallback in the list. The client receives a successful response from whichever provider succeeds — the fallback is completely transparent.

#### Rule structure

```json
"governance": {
  "routing_rules": [
    {
      "id": "rule-gpt4o",
      "name": "rule-gpt4o",
      "enabled": true,
      "cel_expression": "model == \"gpt-4o\"",
      "targets": [
        { "provider": "openai", "model": "gpt-4o", "weight": 1.0 }
      ],
      "fallbacks": [
        "openrouter/meta-llama/llama-4-maverick",
        "ollama/llama3.2:1b"
      ],
      "scope": "global",
      "priority": 0
    }
  ]
}
```

**Field reference:**

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique identifier. Must match `name` to avoid DB conflict |
| `name` | Yes | Human-readable name, shown in Bifrost UI and request logs |
| `enabled` | Yes | `true` / `false` — disable without deleting |
| `cel_expression` | Yes | CEL condition evaluated per request. Rule only applies when this returns true |
| `targets` | Yes | Primary provider/model routing destination |
| `targets[].weight` | Yes | Weight for load balancing across multiple targets |
| `fallbacks` | No | Ordered list of `"provider/model"` to try if primary fails |
| `scope` | Yes | `"global"` (all requests) or `"virtual_key"` (scoped to a specific key) |
| `priority` | Yes | Lower = higher priority when multiple rules match the same request |

#### CEL Expression — Available Variables

CEL expressions are evaluated per-request. All top-level variables:

| Variable | Type | Description | Example |
|---|---|---|---|
| `model` | string | The model name requested | `model == "gpt-4o"` |
| `provider` | string | The provider name | `provider == "openai"` |
| `request_type` | string | `"chat_completion"`, `"embedding"`, `"image_generation"` | `request_type == "embedding"` |
| `budget_used` | float (0–100) | Percentage of virtual key budget consumed | `budget_used > 80` |
| `tokens_used` | float (0–100) | Token rate limit usage percentage | `tokens_used > 90` |
| `request` | float (0–100) | Request rate limit usage percentage | `request > 95` |
| `virtual_key_name` | string | Name of the virtual key on the request | `virtual_key_name == "team-a"` |
| `team_name` | string | Team name from virtual key config | `team_name == "research"` |
| `customer_id` | string | Customer identifier | `customer_id == "acme"` |
| `headers["name"]` | string | HTTP header value (case-insensitive) | `headers["x-tier"] == "premium"` |

> **Critical gotcha:** `request.model` is **not** the request object. In Bifrost's CEL environment, `request` is a float representing the request rate limit usage percentage. Writing `request.model` will fail with `"type 'double' does not support field selection"`. Always use `model` directly at the top level.

#### Multiple fallback chains

You can define as many rules as needed, each with its own condition and fallback list:

```json
"routing_rules": [
  {
    "id": "rule-gpt4o",
    "name": "rule-gpt4o",
    "cel_expression": "model == \"gpt-4o\"",
    "targets": [{ "provider": "openai", "model": "gpt-4o", "weight": 1.0 }],
    "fallbacks": ["openrouter/meta-llama/llama-4-maverick", "ollama/llama3.2:1b"],
    "scope": "global",
    "priority": 0
  },
  {
    "id": "rule-gemini",
    "name": "rule-gemini",
    "cel_expression": "model == \"gemini-2.0-flash\"",
    "targets": [{ "provider": "gemini", "model": "gemini-2.0-flash", "weight": 1.0 }],
    "fallbacks": ["openrouter/meta-llama/llama-4-maverick"],
    "scope": "global",
    "priority": 1
  },
  {
    "id": "rule-budget-guard",
    "name": "rule-budget-guard",
    "cel_expression": "budget_used > 80",
    "targets": [{ "provider": "ollama", "model": "llama3.2:1b", "weight": 1.0 }],
    "fallbacks": [],
    "scope": "global",
    "priority": 2
  }
]
```

#### Updating routing rules

After editing `data/config.json`, clear the DB and restart:

```bash
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM routing_targets; DELETE FROM routing_rules;"
docker compose restart bifrost
```

Verify rules were seeded:
```bash
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "SELECT name, enabled, cel_expression FROM routing_rules;"
```

---

### 6.3 Semantic Cache

Bifrost caches LLM responses using **semantic similarity**, not exact string matching. Before forwarding a request to a provider, Bifrost embeds the prompt and searches the Redis vector index for a semantically similar past prompt. If found above the threshold, the cached response is returned instantly — no API call, no latency, no cost.

**Why this is valuable:** "What is the capital of France?" and "Tell me France's capital city" are semantically identical but would miss an exact-match cache. Semantic caching catches this.

#### How it works

1. Request arrives at Bifrost
2. Bifrost calls Ollama's `nomic-embed-text` to generate a 768-dimensional float vector of the prompt
3. Redis Stack performs a cosine similarity search against all cached prompt vectors
4. If a match ≥ `threshold` (default 0.8) is found, the cached response is returned
5. Otherwise, the request is forwarded to the provider, the response is stored, and the span is logged

#### Configuration

```json
"plugins": [
  {
    "enabled": true,
    "name": "semantic_cache",
    "config": {
      "ttl": 2592000,
      "threshold": 0.8,
      "provider": "ollama",
      "embedding_model": "nomic-embed-text",
      "dimension": 768,
      "cleanup_on_shutdown": false
    }
  }
]
```

| Field | Description |
|---|---|
| `ttl` | Cache TTL in seconds. `2592000` = 30 days |
| `threshold` | Cosine similarity threshold (0.0–1.0). `0.8` is recommended for production |
| `provider` | Provider serving the embedding model — always `"ollama"` in this stack |
| `embedding_model` | Must match the model name pulled in Ollama |
| `dimension` | **Required.** Must match the output dimensionality of the embedding model. `nomic-embed-text` = `768`. If wrong or missing, Redis fails to create the vector index and the plugin reports `"error"` on startup |
| `cleanup_on_shutdown` | If `true`, clears the entire Redis cache on Bifrost stop |

#### Threshold tuning guide

| Threshold | Behaviour | Recommended for |
|---|---|---|
| `0.95+` | Near-exact matches only | High-stakes factual queries where wrong cached answers are costly |
| `0.85–0.95` | Paraphrases of the same question | General production use |
| `0.75–0.85` | Broader semantic matches | FAQ bots, support assistants with narrow topic domains |
| `< 0.75` | Too loose — risk of wrong cached answer for different question | Not recommended |

#### Prerequisites

`nomic-embed-text` must be pulled into Ollama once. It is stored in the `ollama_data` Docker volume and survives container restarts. It is lost on `docker compose down -v` and must be re-pulled.

```bash
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text
```

---

### 6.4 OpenTelemetry Tracing

Every request through Bifrost is emitted as an OTEL span and forwarded to Langfuse v3's OTEL HTTP endpoint. This provides full distributed tracing in the Langfuse UI with no code changes required in your application.

#### Configuration

```json
"plugins": [
  {
    "enabled": true,
    "name": "otel",
    "config": {
      "service_name": "bifrost",
      "collector_url": "http://langfuse-web:3000/api/public/otel/v1/traces",
      "trace_type": "otel",
      "protocol": "http",
      "headers": {
        "Authorization": "env.LANGFUSE_AUTH"
      }
    }
  }
]
```

| Field | Description |
|---|---|
| `collector_url` | Langfuse's OTEL endpoint. Uses Docker internal hostname `langfuse-web` |
| `trace_type` | Must be `"otel"`. Using `"genai_extension"` fails schema validation silently |
| `protocol` | `"http"` for Langfuse. `"grpc"` is also supported but not needed here |
| `headers.Authorization` | Langfuse `Basic <base64>` auth header, read from env var at first boot |

#### What each trace contains

- Full input prompt and output response
- Provider and model used
- Whether a fallback occurred (`fallback_index > 0`)
- Latency (total and per-provider)
- Token usage and cost
- Streaming flag
- Virtual key and team attribution (when configured)

---

## 7. Monitoring & Alerting

The `bifrost-monitor` sidecar is a Python service that polls Bifrost's internal API every 60 seconds and sends rich Discord embeds when alert thresholds are breached.

It is active when `DISCORD_WEBHOOK_URL` is set in `.env`. If not set, it runs but silently skips all alerts.

### 7.1 Alert Reference

| Alert | Trigger | Cooldown | Severity |
|---|---|---|---|
| **Bifrost Unreachable** | `/health` connection refused or timed out | 5 polls | Critical |
| **Bifrost Unhealthy** | `/health` returns non-OK body | 5 polls | Critical |
| **Provider Down** | Provider status is `unhealthy`/`error`/`down` | 5 polls per provider | Critical |
| **High Error Rate** | >10% of requests errored in last 5 min (min 5 req) | 5 polls | Warning |
| **High Average Latency** | Avg latency >5,000ms in last 5 min | 5 polls | Warning |
| **High P95 Latency** | P95 latency >10,000ms in last 5 min | 5 polls | Warning |
| **High Latency by Provider** | A specific provider's avg >5,000ms | 5 polls per provider | Warning |
| **Cost Spike** | >\$1.00 spent in last 5 minutes | 5 polls | Warning |
| **Daily Cost Threshold** | >\$10.00 spent in last 24 hours | 60 polls (~1h) | Critical |
| **High Fallback Rate** | >20% of recent requests used fallback (min 5 req) | 5 polls | Warning |
| **Virtual Key Budget Warning** | A virtual key has used ≥80% of budget | 10 polls | Warning/Critical |

> Cooldown = `cooldown_polls × POLL_INTERVAL_SECONDS`. At 60s polling, "5 polls" = 5 minutes before the same alert fires again.

Each Discord embed includes relevant request-level log entries (provider, model, status, latency, cost, error message) to help diagnose the issue immediately.

### 7.2 Configuring Thresholds

All thresholds are set via environment variables in `.env`:

```env
POLL_INTERVAL_SECONDS=60        # Poll frequency in seconds
ERROR_RATE_THRESHOLD=0.1        # 0.1 = 10% error rate
LATENCY_THRESHOLD_MS=5000       # Avg latency threshold (ms)
P95_LATENCY_THRESHOLD_MS=10000  # P95 latency threshold (ms)
COST_SPIKE_THRESHOLD=1.0        # Cost in $ per 5-min window
TOTAL_COST_DAILY_THRESHOLD=10.0 # Cost in $ per 24 hours
FALLBACK_RATE_THRESHOLD=0.2     # 0.2 = 20% fallback rate
MIN_REQUESTS_FOR_ALERT=5        # Min requests in window before rate alerts fire
BUDGET_ALERT_THRESHOLD=0.8      # 0.8 = 80% of virtual key budget used
```

**When to tune each threshold:**

| Variable | When to change |
|---|---|
| `ERROR_RATE_THRESHOLD` | Lower to `0.05` for stricter alerting. Raise to `0.2` for exploratory/eval workloads where errors are expected |
| `LATENCY_THRESHOLD_MS` | Tune to your SLA. If users expect <2s, set to `2000` |
| `P95_LATENCY_THRESHOLD_MS` | Should be ~2× your avg threshold |
| `COST_SPIKE_THRESHOLD` | Set to ~10% of your expected 5-minute peak spend |
| `TOTAL_COST_DAILY_THRESHOLD` | Set to your daily budget cap |
| `MIN_REQUESTS_FOR_ALERT` | Raise to `20`+ in production to avoid noise during cold starts or low-traffic hours |
| `FALLBACK_RATE_THRESHOLD` | Lower to `0.05` if any fallback is unexpected. Raise if your routing intentionally uses fallbacks frequently |
| `BUDGET_ALERT_THRESHOLD` | Lower to `0.6` for earlier warning on expensive virtual keys |

### 7.3 Implementation Notes & Limitations

**Fallback rate sampling:** The fallback rate check queries the most recent 500 log entries and filters for those with `fallback_index > 0`. This approach is needed because the Bifrost histogram API does not include fallback counts in its bucket data. At sustained >100 req/min, the 5-minute window may exceed 500 entries and the computed rate will be under-sampled. For high-throughput deployments, a dedicated Prometheus/Grafana stack is recommended.

**Cache hit rate is not alertable:** Bifrost exposes no Prometheus metric or API endpoint for semantic cache hit/miss counts. The `bifrost_cache_hits_total` metric referenced in some documentation does not exist in the actual binary. Monitor cache performance via the Bifrost UI dashboard at **http://localhost:8080**.

**Alert state is in-memory only:** Cooldown timers live in the monitor process's memory. If `bifrost-monitor` restarts (e.g. due to a crash or deploy), all cooldown timers reset and you may receive duplicate alerts for the same ongoing issue.

**Virtual key alerts are silent by default:** The virtual key budget check queries `/api/governance/virtual-keys`. If no virtual keys are configured, the response is empty and the check silently passes. It activates automatically once virtual keys are created.

---

## 8. Langfuse Observability

Langfuse v3 is the observability layer for all LLM requests. It provides trace-level visibility, cost attribution, evaluation tooling, and batch data export.

### Component roles

| Component | Role |
|---|---|
| **langfuse-web** | Web UI, REST API, OTEL HTTP endpoint (`/api/public/otel/v1/traces`) |
| **langfuse-worker** | Reads raw events from MinIO, writes to ClickHouse, runs batch exports and evaluations |
| **langfuse-db** | Postgres: stores users, organisations, projects, prompts, datasets, scores |
| **clickhouse** | Column-oriented store for all trace spans and events — optimised for analytical queries |
| **langfuse-redis** | BullMQ job queue between web (producer) and worker (consumer) |
| **minio** | Blob store: raw event payloads, media attachments, and batch export files |

### Why ClickHouse for traces?

Langfuse v3 moved trace storage from Postgres to ClickHouse because trace data is:
- **Write-heavy** — every request produces multiple spans
- **Analytical** — queries aggregate by model, provider, cost, latency across thousands of rows
- **Append-only** — traces are never updated, only inserted

ClickHouse is purpose-built for this pattern and handles millions of spans with far lower cost and latency than Postgres at scale.

### What you can see in Langfuse

- Every Bifrost request as a trace: input, output, latency, tokens, cost
- Provider and model used
- Whether a fallback occurred and the fallback index
- Streaming vs. non-streaming
- Team/customer attribution (when virtual keys are configured in Bifrost)
- Session grouping for multi-turn conversations

---

## 9. Data Export

Langfuse supports batch export of traces, scores, datasets, and sessions from the UI.

### How to export

1. Open **http://localhost:3001** → your project
2. Navigate to **Traces** or **Settings → Exports**
3. Select data type and date range and submit
4. Langfuse worker writes the export file to MinIO's `langfuse-exports` bucket
5. Download from **MinIO Console at http://localhost:9001**

MinIO Console credentials: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`.

### MinIO buckets

| Bucket | Contents |
|---|---|
| `langfuse-events` | Raw OTEL event payloads before ClickHouse ingestion |
| `langfuse-media` | Prompt/trace media attachments |
| `langfuse-exports` | Batch export files (JSON/CSV) triggered from the Langfuse UI |

### Presigned URL hostname

When you click a download link in Langfuse, it generates a presigned S3 URL. The hostname in that URL is controlled by `MINIO_SERVER_URL` in `docker-compose.yml` on the MinIO service.

- **Local deployment:** `MINIO_SERVER_URL=http://localhost:9000` — links open in your browser
- **Remote deployment:** Set to your public MinIO URL, e.g. `https://minio.yourdomain.com`

If download links fail (e.g. link says `http://minio:9000/...` which is an internal Docker hostname unreachable from your browser), update `MINIO_SERVER_URL` and restart MinIO:

```bash
docker compose up -d minio
```

---

## 10. Database Access

### Adminer UI

Go to **http://localhost:8081**.

| Database | Server field | Username | Password | Contents |
|---|---|---|---|---|
| Bifrost | `bifrost-db` | `bifrost` | `bifrost` | Request logs, keys, routing rules, plugin configs |
| Langfuse | `langfuse-db` | `langfuse` | `langfuse` | Users, projects, prompts, datasets |

> Use the exact Docker service name as the server. Docker resolves these hostnames internally. Do not use `localhost` or `127.0.0.1` — those refer to the Adminer container itself.

> Langfuse trace data lives in ClickHouse, not Postgres. Use the Langfuse UI for trace queries.

### Important Bifrost tables

| Table | Description |
|---|---|
| `request_logs` | Every request: provider, model, status, latency, tokens, cost, input, output, fallback_index |
| `config_env_keys` | Resolved API key values (from env vars at first boot) |
| `config_plugins` | Plugin configs (semantic_cache, otel) stored as JSON |
| `routing_rules` | CEL-based routing rules with fallback lists |
| `routing_targets` | Primary target (provider/model) for each routing rule |
| `governance_virtual_keys` | Virtual keys with budget and rate limit configuration |

---

## 11. ClickHouse Single-Node Setup

Langfuse v3 uses `ReplicatedMergeTree` tables, which normally require a ZooKeeper cluster for distributed coordination. For single-node self-hosting, ClickHouse's **built-in Keeper** provides the same ZooKeeper-compatible API internally — no external ZooKeeper container needed.

### What `clickhouse/config.xml` does

```xml
<clickhouse>
  <!-- 1. Enable built-in Keeper on port 9181 -->
  <keeper_server>
    <tcp_port>9181</tcp_port>
    <server_id>1</server_id>
    ...
  </keeper_server>

  <!-- 2. Point ClickHouse's ZooKeeper client at the built-in Keeper -->
  <zookeeper>
    <node><host>localhost</host><port>9181</port></node>
  </zookeeper>

  <!-- 3. Define a single-node cluster named "default" -->
  <!-- Langfuse migrations run: CREATE TABLE ... ON CLUSTER default -->
  <remote_servers>
    <default>
      <shard><replica><host>localhost</host><port>9000</port></replica></shard>
    </default>
  </remote_servers>

  <!-- 4. Set node identity macros used by ReplicatedMergeTree -->
  <macros>
    <cluster>default</cluster>
    <shard>1</shard>
    <replica>clickhouse-1</replica>
  </macros>
</clickhouse>
```

If this file is missing or not mounted, Langfuse migrations fail with:
> `"no Zookeeper configuration"` / `"Table ... requires ZooKeeper"`

This is the standard recommended approach for self-hosted single-node Langfuse v3. It is not a workaround.

---

## 12. Data Retention

Understanding what gets deleted automatically, what grows forever, and how to configure limits is critical for production operations.

### Retention summary

| Store | What it holds | Default retention | Managed by |
|---|---|---|---|
| **bifrost-db** (Postgres) | Request logs | **30 days** — auto-deleted by Bifrost | `client.log_retention_days` in `data/config.json` |
| **bifrost-redis** (Redis Stack) | Semantic cache vectors | **30 days TTL** per cache entry | `plugins.semantic_cache.ttl` in `data/config.json` (seconds) |
| **clickhouse** | Langfuse traces and events | **Forever** — no TTL configured | Must be added manually (see below) |
| **langfuse-db** (Postgres) | Langfuse metadata (users, projects, prompts, scores) | **Forever** | No built-in retention mechanism |
| **minio** | Raw events, media attachments, batch exports | **Forever** — no lifecycle rules | Must be added via MinIO Console or CLI (see below) |

### Bifrost request log retention

Controlled by `client.log_retention_days` in `data/config.json`:

```json
"client": {
  "enable_logging": true,
  "log_retention_days": 30
}
```

Bifrost runs an internal cleanup job that deletes rows from `request_logs` older than this value. Change the value and clear `config_plugins` from the DB, then restart Bifrost to apply.

### Redis semantic cache TTL

Each cache entry has a TTL set at write time via `plugins.semantic_cache.ttl` (seconds). Current value: `2592000` = 30 days. Entries expire individually — Redis does not flush the index wholesale.

**Important:** No `maxmemory` cap is configured. Under sustained high traffic, the vector index grows unboundedly until entries expire. For production, add to the `bifrost-redis` service in `docker-compose.yml`:

```yaml
bifrost-redis:
  image: redis/redis-stack:latest
  command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
```

This caps Redis at 512MB and evicts least-recently-used entries when the limit is reached.

### ClickHouse trace retention (optional)

No TTL is set — traces accumulate indefinitely. To add a TTL:

```sql
-- Connect: docker exec -it $(docker compose ps -q clickhouse) clickhouse-client --user clickhouse --password <CLICKHOUSE_PASSWORD>
ALTER TABLE langfuse.traces MODIFY TTL timestamp + INTERVAL 90 DAY;
ALTER TABLE langfuse.observations MODIFY TTL start_time + INTERVAL 90 DAY;
```

ClickHouse enforces TTLs during background merges — rows are removed within hours, not instantly.

### MinIO lifecycle rules (optional)

No lifecycle rules are set — all buckets accumulate objects indefinitely. To add expiry:

**Via MinIO Console (http://localhost:9001):** Buckets → select bucket → Lifecycle → Add Rule → set Expiry Days

**Via CLI:**
```bash
docker exec $(docker compose ps -q minio) mc ilm add --expiry-days 90 local/langfuse-events
docker exec $(docker compose ps -q minio) mc ilm add --expiry-days 30 local/langfuse-exports
docker exec $(docker compose ps -q minio) mc ilm add --expiry-days 90 local/langfuse-media
```

`langfuse-events` can safely be expired after a few days — the worker ingests them into ClickHouse within seconds to minutes of arrival.

---

## 13. Useful Commands

```bash
# ── Stack lifecycle ────────────────────────────────────────────
docker compose up -d                    # Start everything
docker compose down                     # Stop (data preserved in volumes)
docker compose down -v                  # FULL RESET — deletes all volumes and data
docker compose ps                       # Check all container statuses

# ── Applying changes ──────────────────────────────────────────
docker compose up -d                    # Reload .env / docker-compose.yml changes
docker compose restart bifrost          # Reload data/config.json (after DB cleanup)

# ── Logs ──────────────────────────────────────────────────────
docker compose logs -f bifrost
docker compose logs -f langfuse-worker
docker compose logs -f bifrost-monitor
docker compose logs -f clickhouse

# ── Health ────────────────────────────────────────────────────
curl http://localhost:8080/health

# ── Ollama ────────────────────────────────────────────────────
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text
docker exec $(docker compose ps -q ollama) ollama list

# ── Bifrost DB operations ──────────────────────────────────────
# Clear stale routing rules (before updating routing config):
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM routing_targets; DELETE FROM routing_rules;"

# Clear stale plugin configs (before updating plugin config):
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM config_plugins;"

# View routing rules in DB:
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "SELECT name, enabled, cel_expression, fallbacks FROM routing_rules;"

# ── MinIO ─────────────────────────────────────────────────────
# Re-create buckets if missing:
docker compose up minio-init
```

---

## 14. Troubleshooting

### Bifrost won't start / immediately exits

```bash
docker compose logs bifrost
```

Common causes:
- JSON syntax error in `data/config.json` — Bifrost fails schema validation and exits
- A required env var is missing — add it to `.env` and run `docker compose up -d`
- A dependency (bifrost-db, bifrost-redis, ollama) is not yet healthy — check `docker compose ps`

---

### Config changes in `data/config.json` not taking effect

Bifrost uses Postgres as its config source of truth after first boot. Editing the file is not enough. Clear the relevant DB table and restart:

```bash
# For plugin changes (semantic_cache, otel):
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost -c "DELETE FROM config_plugins;"

# For routing rule changes:
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM routing_targets; DELETE FROM routing_rules;"

docker compose restart bifrost
```

---

### Provider API keys not working after editing `.env`

API keys are resolved from env vars once at first boot and stored in Postgres. Editing `.env` afterward has no effect. The only fix is a full reset:

```bash
docker compose down -v
docker compose up -d
# Then repeat two-phase setup
```

---

### Routing rule CEL expression compile error

Check logs:
```bash
docker compose logs bifrost | grep "RoutingEngine"
```

Common error: `"type 'double' does not support field selection"` on `request.model`

**Cause:** `request` in CEL is a float (rate limit usage %), not the HTTP request object.  
**Fix:** Use `model == "gpt-4o"` instead of `request.model == "gpt-4o"`.

---

### Routing fallback not triggering

1. Verify the rule is in the DB:
   ```bash
   docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
     -c "SELECT name, cel_expression, fallbacks FROM routing_rules;"
   ```
2. Check for CEL compile errors in logs
3. Verify the request model format matches: use `"model": "openai/gpt-4o"` in requests

---

### Semantic cache plugin status: `error`

```bash
docker compose logs bifrost | grep -i "semantic_cache\|dimension"
```

**Error:** `"dimension must be > 0 (got 0)"` — the `dimension` field is missing from the plugin config in DB.

Fix:
```bash
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost -c "DELETE FROM config_plugins;"
docker compose restart bifrost
```

Ensure `data/config.json` has `"dimension": 768` in the semantic_cache plugin config.

---

### Semantic cache not returning hits despite queries

The `nomic-embed-text` model is not loaded in Ollama:

```bash
docker exec $(docker compose ps -q ollama) ollama list
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text
```

---

### Traces not appearing in Langfuse

Check in order:

1. OTEL plugin is active:
   ```bash
   docker compose logs bifrost | grep "plugin status: otel"
   ```
2. `LANGFUSE_AUTH` is correctly base64-encoded in `.env`:
   ```bash
   echo -n "pk-lf-...:sk-lf-..." | base64
   ```
3. `trace_type` in DB is `"otel"` (not `"genai_extension"`):
   ```bash
   docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
     -c "SELECT name, config_json FROM config_plugins WHERE name='otel';"
   ```
   If it shows `"genai_extension"`: delete from config_plugins and restart Bifrost
4. Worker is running:
   ```bash
   docker compose logs langfuse-worker | tail -20
   ```
5. ClickHouse is healthy:
   ```bash
   docker compose ps clickhouse
   ```

---

### Langfuse fails with "no Zookeeper configuration"

The `clickhouse/config.xml` file is missing or not mounted correctly.

- Verify the file exists: `./clickhouse/config.xml`
- Verify the mount in `docker-compose.yml` under the `clickhouse` service:
  ```yaml
  volumes:
    - ./clickhouse/config.xml:/etc/clickhouse-server/config.d/langfuse.xml:ro
  ```

After fixing, recreate ClickHouse:
```bash
docker compose stop clickhouse
docker compose up -d clickhouse
docker compose restart langfuse-web langfuse-worker
```

---

### Export download links fail (link shows `http://minio:9000/...`)

`MINIO_SERVER_URL` in `docker-compose.yml` is set to the internal Docker hostname instead of the browser-accessible URL. Update it:

```yaml
# docker-compose.yml — minio service environment
- MINIO_SERVER_URL=http://localhost:9000   # local
# - MINIO_SERVER_URL=https://minio.yourdomain.com  # remote
```

Restart MinIO to apply:
```bash
docker compose up -d minio
```

---

### MinIO buckets missing

Re-run the init service:
```bash
docker compose up minio-init
```

---

### Adminer: "could not translate host name"

Use the Docker service name — not `localhost`, not `db`:
- Bifrost database: `bifrost-db`
- Langfuse database: `langfuse-db`

---

### Discord alerts not sending

```bash
docker compose logs bifrost-monitor
```

- Check `DISCORD_WEBHOOK_URL` is set and valid in `.env`
- Check the monitor started after Bifrost was healthy
- Verify the webhook URL is reachable from the container (outbound internet access required)

---

### `docker compose restart` doesn't reload `.env` changes

`restart` reuses the existing container config. Always use `docker compose up -d` to apply env var changes — it recreates only the affected containers automatically.

---

## 15. Production Enhancement Options

| Current | Production Alternative | Benefit |
|---|---|---|
| Single-node ClickHouse with built-in Keeper | [ClickHouse Cloud](https://clickhouse.cloud) or 3-node cluster | HA, no single point of failure, managed backups |
| MinIO single-node | AWS S3, GCS, or Azure Blob Storage | Managed durability, no container to maintain |
| Hardcoded Bifrost DB password (`bifrost`) | Strong password via `.env` | Security |
| No TLS | Nginx or Traefik reverse proxy with Let's Encrypt | Encrypt client–gateway traffic |
| No resource limits | `deploy.resources.limits` per service | Prevent one container starving others |
| No backups | `pg_dump` cron + MinIO bucket versioning | Recover from data loss |
| Ollama model pulled manually | Startup entrypoint script or pre-baked image | Fully automated after full reset |
| In-memory alert cooldown | Redis-backed cooldown state | Cooldowns survive monitor restarts |
| Single Docker network | Separate frontend/backend networks | Network isolation |

---

## 16. Known Limitations

**Cache hit rate is not alertable.** Bifrost does not expose semantic cache hit or miss counts via any API or Prometheus metric. The `/metrics` endpoint contains only Go runtime and HTTP server metrics — no `bifrost_cache_hits_total` or equivalent exists. Monitor cache behaviour visually in the Bifrost UI.

**Fallback rate is sampled, not counted.** The monitor computes fallback rate from the most recent 500 log entries. At sustained throughput above ~100 req/min, the 5-minute window contains more than 500 entries and the computed rate will be under-sampled. At high traffic volumes, integrate a proper Prometheus exporter.

**Bifrost config is seeded once from file.** After the first boot, Postgres is the source of truth for all Bifrost configuration. Editing `data/config.json` requires manual DB table cleanup before the changes take effect. This is by design (config-as-code with DB as runtime store) but requires operational awareness.

**Ollama models are volume-resident.** Model weights are stored in the `ollama_data` Docker volume. After `docker compose down -v`, all models are deleted and must be re-pulled. On slow internet connections this can take several minutes and the semantic cache is non-functional until the pull completes.

**No horizontal scaling.** Every service runs as a single instance. There is no clustering, replica, or sharding configuration. This stack is designed for single-node deployment.

**Alert cooldowns reset on monitor restart.** If `bifrost-monitor` is restarted (deploy, crash, OOM), cooldown timers are lost and you may receive duplicate alerts for the same ongoing issue until the cooldown window replenishes.
