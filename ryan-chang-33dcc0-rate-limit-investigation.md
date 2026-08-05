# Investigation: Rate Limiting for `ryan-chang-33dcc0` (Clay)

**Account:** `accounts/ryan-chang-33dcc0` (`Clay [Production]`, ryan.chang@clay.com)  
**Window:** last 24h from 2026-08-05 ~17:40 UTC (covering 2026-08-04 17:40 → 2026-08-05 17:40)  
**Primary model involved:** `accounts/fireworks/models/kimi-k2p6` / deployment `accounts/fireworks/deployments/kimi-k2p6`  
**Source:** GCP Managed Prometheus (`fw-ai-cp-prod`) + billing usage API

---

## Verdict

Clay was rate-limited on **Kimi K2.6**, but **not because sustained TPM sat at their adaptive ceilings**.

Prometheus records **62 HTTP 429s** with:

| Field | Value |
|-------|-------|
| `rejection_reason` | `tokens_prompt` |
| `http_code_allowlisted` | `429` |
| Deployment | `kimi-k2p6` |
| When | **2026-08-05 01:21–01:23 UTC** (8 + 39 + 15) |

That lines up with a sharp traffic ramp on kimi-k2p6 (≈25 → **349 req/min** within ~6 minutes). Adaptive limits were still raising during the burst. This matches Fireworks’ documented behavior: ramping too quickly causes 429s even when average utilization looks “fine.”

---

## Why dashboards can look under-limit

Against **global RLM** limits for kimi-k2p6 (5‑minute averages), peak utilization in the last 24h was:

| Dimension | Peak rate | Adaptive limit | Peak util |
|-----------|----------:|---------------:|----------:|
| `tokens_generated` | ~7,040 | ~17,334 | **~41%** |
| `tokens_prompt` | ~68,264 | ~533,334 | **~13%** |
| `tokens_cache_adjusted_prompt` | ~27,860 | 200k→250k | **~11–14%** |

So if you only compare smoothed rate mirrors to current limits, Clay does **not** look like they hit TPM caps.

Two important caveats:

1. **`tokens_prompt` rate_mirror was missing/0 during the exact 429 window**, so that dimension’s utilization is not observable at the moment of rejection.
2. Limits were **still adapting upward** during the incident (see below), so a short admission burst can exceed the *then-current* bucket even if later averages look low.

---

## Incident timeline (kimi-k2p6, 2026-08-05 UTC)

Successful request volume (per-minute deltas from `requests_total_per_account_total`):

| Time (UTC) | Successful req/min | `tokens_prompt` 429s | Other errors |
|------------|-------------------:|---------------------:|-------------:|
| 01:16 | 25 | 0 | 0 |
| 01:17 | 118 | 0 | 0 |
| 01:18 | 206 | 0 | 0 |
| 01:19 | 307 | 0 | 0 |
| 01:20 | 345 | 0 | 0 |
| **01:21** | **349** | **8** | 0 |
| **01:22** | **277** | **39** | 2 |
| **01:23** | **194** | **15** | 5 |
| 01:24 | 154 | 0 | 5 |
| 01:25 | 110 | 0 | 3 |

Adaptive limits on the same deployment during that hour:

| Metric | Before burst | After raise |
|--------|-------------:|------------:|
| `global_rlm_tokens_prompt_limit_per_account` | 426,667 | **533,334** |
| `global_rlm_tokens_cache_adjusted_prompt_limit_per_account` | 200,000 | **250,000** |
| `global_rlm_tokens_generated_limit_per_account` | 13,867 | **17,334** |

Additional signal: **`global_rlm_tokens_cache_adjusted_prompt_limit_at_upper_bound_per_account = 1`** for kimi-k2p6 throughout — uncached/cache-adjusted prompt limit is pinned at its ceiling and cannot auto-raise further. No 429s were labeled `tokens_cache_adjusted_prompt` in this window (count ≈ 0), but the ceiling being maxed is relevant for headroom.

No meaningful volume of:

- `concurrency_limit` (583)
- `pid_shed_load` (583)

in this window.

---

## Usage context (billing API, serverless)

Rough 24h serverless token volume for this account:

| Model | Prompt tokens | Cached prompt | Completion |
|-------|--------------:|--------------:|-----------:|
| **kimi-k2p6** | **~335M** (across day buckets) | **~266M** | **~11.6M** |
| deepseek-v4-flash | ~46M | ~0 | ~9.0M |
| glm-5p2 | ~15.4M | ~9.6M | ~1.1M |
| kimi-k3 | ~0.5M | ~0.2M | ~19k |

Kimi K2.6 dominates. Cache hit rate on kimi-k2p6 is high (~79% of prompt tokens cached in the latest day bucket), which is why cache-adjusted headroom matters.

Account has **no on-demand deployments** (`deployments` list empty) — this is serverless-only for inference.

---

## What did *not* cause it

- **Account-wide 6,000 RPM cap:** peak observed request throughput on kimi-k2p6 was ~5–6 RPS (~300–350 RPM), far below 6,000.
- **Sustained generated-TPM exhaustion:** peak ~41% of adaptive generated limit.
- **Sustained total-prompt TPM exhaustion (as averaged):** peak ~13% of adaptive prompt limit in rate_mirror (with the caveat that mirror data was absent during the 429 minute).
- **Load shed / concurrency 583s:** essentially none in the incident window.

Note on `requests_limit_per_account`: the series is stuck at **1.0** for kimi-k2p6 while successful traffic clearly runs at several RPS. Treat that series as a **stale/floor signal**, not the effective request limiter. The authoritative rejection label is `tokens_prompt`.

---

## Root-cause summary

1. Clay ramped **kimi-k2p6** hard around **01:16–01:21 UTC**.
2. The rate limiter rejected **62 requests** as **`tokens_prompt` / HTTP 429** at **01:21–01:23**.
3. Adaptive prompt / cache-adjusted / generated limits were mid-raise; cache-adjusted prompt was already **at upper bound**.
4. Smoothed TPM utilization metrics therefore **understate** why 429s happened — this is a **burst / adaptive-ramp** problem on the prompt-token dimension, not “they sat at 100% of the published ceiling for hours.”

---

## Suggested follow-ups

1. Confirm with Clay the client concurrency / retry behavior around 01:20 UTC (likely a batch or agent fan-out).
2. If they need higher prompt/uncached headroom on kimi-k2p6, raise the **cache-adjusted prompt ceiling** (already at upper bound) and/or grant a reservation — adaptive alone cannot lift it further.
3. Advise gradual ramp + exponential backoff on 429; document that `rejection_reason=tokens_prompt` can fire during bursts even when Grafana averages look &lt;50%.
4. Investigate why `tokens_prompt_rate_mirror_per_account` went to 0 during the incident (observability gap on the exact rejecting dimension).

---

## Prometheus queries used

```promql
# Adaptive limits
global_rlm_tokens_prompt_limit_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}
global_rlm_tokens_cache_adjusted_prompt_limit_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}
global_rlm_tokens_generated_limit_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}
global_rlm_tokens_cache_adjusted_prompt_limit_at_upper_bound_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}

# Rate mirrors
tokens_prompt_rate_mirror_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}
tokens_cache_adjusted_prompt_rate_mirror_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}
tokens_generated_rate_mirror_per_account{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6"}

# Rejections (authoritative)
requests_total_per_account_total{account="ryan-chang-33dcc0", deployment="accounts/fireworks/deployments/kimi-k2p6", rejection_reason="tokens_prompt"}
```
