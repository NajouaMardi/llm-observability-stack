import os
import time
import requests
from datetime import datetime, timezone

BIFROST_URL = os.getenv("BIFROST_URL", "http://bifrost:8080")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "0.1"))
LATENCY_THRESHOLD_MS = float(os.getenv("LATENCY_THRESHOLD_MS", "5000"))
P95_LATENCY_THRESHOLD_MS = float(os.getenv("P95_LATENCY_THRESHOLD_MS", "10000"))
COST_SPIKE_THRESHOLD = float(os.getenv("COST_SPIKE_THRESHOLD", "1.0"))
TOTAL_COST_DAILY_THRESHOLD = float(os.getenv("TOTAL_COST_DAILY_THRESHOLD", "10.0"))
FALLBACK_RATE_THRESHOLD = float(os.getenv("FALLBACK_RATE_THRESHOLD", "0.2"))
MIN_REQUESTS_FOR_ALERT = int(os.getenv("MIN_REQUESTS_FOR_ALERT", "5"))

COLORS = {
    "error":   0xE74C3C,
    "warning": 0xF39C12,
    "info":    0x3498DB,
    "success": 0x2ECC71,
}

_alerted = {}


def already_alerted(key: str, cooldown_polls: int = 5) -> bool:
    now = time.time()
    last = _alerted.get(key, 0)
    if now - last < cooldown_polls * POLL_INTERVAL:
        return True
    _alerted[key] = now
    return False


def send_discord_alert(title: str, description: str, color_key: str, fields: list = None):
    if not DISCORD_WEBHOOK_URL:
        print("[alert] DISCORD_WEBHOOK_URL not set, skipping")
        return
    embed = {
        "title": title,
        "description": description,
        "color": COLORS.get(color_key, COLORS["info"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Bifrost Monitor"},
        "fields": fields or [],
    }
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"username": "Bifrost Alerts", "embeds": [embed]},
            timeout=10,
        )
        if resp.status_code not in (200, 204):
            print(f"[alert] Discord returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[alert] Failed to send Discord alert: {e}")


def get_time_window(minutes: int = 5):
    now = datetime.now(timezone.utc)
    start = now.timestamp() - (minutes * 60)
    start_iso = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return f"?start_time={start_iso}&end_time={end_iso}"


def fetch(path: str, window_minutes: int = 5):
    try:
        params = get_time_window(window_minutes)
        resp = requests.get(f"{BIFROST_URL}{path}{params}", timeout=5)
        return resp.json() if resp.ok else None
    except Exception as e:
        print(f"[monitor] Failed to fetch {path}: {e}")
        return None


def fetch_no_params(path: str):
    try:
        resp = requests.get(f"{BIFROST_URL}{path}", timeout=5)
        return resp.json() if resp.ok else None
    except Exception as e:
        print(f"[monitor] Failed to fetch {path}: {e}")
        return None


def fetch_recent_logs(status: str = None, limit: int = 5) -> list:
    """Fetch recent logs, optionally filtered by status (error, success)."""
    try:
        url = f"{BIFROST_URL}/api/logs?limit={limit}&order=desc"
        if status:
            url += f"&status={status}"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            return resp.json().get("logs", [])
    except Exception as e:
        print(f"[monitor] Failed to fetch logs: {e}")
    return []


