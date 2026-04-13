# LLM Observability Stack

A self-hosted, production-ready gateway and observability stack for LLM applications. It sits between your application and LLM providers (OpenAI, Gemini, OpenRouter, Ollama), giving you routing, semantic caching, full request logging, tracing, and real-time alerting — all in a single `docker compose up`.

---

## Architecture

```
Your App
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                  Bifrost Gateway :8080               │
│  • Unified OpenAI-compatible API                    │
│  • Provider routing + fallback                      │
│  • Semantic cache (Redis Stack + nomic-embed-text)  │
│  • Request/response logging → Postgres              │
│  • OTEL traces → Langfuse                           │
└────────────┬──────────────────────┬─────────────────┘
             │                      │
    ┌────────▼────────┐    ┌────────▼──────────────────────────┐
    │  LLM Providers  │    │  Langfuse v3 :3001                │
    │  • OpenAI       │    │  • langfuse-web  (UI + API)       │
    │  • Gemini       │    │  • langfuse-worker (jobs/exports) │
    │  • OpenRouter   │    │  • langfuse-db  (Postgres)        │
    │  • Ollama       │    │  • clickhouse   (trace store)     │
    └─────────────────┘    │  • langfuse-redis (job queue)     │
                           │  • minio        (blob store :9000)│
                           └───────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│               Bifrost Monitor (sidecar)              │
│  Polls Bifrost every 60s, sends Discord alerts for: │
│  health, errors, latency, cost, fallbacks, budgets  │
└─────────────────────────────────────────────────────┘

Supporting: bifrost-db (Postgres), bifrost-redis (Redis Stack), Adminer :8081
```

---

## Services

| Service | Port | Description |
|---|---|---|
| **Bifrost** | 8080 | LLM gateway — send all your LLM requests here |
| **Langfuse** | 3001 | Observability UI — traces, costs, evaluations |
| **MinIO Console** | 9001 | Blob storage UI — browse exported data |
| **Ollama** | 11434 | Local LLM runtime (used for embeddings) |
| **Adminer** | 8081 | Database admin UI (optional, for debugging) |
| bifrost-db | — | Postgres for Bifrost logs & config |
| langfuse-db | — | Postgres for Langfuse metadata |
| bifrost-redis | — | Redis Stack for semantic cache vectors |
| langfuse-redis | — | Redis for Langfuse job queuing |
| clickhouse | — | ClickHouse for Langfuse trace storage |
| minio | 9000 | S3-compatible storage for events, media, exports |
| langfuse-worker | — | Background job processor for Langfuse |
| bifrost-monitor | — | Discord alerting sidecar |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- API keys for whichever LLM providers you want to use (at least one)
- A Discord server with a webhook URL (optional, for alerts)

---

## First-Time Setup

> **Important:** Bifrost seeds its database from `.env` exactly once on first startup. If any keys are missing at that point, they won't be picked up later without a full reset (`docker compose down -v`). Follow the two-phase process below to avoid this.

---

### Phase 1 — Start Langfuse first, get your API key

Langfuse must be running before you can generate the `LANGFUSE_AUTH` key that Bifrost needs.

**1a. Create a partial `.env` file** with everything except `LANGFUSE_AUTH`:

