# LLM Observability Stack

Plug-and-play LLM observability for any application.
Built on LiteLLM + Langfuse. Every LLM call is
automatically routed, logged, traced, and monitored.

## What's included
- **LiteLLM** => unified LLM proxy with routing,
  fallbacks, retries, rate limiting, and cost tracking
- **Langfuse** => full observability UI: traces, sessions,
  cost dashboards, latency metrics, token usage
- **Ollama** => run LLMs locally for free
- **PostgreSQL, ClickHouse, Redis, MinIO** => required
  infrastructure, all pre-configured

## Services and ports
| Service      | Port  | Description              |
|--------------|-------|--------------------------|
| LiteLLM      | 4000  | LLM proxy: send calls here |
| Langfuse     | 3000  | Observability UI         |
| Ollama       | 11434 | Local LLM runner         |
| PostgreSQL   | 5432  | Database                 |

## Setup

**Step 1 — Copy and fill environment file**
```
cp .env.example .env
```
Fill in your API keys and generate random strings
for NEXTAUTH_SECRET, LANGFUSE_SALT, and ENCRYPTION_KEY:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

**Step 2 — Start the stack**
```
docker-compose up
```
Wait 2-3 minutes for all services to initialize.

**Step 3 — Set up Langfuse**
- Open http://localhost:3000
- Create an account, organization, and project
- Copy your public and secret keys into .env
- Restart: docker-compose restart langfuse-web langfuse-worker litellm

## Using the proxy

Point your app to LiteLLM instead of any provider directly:
```
http://localhost:4000
```

Example request:
```
POST http://localhost:4000/chat/completions
Authorization: Bearer your-master-key
Content-Type: application/json

{
  "model": "gemini-flash",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

Every call automatically appears as a trace in Langfuse.

## Available models
| Model name      | Provider   |
|-----------------|------------|
| gemini-flash    | Google     |
| gpt-4o          | OpenAI     |
| openrouter-llama| OpenRouter |
| ollama-llama    | Local      |

## Using Ollama (local, free)
Pull a model first:
```
docker exec -it llmobservability-ollama-1 ollama pull llama3.2:1b
```
Then use model name: `ollama-llama`

## Integrating with your app
Your app only needs one change, replace your LLM
provider URL with:
```
http://localhost:4000
```
No other code changes needed. Works with any language
or framework.
```