def format_log_fields(logs: list, label: str = "Recent errors") -> list:
    """Turn a list of log entries into Discord embed fields with full context."""
    if not logs:
        return []

    fields = []
    for i, log in enumerate(logs[:3], 1):
        provider = log.get("provider", "unknown")
        model = log.get("model", "unknown")
        status = log.get("status", "unknown")
        retries = log.get("number_of_retries", 0)
        fallback_idx = log.get("fallback_index", 0)
        latency = log.get("latency_ms") or log.get("latency") or 0
        tokens = log.get("total_tokens") or 0
        cost = log.get("cost") or 0.0
        ts = log.get("timestamp", "")[:19].replace("T", " ") if log.get("timestamp") else "unknown"

        error_msg = ""
        error_details = log.get("error_details") or {}
        if error_details:
            err = error_details.get("error") or {}
            error_msg = err.get("message", "")[:120] if err else ""
            status_code = error_details.get("status_code", "")
        else:
            status_code = ""

        input_history = log.get("input_history") or []
        last_msg = ""
        if input_history:
            last_msg = str(input_history[-1].get("content", ""))[:80]

        # Optional identity/routing fields — present only when configured
        team = log.get("prom_team") or log.get("team") or ""
        env = log.get("prom_environment") or log.get("environment") or ""
        vk_name = log.get("virtual_key_name") or ""
        key_name = log.get("selected_key_name") or ""
        routing_rule = log.get("routing_rule_name") or ""
        is_stream = log.get("stream", False)

        lines = [
            f"**Provider:** {provider}",
            f"**Model:** `{model}`",
            f"**Status:** {status}" + (f" (HTTP {status_code})" if status_code else ""),
            f"**Time:** {ts}",
        ]
        if team:
            lines.append(f"**Team:** {team}")
        if env:
            lines.append(f"**Environment:** {env}")
        if vk_name:
            lines.append(f"**Virtual key:** {vk_name}")
        if key_name:
            lines.append(f"**API key used:** {key_name}")
        if routing_rule:
            lines.append(f"**Routing rule:** {routing_rule}")
        if is_stream:
            lines.append(f"**Streaming:** yes")
        if latency:
            lines.append(f"**Latency:** {latency}ms")
        if tokens:
            lines.append(f"**Tokens:** {tokens}")
        if cost:
            lines.append(f"**Cost:** ${cost:.6f}")
        if retries:
            lines.append(f"**Retries:** {retries} | **Fallback index:** {fallback_idx}")
        if error_msg:
            lines.append(f"**Error:** {error_msg}")
        if last_msg:
            lines.append(f"**Last prompt:** {last_msg}...")

        fields.append({
            "name": f"{'─' * 20} Log {i}",
            "value": "\n".join(lines),
            "inline": False
        })

    return fields


def check_bifrost_health():
    try:
        resp = requests.get(f"{BIFROST_URL}/health", timeout=5)
        if not resp.ok or resp.json().get("status") != "ok":
            if not already_alerted("bifrost_health"):
                send_discord_alert(
                    title="🔴 Bifrost Unhealthy",
                    description="Bifrost health check is failing. The gateway may be degraded.",
                    color_key="error",
                    fields=[{"name": "Health Response", "value": resp.text[:200], "inline": False}]
                )
    except Exception as e:
        if not already_alerted("bifrost_unreachable"):
            err_str = str(e)
            if "NewConnectionError" in err_str:
                short_err = "Connection refused — Bifrost container is unreachable on port 8080."
            elif "timed out" in err_str.lower():
                short_err = "Connection timed out — Bifrost is not responding."
            else:
                short_err = err_str[:200]
            send_discord_alert(
                title="🔴 Bifrost Unreachable",
                description="Cannot reach Bifrost at all — the gateway is down.",
                color_key="error",
                fields=[{"name": "Error", "value": short_err, "inline": False}]
            )


def check_provider_health():
    data = fetch_no_params("/api/providers")
    if not data:
        return
    providers = data if isinstance(data, list) else data.get("providers", [])
    for provider in providers:
        name = provider.get("name", "unknown")
        status = provider.get("status", "")
        if status in ("unhealthy", "error", "down"):
            key = f"provider_down_{name}"
            if not already_alerted(key):
                recent = fetch_recent_logs(status="error", limit=3)
                provider_logs = [l for l in recent if l.get("provider") == name]
                fields = [
                    {"name": "Provider", "value": name, "inline": True},
                    {"name": "Status", "value": status, "inline": True},
                ] + format_log_fields(provider_logs, "Recent errors from this provider")
                send_discord_alert(
                    title=f"🔴 Provider Down: {name}",
                    description=f"Provider **{name}** is reporting status `{status}`.",
                    color_key="error",
                    fields=fields,
                )