```env
# ── LLM Provider API Keys ─────────────────────────────────────────
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...

# ── Langfuse ──────────────────────────────────────────────────────
LANGFUSE_SALT=any-random-string-here

# ── NextAuth (required by Langfuse) ──────────────────────────────
# Generate with: openssl rand -base64 32
NEXTAUTH_SECRET=any-random-string-here

# ── ClickHouse ────────────────────────────────────────────────────
CLICKHOUSE_PASSWORD=your-strong-password

# ── MinIO (S3-compatible blob storage) ───────────────────────────
MINIO_ACCESS_KEY=minio-admin
MINIO_SECRET_KEY=your-strong-minio-secret

# ── Discord Alerts (optional) ────────────────────────────────────
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

> To generate a secure random string on Windows, open PowerShell and run:  
> `[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`

**1b. Start Langfuse only:**

```bash
docker compose up -d langfuse-db langfuse-web
```

**1c. Generate your Langfuse API key:**

1. Open **http://localhost:3001** and create an account (local — no external registration)
2. Create an **Organization** and a **Project**
3. Go to **Settings → API Keys** and click **Create new API key**
4. Copy the **Public Key** and **Secret Key**
5. Encode them:

```bash
# Linux/Mac:
echo -n "pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY" | base64

# Windows PowerShell:
[Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("pk-lf-YOUR_PUBLIC_KEY:sk-lf-YOUR_SECRET_KEY"))
```

**1d. Add `LANGFUSE_AUTH` to your `.env`:**

```env
LANGFUSE_AUTH=Basic <the base64 string from above>
```

---

### Phase 2 — Start the full stack

Now that `.env` is complete, start everything:

```bash
docker compose up -d
```

Bifrost will seed its database with all keys correctly on this first boot. The first startup takes about 30–60 seconds as Bifrost waits for its dependencies to be healthy.

Verify everything is running:

```bash
docker compose ps
```

---

## Sending Requests

Bifrost exposes an **OpenAI-compatible API** on port 8080. Point your application at `http://localhost:8080` instead of `https://api.openai.com`.

### Example — curl

```bash
# Use provider/model format
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Example — Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="any-value"  # Bifrost uses its own keys from config
)

response = client.chat.completions.create(
    model="openai/gpt-4o",  # use provider/model format
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### Available Models

Use `provider/model` format in requests. Configured in `data/config.json`:

| Request Model | Provider | Notes |
|---|---|---|
| `openai/gpt-4o` | OpenAI | Primary model, has fallback chain |
| `openrouter/meta-llama/llama-4-maverick` | OpenRouter | Fallback #1 for gpt-4o |
| `gemini/gemini-2.0-flash` | Gemini | |
| `ollama/llama3.2:1b` | Ollama (local) | Fallback #2 for gpt-4o, no API key needed |

To add a model, add it to the provider's `keys[].models` array in `data/config.json` and run `docker compose up -d`.

---

## Features

### Provider Routing & Fallback

Bifrost automatically falls back to secondary providers if the primary fails. The current fallback chain (configured in `data/config.json`):

```
openai/gpt-4o  →  openrouter/meta-llama/llama-4-maverick  →  ollama/llama3.2:1b
```

If OpenAI is down or rate-limited, requests automatically retry with OpenRouter, then fall back to the local Ollama model. Fallback chains are configured in `data/config.json` under `governance.routing_rules`.

### Multiple Fallback Chains

Each routing rule targets a specific condition (CEL expression) and has its own fallback list. You can define as many rules as needed:

```json
"governance": {
  "routing_rules": [
    {
      "id": "rule-gpt4o",
      "name": "rule-gpt4o",
      "enabled": true,
      "cel_expression": "model == \"gpt-4o\"",
      "targets": [{ "provider": "openai", "model": "gpt-4o", "weight": 1.0 }],
      "fallbacks": ["openrouter/meta-llama/llama-4-maverick", "ollama/llama3.2:1b"],
      "scope": "global",
      "priority": 0
    },
    {
      "id": "rule-gemini",
      "name": "rule-gemini",
      "enabled": true,
      "cel_expression": "model == \"gemini-2.0-flash\"",
      "targets": [{ "provider": "gemini", "model": "gemini-2.0-flash", "weight": 1.0 }],
      "fallbacks": ["openrouter/meta-llama/llama-4-maverick"],
      "scope": "global",
      "priority": 1
    }
  ]
}
```

**Available CEL variables:** `model`, `provider`, `request_type`, `budget_used` (0–100), `tokens_used` (0–100), `virtual_key_name`, `team_name`, `customer_id`, `headers["name"]`

> **Note:** `request` in CEL resolves to the *request rate limit usage percentage* (a float) — not the request object. Use `model`, `provider`, etc. directly at the top level.

After editing `data/config.json`, restart Bifrost. If a routing rule already exists in the DB with the same name, delete it first to avoid a conflict:
```bash
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost -c "DELETE FROM routing_targets; DELETE FROM routing_rules;"
docker compose restart bifrost
```

### Semantic Cache

Bifrost caches LLM responses using semantic similarity — not just exact string matching. If a new request is semantically similar (≥ 80% by default) to a cached one, the cached response is returned instantly with no API call.

- **Embeddings model:** `nomic-embed-text` (runs locally via Ollama)
- **Vector store:** Redis Stack
- **Cache TTL:** 30 days
- **Similarity threshold:** 0.8 (configurable in `data/config.json`)

### Request Logging

Every request and response is logged to Postgres with full metadata: provider, model, latency, token counts, cost, errors, input/output content.

- **Retention:** 30 days (configurable in `data/config.json`)
- View logs via Adminer at **http://localhost:8081** (server: `bifrost-db`, user/password: `bifrost`)

### Tracing (OpenTelemetry → Langfuse v3)

All requests are traced via OpenTelemetry and sent to Langfuse. View them at **http://localhost:3001**:
- Full input/output content
- Latency breakdowns
- Token usage and cost per request
- Provider and model used
- Fallback and retry chains

Langfuse v3 uses **ClickHouse** for trace storage (high-volume, fast aggregations) and **MinIO** for blob storage (event payloads, media, exports). These replace the simple Postgres-only setup of v2.

**Langfuse Worker** runs in the background and handles:
- Processing raw event ingestion from MinIO into ClickHouse
- Batch data exports
- Evaluation jobs

If traces are missing, check the worker first:
```bash
docker compose logs langfuse-worker
```

### Data Export

Langfuse v3 supports batch export of traces, scores, and sessions directly from the UI:

1. Go to **http://localhost:3001** → your project → **Settings → Exports**
2. Select the data type and date range
3. The worker writes the export to MinIO's `langfuse-exports` bucket
4. Download from the **MinIO Console at http://localhost:9001** (login with `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`)

All three MinIO buckets and their purposes:

| Bucket | Purpose |
|---|---|
| `langfuse-events` | Raw event payloads before ClickHouse ingestion |
| `langfuse-media` | Prompt/trace media attachments |
| `langfuse-exports` | Batch exports triggered from the UI |

---

## Monitoring & Alerts

The `bifrost-monitor` sidecar polls Bifrost every 60 seconds and sends Discord alerts when thresholds are breached.

### Alert Types

| Alert | Condition |
|---|---|
| Bifrost Unreachable / Unhealthy | Health check fails |
| Provider Down | A provider reports unhealthy status |
| High Error Rate | > 10% of requests in the last 5 min |
| High Average Latency | Avg latency > 5,000ms |
| High P95 Latency | P95 latency > 10,000ms |
| High Latency (by provider) | A specific provider's avg > 5,000ms |
| Cost Spike | > $1.00 spent in the last 5 min |
| Daily Cost Threshold | > $10.00 spent today |
| High Fallback Rate | > 20% of requests are falling back |
| Virtual Key Budget Warning | A virtual key has used ≥ 80% of its budget |

Alerts include cooldown periods to avoid repeated notifications for the same issue.

### Implementation Notes

- **Fallback rate** is computed from individual log entries (last 500 by timestamp), not from pre-aggregated histogram buckets — the histogram API does not expose fallback counts. The 500-entry limit safely covers ~100 req/min sustained over a 5-minute window. At higher volumes, the rate may be under-sampled; consider a dedicated Prometheus/Grafana setup for high-throughput production.
- **Cache hit rate** alerting is not implemented — Bifrost exposes no API or Prometheus metric for semantic cache hits. Monitor cache behavior via the Bifrost UI dashboard instead.

### Configuring Alert Thresholds

All thresholds can be overridden via environment variables in your `.env`:

```env
POLL_INTERVAL_SECONDS=60        # How often to poll (default: 60)
ERROR_RATE_THRESHOLD=0.1        # 10% error rate (default)
LATENCY_THRESHOLD_MS=5000       # 5s avg latency (default)
P95_LATENCY_THRESHOLD_MS=10000  # 10s P95 latency (default)
COST_SPIKE_THRESHOLD=1.0        # $1.00 per 5-min window (default)
TOTAL_COST_DAILY_THRESHOLD=10.0 # $10.00 per day (default)
FALLBACK_RATE_THRESHOLD=0.2     # 20% fallback rate (default)
MIN_REQUESTS_FOR_ALERT=5        # Min requests before triggering rate alerts
BUDGET_ALERT_THRESHOLD=0.8      # Alert at 80% of virtual key budget
```

---

## Database Access (Adminer)

Go to **http://localhost:8081** and use:

| Database | Server | Username | Password |
|---|---|---|---|
| Bifrost logs & config | `bifrost-db` | `bifrost` | `bifrost` |
| Langfuse metadata | `langfuse-db` | `langfuse` | `langfuse` |

> Use the exact service name as the server — Docker resolves it internally.

> **Note:** Langfuse v3 traces are stored in ClickHouse, not Postgres.

**MinIO Console** — go to **http://localhost:9001** and login with `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`.

**Export download links:** Langfuse generates presigned S3 URLs for exports. The `MINIO_SERVER_URL` env var on the MinIO service controls the hostname used in these URLs. It must match what your browser can reach:
- **Local:** `http://localhost:9000` (default in this stack)
- **Production:** set to your public MinIO URL, e.g. `https://minio.yourdomain.com`

If export links return an error, check that `MINIO_SERVER_URL` matches your deployment URL and restart MinIO: `docker compose up -d minio`. The `langfuse-db` Postgres only holds metadata (users, projects, prompts, settings). Use the Langfuse UI for trace data.

---

## Configuration Reference

### `data/config.json`

The main Bifrost configuration file. Key sections:

- **`client`** — logging and retention settings
- **`config_store` / `logs_store`** — Postgres connection (reads from env vars)
- **`vector_store`** — Redis connection for semantic cache
- **`providers`** — API keys per provider, each as a `keys[]` array with `value`, `models`, and `weight`
- **`governance.routing_rules`** — CEL-based routing rules with per-rule fallback chains in `provider/model` format
- **`plugins`** — semantic cache and OTEL tracing configuration

> **Important:** Provider keys use `"value": "env.VAR_NAME"` syntax. Bifrost resolves these from environment variables **at first boot only** and stores them in Postgres. If you change a key in `.env` after first boot, you must do a full reset (`docker compose down -v`) for it to take effect.

Changes to `data/config.json` require clearing the relevant DB tables first (Postgres is the source of truth after first boot), then restarting:

```bash
# For routing rule changes:
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM routing_targets; DELETE FROM routing_rules;"

# For plugin changes (semantic_cache, otel):
docker exec $(docker compose ps -q bifrost-db) psql -U bifrost \
  -c "DELETE FROM config_plugins;"

docker compose restart bifrost
```

> **`semantic_cache` plugin note:** The `dimension` field is required and must match the embedding model's output size — `nomic-embed-text` = `768`. If missing, Redis fails to create the vector index and the plugin reports `error` on startup.

> **`otel` plugin note:** `trace_type` must be `"otel"`. The value `"genai_extension"` fails schema validation and traces will not be sent to Langfuse.

---

## ClickHouse — Single-Node Setup

Langfuse v3 stores all traces and events in ClickHouse using `ReplicatedMergeTree` tables, which normally require a ZooKeeper cluster. For single-node self-hosting, ClickHouse's **built-in Keeper** is used instead — it provides the same ZooKeeper-compatible API without any external dependency.

The config in `clickhouse/config.xml` does three things:
1. **Enables Keeper** — runs the built-in ZooKeeper-compatible coordination service on port `9181`
2. **Defines a single-node cluster** named `default` — matches the `ON CLUSTER default` in Langfuse's migrations
3. **Sets macros** (`cluster`, `shard`, `replica`) — used by `ReplicatedMergeTree` to identify this node

This is the standard approach for single-node self-hosted Langfuse v3. It is not a hack — it's the intended way to run ClickHouse without a full multi-node cluster.

### Production Enhancement Options

| Current | Production Alternative | Benefit |
|---|---|---|
| Self-hosted ClickHouse (single node) | [ClickHouse Cloud](https://clickhouse.cloud) or Altinity Cloud | Managed, HA, no Keeper config needed |
| MinIO (self-hosted) | AWS S3, GCS, or Azure Blob Storage | Managed, durable, no container to maintain |
| Single-node ClickHouse | 3-node ClickHouse cluster with dedicated Keeper | True HA, no single point of failure |

If you move to managed ClickHouse or managed S3, remove the `clickhouse/config.xml` mount and the `minio`/`minio-init` services from `docker-compose.yml`, and update the relevant env vars to point at the managed endpoints.

---

## Data Retention

| Store | What it holds | Retention | Configurable |
|---|---|---|---|
| **bifrost-db** (Postgres) | Request logs | 30 days — Bifrost auto-deletes older entries | `client.log_retention_days` in `data/config.json` |
| **bifrost-redis** (Redis Stack) | Semantic cache vectors | 30 days TTL per entry | `plugins.semantic_cache.ttl` in `data/config.json` (seconds) |
| **clickhouse** | Langfuse traces and events | Forever — no TTL set | Add a ClickHouse TTL policy manually (see below) |
| **langfuse-db** (Postgres) | Langfuse metadata (users, projects, prompts) | Forever | No built-in retention |
| **minio** | Raw events, media, exports | Forever — no lifecycle rules set | Add MinIO bucket lifecycle rules (see below) |

> **Redis note:** No `maxmemory` cap is set. Under heavy traffic, the vector index grows unboundedly until the 30-day TTL expires entries. For production, set a `maxmemory` limit and `maxmemory-policy: allkeys-lru` in the Redis config.

### Adding ClickHouse trace retention (optional)

To automatically drop Langfuse traces older than 90 days, run this against ClickHouse:

```sql
ALTER TABLE langfuse.traces MODIFY TTL timestamp + INTERVAL 90 DAY;
ALTER TABLE langfuse.observations MODIFY TTL start_time + INTERVAL 90 DAY;
```

### Adding MinIO bucket lifecycle rules (optional)

Via MinIO Console (**http://localhost:9001**) → Buckets → `langfuse-events` → Lifecycle → Add Rule → Expiry after N days.

Or via CLI:
```bash
docker exec $(docker compose ps -q minio) mc ilm add --expiry-days 90 local/langfuse-events
docker exec $(docker compose ps -q minio) mc ilm add --expiry-days 90 local/langfuse-media
```

---

## Useful Commands

```bash
# Start everything
docker compose up -d

# Stop everything (data is preserved in volumes)
docker compose down

# Stop and delete all data (FULL RESET — requires re-running first-time setup)
docker compose down -v

# Apply .env or config changes (recreates affected containers automatically)
docker compose up -d

# Restart a single service (does NOT reload .env changes — use up -d instead)
docker compose restart bifrost

# View logs
docker compose logs -f bifrost
docker compose logs -f langfuse-worker
docker compose logs -f bifrost-monitor

# Check Bifrost health
curl http://localhost:8080/health

# Re-pull Ollama models after a full reset
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text

# Check all container statuses
docker compose ps
```

---

## Troubleshooting

**API keys not being picked up after editing `.env`**  
`docker compose restart` does not reload environment variables. Always use `docker compose up -d` — it automatically recreates only affected containers.

**Bifrost won't start**  
Check all dependencies are healthy: `docker compose ps`. Bifrost waits for `bifrost-db`, `bifrost-redis`, `ollama`, and `langfuse-web`.

**Bifrost seeds empty keys on first boot**  
This happens if `.env` was incomplete when first started. The only fix is a full reset:
```bash
docker compose down -v && docker compose up -d
```
Then follow the two-phase setup process again.

**Traces not appearing in Langfuse**  
Check in this order:
1. `LANGFUSE_AUTH` is set and correctly base64-encoded in `.env`
2. Langfuse worker is running: `docker compose logs langfuse-worker`
3. ClickHouse is healthy: `docker compose ps clickhouse`
4. Bifrost OTEL errors: `docker compose logs bifrost | grep otel`

**Langfuse web/worker crash with "no Zookeeper configuration" error**  
ClickHouse is missing the Keeper config. Make sure `clickhouse/config.xml` exists in the project root and is mounted correctly in `docker-compose.yml`. Recreate ClickHouse after adding the config:
```bash
docker compose stop clickhouse && docker compose up -d clickhouse
```
Then restart Langfuse: `docker compose up -d langfuse-web langfuse-worker`

**Langfuse worker not processing events**  
Worker depends on ClickHouse, Redis, and MinIO. Check all three:
```bash
docker compose ps clickhouse langfuse-redis minio
```

**MinIO buckets missing**  
The `minio-init` service creates buckets on first boot. If it failed:
```bash
docker compose up minio-init
```

**Adminer "could not translate host name" error**  
Use the exact Docker service name: `bifrost-db` or `langfuse-db` — not `localhost` or `db`.

**Semantic cache not working**  
The `nomic-embed-text` model must be in Ollama. After a full reset, re-pull it:
```bash
docker exec $(docker compose ps -q ollama) ollama pull nomic-embed-text
```

**Discord alerts not sending**  
```bash
docker compose logs bifrost-monitor
```
