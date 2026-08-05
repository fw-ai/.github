# Kimi K2.6 Serverless Rate Limiting Test Report

**Date:** August 5, 2026  
**Provider:** Fireworks AI (serverless)  
**Model:** `accounts/fireworks/models/kimi-k2p6`  
**Endpoint:** `POST https://api.fireworks.ai/inference/v1/chat/completions`

---

## Executive Summary

Kimi K2.6 on Fireworks serverless exposes **adaptive per-model token rate limits** via response headers. Under moderate parallel load (≤15 concurrent, ≤512 output tokens), all **224/224 requests succeeded** with no throttling. Under an aggressive burst of **200 tiny requests at 100-way concurrency**, **12/200 (6%) returned HTTP 429**, triggered by **generated-token TPM exhaustion** (`x-ratelimit-remaining-tokens-generated: 0`), not prompt-token or account RPM limits.

The observed adaptive ceiling for generated tokens **dropped from 216,000 TPM to 36,000 TPM** during the burst, demonstrating the adaptive shrink behavior described in Fireworks docs.

---

## Observed Rate Limit Headers

After sustained load, all three TPM dimensions are reported:

| Header | Observed Limit (TPM) | Docs Default Ceiling |
|--------|---------------------:|---------------------:|
| `x-ratelimit-limit-tokens-prompt` | 11,250,000 | 21,600,000 |
| `x-ratelimit-limit-tokens-cache-adjusted-prompt` | 5,400,000 | 5,400,000 |
| `x-ratelimit-limit-tokens-generated` | 216,000 → **36,000** (after burst) | 216,000 |

Equivalent TPS (limit ÷ 60):

| Dimension | Initial TPS | Post-burst TPS |
|-----------|------------:|---------------:|
| Total prompt | 187,500 | 187,500 |
| Uncached prompt | 90,000 | 90,000 |
| Generated | 3,600 | **600** |

The account's effective prompt limit (11.25M TPM) is below the documented default ceiling, consistent with adaptive limits that grow with usage history.

---

## Test Phases

### Phase 1 — Characterization (74 requests, moderate load)

| Phase | Requests | Concurrency | Success | 429 | 503 | Avg Latency |
|-------|----------|-------------|---------|-----|-----|-------------|
| Baseline single | 1 | 1 | 1/1 | 0 | 0 | 0.45s |
| Steady low parallel | 10 | 2 | 10/10 | 0 | 0 | 1.25s |
| Moderate parallel | 20 | 5 | 20/20 | 0 | 0 | 4.13s |
| Burst parallel | 30 | 15 | 30/30 | 0 | 0 | 1.73s |
| Heavy output (256 tok) | 8 | 4 | 8/8 | 0 | 0 | 5.44s |
| Recovery (2s spacing) | 5 | 1 | 5/5 | 0 | 0 | 4.64s |

**Finding:** No throttling at ≤15 concurrency with output up to 256 tokens. Remaining-token counters decrement predictably but stay well above zero.

### Phase 2 — Token Stress (150 requests, high concurrency)

| Scenario | Requests | Concurrency | Success | 429 | 503 |
|----------|----------|-------------|---------|-----|-----|
| stress_50x20 | 50 | 20 | 50/50 | 0 | 0 |
| stress_100x50 | 100 | 50 | 100/100 | 0 | 0 |

**Finding:** Even 50-way concurrent requests with 512 max output tokens did not trigger 429. Generated-token remaining stayed above zero (lowest observed: ~208,898 of 216,000).

### Phase 3 — RPM / Generated-TPM Burst (200 requests, 100-way concurrency)

| Metric | Value |
|--------|------:|
| Total requests | 200 |
| Concurrency | 100 |
| `max_tokens` | 1 |
| Wall time | 3.13s |
| Effective RPM | ~3,840 |
| Success (200) | 188 (94%) |
| Throttled (429) | 12 (6%) |
| Load shed (503) | 0 |

**429 trigger condition:**

```
x-ratelimit-remaining-tokens-generated: 0
x-ratelimit-limit-tokens-generated: 36000   (shrunk from 216000)
x-ratelimit-over-limit: no                  (still reports "no")
```

**429 error body:**

```json
{
  "object": "error",
  "type": "invalid_request_error",
  "code": "invalid_request_error",
  "message": "rate limit exceeded, please try again later"
}
```

First 429 appeared at request index 18 (~0.23s into the burst). All 429 responses returned in <260ms (fail-fast, no queueing).

---

## Key Findings

### 1. Generated TPM Is the First Bottleneck for Burst Traffic

When firing many concurrent requests with even minimal output (`max_tokens=1`), the **generated-token bucket exhausts first**. Prompt-token remaining stayed above 11.2M (of 11.25M limit) at the time of 429s.

### 2. Adaptive Limits Shrink Under Burst

The generated-token limit dropped from **216,000 → 36,000 TPM** (6× reduction) during the burst test. This matches Fireworks' documented adaptive behavior: limits grow and shrink based on usage patterns; ramping too quickly causes 429s.

### 3. `x-ratelimit-over-limit: no` on 429 Responses

Even when returning HTTP 429, the `x-ratelimit-over-limit` header remained `"no"`. Clients should treat **HTTP status code 429** and **`remaining-tokens-*: 0`** as the authoritative throttle signals, not the over-limit flag alone.

### 4. No 503 Load Shedding Observed

Across 374 total requests, zero `503 Service Overloaded` responses were observed. Throttling manifested exclusively as 429 rate-limit errors.

### 5. Account RPM Limit Not Hit

Peak effective throughput was ~3,840 RPM, well below the documented 6,000 RPM account-wide ceiling. The 429s in Phase 3 were token-bucket driven, not request-count driven.

---

## Recommendations for Kimi K2.6 Clients

1. **Always set `max_tokens` explicitly** — Kimi K2.6 can produce long reasoning traces; unbounded output accelerates generated-TPM consumption.
2. **Use exponential backoff on 429** — Fail-fast responses (<300ms) indicate bucket exhaustion; retry after a brief delay.
3. **Monitor all three header dimensions** — Track `remaining-tokens-prompt`, `remaining-tokens-cache-adjusted-prompt`, and `remaining-tokens-generated`.
4. **Ramp concurrency gradually** — Jumping to 50–100 concurrent requests causes adaptive limit shrink and 429s even when per-request token usage is tiny.
5. **Separate rate-limit from load-shed** — 429 = token/RPM bucket; 503 = deployment saturation. Different remediation strategies apply.

---

## Artifacts

| File | Description |
|------|-------------|
| `scripts/kimi_k2p6_rate_limit_test.py` | Phased characterization test harness |
| `scripts/kimi_k2p6_stress_test.py` | High-concurrency token stress test |
| `kimi-k2p6-rate-limit-results.json` | Raw results from Phase 1 |
| `kimi-k2p6-stress-results.json` | Raw results from Phase 2 |
| `kimi-k2p6-rpm-stress.json` | Raw results from Phase 3 burst |

---

## References

- [Fireworks Serverless Rate Limits](https://docs.fireworks.ai/serverless/rate-limits)
- [Account Quotas & RPM Limits](https://docs.fireworks.ai/guides/quotas_usage/account-quotas)
- [Kimi K2 Family on Fireworks](https://docs.fireworks.ai/models/kimi-k2)