def check_error_rate():
    data = fetch("/api/logs/histogram")
    if not data:
        return
    buckets = data.get("buckets", [])
    total = sum(b.get("count", 0) for b in buckets)
    errors = sum(b.get("error", 0) for b in buckets)
    if total < MIN_REQUESTS_FOR_ALERT:
        return
    rate = errors / total
    if rate >= ERROR_RATE_THRESHOLD and not already_alerted("error_rate"):
        recent_errors = fetch_recent_logs(status="error", limit=3)

        #Summarise which providers/models are failing
        provider_counts = {}
        model_counts = {}
        for log in recent_errors:
            p = log.get("provider", "unknown")
            m = log.get("model", "unknown")
            provider_counts[p] = provider_counts.get(p, 0) + 1
            model_counts[m] = model_counts.get(m, 0) + 1

        summary_fields = [
            {"name": "Total Requests", "value": str(total), "inline": True},
            {"name": "Errors", "value": str(errors), "inline": True},
            {"name": "Error Rate", "value": f"{rate:.1%}", "inline": True},
            {"name": "Failing Providers", "value": ", ".join(f"{p} ({c}x)" for p, c in provider_counts.items()) or "unknown", "inline": False},
            {"name": "Failing Models", "value": ", ".join(f"`{m}`" for m in list(model_counts.keys())[:5]) or "unknown", "inline": False},
        ] + format_log_fields(recent_errors)

        send_discord_alert(
            title="⚠️ High Error Rate",
            description=f"Error rate is **{rate:.1%}** over the last 5 minutes.",
            color_key="warning",
            fields=summary_fields,
        )


def check_latency():
    data = fetch("/api/logs/histogram/latency")
    if not data:
        return
    buckets = [b for b in data.get("buckets", []) if b.get("avg_latency", 0) > 0]
    if not buckets:
        return
    avg = sum(b["avg_latency"] for b in buckets) / len(buckets)
    p95 = max(b.get("p95_latency", 0) for b in buckets)
    p90 = max(b.get("p90_latency", 0) for b in buckets)

    if avg >= LATENCY_THRESHOLD_MS and not already_alerted("high_avg_latency"):
        recent = fetch_recent_logs(limit=3)
        send_discord_alert(
            title="🐢 High Average Latency",
            description=f"Average latency is **{avg:.0f}ms** over the last 5 minutes.",
            color_key="warning",
            fields=[
                {"name": "Avg Latency", "value": f"{avg:.0f}ms", "inline": True},
                {"name": "P90 Latency", "value": f"{p90:.0f}ms", "inline": True},
                {"name": "P95 Latency", "value": f"{p95:.0f}ms", "inline": True},
                {"name": "Threshold", "value": f"{LATENCY_THRESHOLD_MS:.0f}ms", "inline": True},
            ] + format_log_fields(recent),
        )
    elif p95 >= P95_LATENCY_THRESHOLD_MS and not already_alerted("high_p95_latency"):
        recent = fetch_recent_logs(limit=3)
        send_discord_alert(
            title="🐢 High P95 Latency",
            description=f"P95 latency hit **{p95:.0f}ms** — some requests are very slow.",
            color_key="warning",
            fields=[
                {"name": "P95 Latency", "value": f"{p95:.0f}ms", "inline": True},
                {"name": "P90 Latency", "value": f"{p90:.0f}ms", "inline": True},
                {"name": "Avg Latency", "value": f"{avg:.0f}ms", "inline": True},
                {"name": "Threshold", "value": f"{P95_LATENCY_THRESHOLD_MS:.0f}ms", "inline": True},
            ] + format_log_fields(recent),
        )


def check_latency_by_provider():
    data = fetch("/api/logs/histogram/latency/by-provider")
    if not data:
        return
    buckets = data.get("buckets", []) if isinstance(data, dict) else data
    provider_latency = {}
    for b in buckets:
        for provider, metrics in (b.get("by_provider") or {}).items():
            avg = metrics.get("avg_latency", 0)
            if avg > 0:
                provider_latency.setdefault(provider, []).append(avg)
    for provider, values in provider_latency.items():
        avg = sum(values) / len(values)
        if avg >= LATENCY_THRESHOLD_MS:
            key = f"latency_provider_{provider}"
            if not already_alerted(key):
                recent = fetch_recent_logs(limit=5)
                provider_logs = [l for l in recent if l.get("provider") == provider]
                send_discord_alert(
                    title=f"🐢 High Latency: {provider}",
                    description=f"Provider **{provider}** is responding slowly.",
                    color_key="warning",
                    fields=[
                        {"name": "Provider", "value": provider, "inline": True},
                        {"name": "Avg Latency", "value": f"{avg:.0f}ms", "inline": True},
                        {"name": "Threshold", "value": f"{LATENCY_THRESHOLD_MS:.0f}ms", "inline": True},
                    ] + format_log_fields(provider_logs),
                )


