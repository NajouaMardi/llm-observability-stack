"""
LLM Observability Stack — Production Validation Test Suite
Run from the project root: python test_stack.py
Requires: pip install requests
Bifrost must be running on localhost:8080
"""

import time
import requests
import sys

BIFROST_URL = "http://localhost:8080"
LANGFUSE_URL = "http://localhost:3001"

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

results = []


def record(name, passed, detail=""):
    status = PASS if passed else FAIL
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, passed))


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def chat(model, prompt, timeout=30):
    """Send a chat completion request to Bifrost."""
    return requests.post(
        f"{BIFROST_URL}/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )


# ── 1. Health Check ───────────────────────────────────────────────────────────
section("1. Bifrost Health")

try:
    r = requests.get(f"{BIFROST_URL}/health", timeout=5)
    ok = r.ok and r.json().get("status") == "ok"
    record("Bifrost health endpoint", ok, r.json().get("status", r.text[:50]))
except Exception as e:
    record("Bifrost health endpoint", False, str(e))
    print(f"\n  {FAIL} Bifrost is unreachable. Aborting tests.")
    sys.exit(1)


# ── 2. Provider Routing ───────────────────────────────────────────────────────
section("2. Provider Routing")

# OpenRouter
try:
    r = chat("openrouter/meta-llama/llama-4-maverick", "Reply with one word: hello")
    ok = r.ok and r.json().get("choices")
    provider = r.json().get("extra_fields", {}).get("provider", "?") if r.ok else "error"
    record("OpenRouter direct request", ok, f"provider={provider}")
except Exception as e:
    record("OpenRouter direct request", False, str(e))

# Gemini
try:
    r = chat("gemini/gemini-2.0-flash", "Reply with one word: hello")
    ok = r.ok and r.json().get("choices")
    provider = r.json().get("extra_fields", {}).get("provider", "?") if r.ok else "error"
    record("Gemini direct request", ok, f"provider={provider}")
except Exception as e:
    record("Gemini direct request", False, str(e))

# Ollama
try:
    r = chat("ollama/llama3.2:1b", "Reply with one word: hello", timeout=60)
    ok = r.ok and r.json().get("choices")
    provider = r.json().get("extra_fields", {}).get("provider", "?") if r.ok else "error"
    record("Ollama local request", ok, f"provider={provider}")
except Exception as e:
    record("Ollama local request", False, str(e))


# ── 3. Fallback Routing ───────────────────────────────────────────────────────
section("3. Fallback Routing (openai/gpt-4o → OpenRouter)")

try:
    r = chat("openai/gpt-4o", "Reply with one word: hello")
    data = r.json()
    provider = data.get("extra_fields", {}).get("provider", "?")
    fallback_idx = data.get("extra_fields", {}).get("fallback_index", 0)
    # OpenAI key is a placeholder, so it must fallback
    fell_back = provider != "openai" and r.ok
    record(
        "Fallback triggered on invalid OpenAI key",
        fell_back,
        f"landed on provider={provider}, fallback_index={fallback_idx}",
    )
    record(
        "Fallback response is valid",
        r.ok and bool(data.get("choices")),
        data.get("choices", [{}])[0].get("message", {}).get("content", "")[:60] if r.ok else r.text[:60],
    )
except Exception as e:
    record("Fallback triggered on invalid OpenAI key", False, str(e))
    record("Fallback response is valid", False, str(e))


# ── 4. Bad Request Handling ───────────────────────────────────────────────────
section("4. Bad Request Handling")

# Unknown model
try:
    r = chat("fakeprovider/nonexistent-model", "hello")
    is_error = not r.ok or r.json().get("is_bifrost_error") or r.json().get("error")
    record("Unknown model returns error (not crash)", is_error, f"status={r.status_code}")
except Exception as e:
    record("Unknown model returns error (not crash)", False, str(e))

# Missing model field
try:
    r = requests.post(
        f"{BIFROST_URL}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        timeout=5,
    )
    is_error = not r.ok
    record("Missing model field returns error", is_error, f"status={r.status_code}")
except Exception as e:
    record("Missing model field returns error", False, str(e))


# ── 5. Semantic Cache ─────────────────────────────────────────────────────────
section("5. Semantic Cache")

# Check plugin is active
try:
    r = requests.get(f"{BIFROST_URL}/api/config", timeout=5)
    record("Config API reachable", r.ok, f"status={r.status_code}")
except Exception as e:
    record("Config API reachable", False, str(e))

CACHE_PROMPT = "What is the capital city of Japan?"

print(f"  {INFO} Sending first request (cache miss expected)...")
try:
    t0 = time.time()
    r1 = chat("openrouter/meta-llama/llama-4-maverick", CACHE_PROMPT)
    t1 = time.time() - t0
    first_ok = r1.ok
    record("First request (cache miss) succeeds", first_ok, f"latency={t1*1000:.0f}ms")
except Exception as e:
    record("First request (cache miss) succeeds", False, str(e))
    t1 = 999
    first_ok = False

print(f"  {INFO} Sending second identical request (cache hit expected)...")
try:
    t0 = time.time()
    r2 = chat("openrouter/meta-llama/llama-4-maverick", CACHE_PROMPT)
    t2 = time.time() - t0
    second_ok = r2.ok
    record("Second request (cache hit) succeeds", second_ok, f"latency={t2*1000:.0f}ms")
    if first_ok and second_ok:
        # Cache hit should be significantly faster
        cache_likely = t2 < (t1 * 0.5)
        record(
            "Cache hit is faster than original request",
            cache_likely,
            f"first={t1*1000:.0f}ms, second={t2*1000:.0f}ms",
        )
except Exception as e:
    record("Second request (cache hit) succeeds", False, str(e))

print(f"  {INFO} Sending semantically similar prompt (cache hit expected)...")
try:
    t0 = time.time()
    r3 = chat("openrouter/meta-llama/llama-4-maverick", "Tell me the capital of Japan")
    t3 = time.time() - t0
    record(
        "Semantically similar prompt returns response",
        r3.ok,
        f"latency={t3*1000:.0f}ms — {'likely cache hit' if t3 < t1 * 0.5 else 'likely cache miss (check threshold)'}",
    )
except Exception as e:
    record("Semantically similar prompt returns response", False, str(e))


# ── 6. Error Rate Alert Trigger ───────────────────────────────────────────────
section("6. Error Rate — Trigger Monitoring Alert")

print(f"  {INFO} Sending 10 bad requests to trigger High Error Rate alert...")
bad_count = 0
for i in range(10):
    try:
        r = chat("fakeprovider/bad-model", "hello")
        if not r.ok or r.json().get("error"):
            bad_count += 1
    except Exception:
        bad_count += 1

record(
    "10 bad requests sent successfully",
    bad_count >= 8,
    f"{bad_count}/10 returned errors — check Discord for 'High Error Rate' alert within ~60s",
)


# ── 7. Bifrost Metrics Endpoint ───────────────────────────────────────────────
section("7. Metrics & API Endpoints")

endpoints = [
    ("/metrics", "Prometheus metrics"),
    ("/api/providers", "Providers list"),
    ("/api/logs/histogram?start_time=2026-01-01T00:00:00.000Z&end_time=2026-12-31T00:00:00.000Z", "Request histogram"),
    ("/api/logs/histogram/latency?start_time=2026-01-01T00:00:00.000Z&end_time=2026-12-31T00:00:00.000Z", "Latency histogram"),
    ("/api/logs/histogram/cost?start_time=2026-01-01T00:00:00.000Z&end_time=2026-12-31T00:00:00.000Z", "Cost histogram"),
    ("/api/governance/virtual-keys", "Virtual keys"),
]

for path, label in endpoints:
    try:
        r = requests.get(f"{BIFROST_URL}{path}", timeout=5)
        record(f"{label} endpoint reachable", r.ok, f"status={r.status_code}")
    except Exception as e:
        record(f"{label} endpoint reachable", False, str(e))


# ── 8. Langfuse Reachability ──────────────────────────────────────────────────
section("8. Langfuse Reachability")

try:
    r = requests.get(f"{LANGFUSE_URL}/api/public/health", timeout=5)
    record("Langfuse health endpoint", r.ok, f"status={r.status_code}")
except Exception as e:
    record("Langfuse health endpoint", False, f"{e} — check docker compose ps langfuse-web")


# ── 9. MinIO Reachability ─────────────────────────────────────────────────────
section("9. MinIO Reachability")

try:
    r = requests.get("http://localhost:9000/minio/health/live", timeout=5)
    record("MinIO S3 API reachable", r.ok, f"status={r.status_code}")
except Exception as e:
    record("MinIO S3 API reachable", False, str(e))

try:
    r = requests.get("http://localhost:9001", timeout=5)
    record("MinIO Console reachable", r.ok, f"status={r.status_code}")
except Exception as e:
    record("MinIO Console reachable", False, str(e))


# ── Summary ───────────────────────────────────────────────────────────────────
section("Summary")

passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
total = len(results)

print(f"\n  Total:  {total}")
print(f"  {PASS} Passed: {passed}")
if failed:
    print(f"  {FAIL} Failed: {failed}")
    print(f"\n  Failed tests:")
    for name, ok in results:
        if not ok:
            print(f"    • {name}")

print()
if failed == 0:
    print(f"  \033[92mAll tests passed. Stack is healthy.\033[0m")
else:
    print(f"  \033[91m{failed} test(s) failed. Review output above.\033[0m")

print()
print("  Manual checks still required:")
print("  • Langfuse UI (http://localhost:3001) — verify traces appear after requests above")
print("  • Discord — verify 'High Error Rate' alert fired from section 6")
print("  • Langfuse export → MinIO download link — verify presigned URL opens in browser")
print("  • docker compose down && docker compose up -d — verify data persists after restart")
print()