def check_cost():
    data = fetch("/api/logs/histogram/cost")
    if not data:
        return
    buckets = data.get("buckets", [])
    total_cost = sum(b.get("total_cost", 0) for b in buckets)
    if total_cost >= COST_SPIKE_THRESHOLD and not already_alerted("cost_spike"):
        #Get cost by provider for breakdown
        by_provider_data = fetch("/api/logs/histogram/cost/by-provider")
        provider_costs = {}
        if by_provider_data:
            for b in by_provider_data.get("buckets", []):
                for p, m in (b.get("by_provider") or {}).items():
                    provider_costs[p] = provider_costs.get(p, 0) + m.get("total_cost", 0)

        recent = fetch_recent_logs(limit=3)
        provider_fields = [
            {"name": f"Cost — {p}", "value": f"${c:.4f}", "inline": True}
            for p, c in sorted(provider_costs.items(), key=lambda x: -x[1]) if c > 0
        ]
        send_discord_alert(
            title="💸 Cost Spike",
            description=f"**${total_cost:.4f}** spent in the last 5 minutes.",
            color_key="warning",
            fields=[
                {"name": "Total Cost", "value": f"${total_cost:.4f}", "inline": True},
                {"name": "Threshold", "value": f"${COST_SPIKE_THRESHOLD:.2f}", "inline": True},
            ] + provider_fields + format_log_fields(recent),
        )


def check_daily_cost():
    data = fetch("/api/logs/histogram/cost", window_minutes=1440)
    if not data:
        return
    buckets = data.get("buckets", [])
    total_cost = sum(b.get("total_cost", 0) for b in buckets)
    if total_cost >= TOTAL_COST_DAILY_THRESHOLD and not already_alerted("daily_cost", cooldown_polls=60):
        send_discord_alert(
            title="💰 Daily Cost Threshold Reached",
            description=f"Total spend today has reached **${total_cost:.4f}**.",
            color_key="error",
            fields=[
                {"name": "Daily Cost", "value": f"${total_cost:.4f}", "inline": True},
                {"name": "Threshold", "value": f"${TOTAL_COST_DAILY_THRESHOLD:.2f}", "inline": True},
                {"name": "Overage", "value": f"${total_cost - TOTAL_COST_DAILY_THRESHOLD:.4f}", "inline": True},
            ],
        )


def check_fallback_rate():
    data = fetch("/api/logs/histogram")
    if not data:
        return
    buckets = data.get("buckets", [])
    total = sum(b.get("count", 0) for b in buckets)
    fallbacks = sum(b.get("fallback", 0) for b in buckets)
    if total < MIN_REQUESTS_FOR_ALERT or fallbacks == 0:
        return
    rate = fallbacks / total
    if rate >= FALLBACK_RATE_THRESHOLD and not already_alerted("fallback_rate"):
        #Get recent logs to show which primary providers triggered fallbacks
        recent = fetch_recent_logs(limit=5)
        fallback_logs = [l for l in recent if (l.get("fallback_index") or 0) > 0]

        fallback_providers = {}
        for log in fallback_logs:
            p = log.get("provider", "unknown")
            fallback_providers[p] = fallback_providers.get(p, 0) + 1

        send_discord_alert(
            title="🔀 High Fallback Rate",
            description=f"**{rate:.1%}** of requests fell back to secondary providers — primary providers may be degraded.",
            color_key="warning",
            fields=[
                {"name": "Total Requests", "value": str(total), "inline": True},
                {"name": "Fallbacks", "value": str(fallbacks), "inline": True},
                {"name": "Fallback Rate", "value": f"{rate:.1%}", "inline": True},
                {"name": "Providers Receiving Fallbacks", "value": ", ".join(f"{p} ({c}x)" for p, c in fallback_providers.items()) or "see logs", "inline": False},
            ] + format_log_fields(fallback_logs),
        )


BUDGET_ALERT_THRESHOLD = float(os.getenv("BUDGET_ALERT_THRESHOLD", "0.8"))        #alert at 80% of budget used
CACHE_HIT_RATE_THRESHOLD = float(os.getenv("CACHE_HIT_RATE_THRESHOLD", "0.3"))    #alert if cache hit rate drops below 30%


def check_virtual_key_budgets():
    """Alert when any virtual key has used >= BUDGET_ALERT_THRESHOLD of its budget.
    Silently skips if no virtual keys are configured, activates automatically once they are."""
    data = fetch_no_params("/api/governance/virtual-keys")
    if not data:
        return
    keys = data.get("virtual_keys", [])
    if not keys:
        return
    for key in keys:
        name = key.get("name", "unknown")
        budget = key.get("budget") or {}
        limit = budget.get("limit", 0)
        used = budget.get("used", 0)
        if not limit or limit <= 0:
            continue
        rate = used / limit
        if rate >= BUDGET_ALERT_THRESHOLD:
            alert_key = f"budget_{key.get('id', name)}"
            if not already_alerted(alert_key, cooldown_polls=10):
                send_discord_alert(
                    title=f"💳 Virtual Key Budget Warning: {name}",
                    description=f"Virtual key **{name}** has used **{rate:.1%}** of its budget.",
                    color_key="error" if rate >= 0.95 else "warning",
                    fields=[
                        {"name": "Key Name", "value": name, "inline": True},
                        {"name": "Used", "value": f"${used:.4f}", "inline": True},
                        {"name": "Limit", "value": f"${limit:.4f}", "inline": True},
                        {"name": "Usage", "value": f"{rate:.1%}", "inline": True},
                        {"name": "Remaining", "value": f"${limit - used:.4f}", "inline": True},
                    ],
                )


def parse_prometheus_metric(metrics_text: str, metric_name: str) -> float | None:
    """Extract a single gauge/counter value from Prometheus text format."""
    for line in metrics_text.splitlines():
        if line.startswith(metric_name + " ") or line.startswith(metric_name + "{"):
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    return float(parts[1])
                except ValueError:
                    pass
    return None


def check_cache_hit_rate():
    """Alert if semantic cache hit rate drops below threshold.
    Silently skips if cache metrics aren't present yet, activates once semantic caching is enabled."""
    try:
        resp = requests.get(f"{BIFROST_URL}/metrics", timeout=5)
        if not resp.ok:
            return
        text = resp.text
        hits = parse_prometheus_metric(text, "bifrost_cache_hits_total")
        total = parse_prometheus_metric(text, "bifrost_upstream_requests_total")
        if hits is None or total is None or total == 0:
            return  #metrics not present yet, semantic caching not enabled
        hit_rate = hits / (hits + total)
        if hit_rate < CACHE_HIT_RATE_THRESHOLD and not already_alerted("cache_hit_rate"):
            send_discord_alert(
                title="📉 Low Cache Hit Rate",
                description=f"Semantic cache hit rate is **{hit_rate:.1%}** — below the {CACHE_HIT_RATE_THRESHOLD:.0%} threshold.",
                color_key="warning",
                fields=[
                    {"name": "Cache Hits", "value": str(int(hits)), "inline": True},
                    {"name": "Total Requests", "value": str(int(total)), "inline": True},
                    {"name": "Hit Rate", "value": f"{hit_rate:.1%}", "inline": True},
                ],
            )
    except Exception as e:
        print(f"[monitor] Failed to check cache hit rate: {e}")


def run():
    print(f"[monitor] Starting — polling every {POLL_INTERVAL}s")
    send_discord_alert(
        title="✅ Bifrost Monitor Started",
        description="Alerting service is running and watching Bifrost metrics.",
        color_key="success",
    )
    while True:
        try:
            check_bifrost_health()
            check_provider_health()
            check_error_rate()
            check_latency()
            check_latency_by_provider()
            check_cost()
            check_daily_cost()
            check_fallback_rate()
            check_virtual_key_budgets()   #activates when virtual keys are configured
            check_cache_hit_rate()        #activates when semantic caching is enabled
        except Exception as e:
            print(f"[monitor] Unexpected error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()