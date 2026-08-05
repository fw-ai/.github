#!/usr/bin/env python3
"""Rate limit characterization for Kimi K2.6 on Fireworks serverless."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

MODEL = "accounts/fireworks/models/kimi-k2p6"
API_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
RATE_LIMIT_HEADERS = [
    "x-ratelimit-limit-tokens-prompt",
    "x-ratelimit-limit-tokens-cache-adjusted-prompt",
    "x-ratelimit-limit-tokens-generated",
    "x-ratelimit-remaining-tokens-prompt",
    "x-ratelimit-remaining-tokens-cache-adjusted-prompt",
    "x-ratelimit-remaining-tokens-generated",
    "x-ratelimit-over-limit",
    "retry-after",
]


@dataclass
class RequestResult:
    phase: str
    index: int
    status_code: int
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def extract_rate_headers(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in RATE_LIMIT_HEADERS:
        if key in headers:
            out[key] = headers[key]
    return out


async def send_request(
    client: httpx.AsyncClient,
    *,
    phase: str,
    index: int,
    prompt: str,
    max_tokens: int,
) -> RequestResult:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    started = time.perf_counter()
    try:
        response = await client.post(API_URL, json=payload)
        latency = time.perf_counter() - started
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {}

        usage = body.get("usage") or {}
        error = None
        if response.status_code >= 400:
            error = body.get("error", body)

        return RequestResult(
            phase=phase,
            index=index,
            status_code=response.status_code,
            latency_s=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            error=str(error) if error else None,
            headers=extract_rate_headers(response.headers),
        )
    except Exception as exc:  # noqa: BLE001
        return RequestResult(
            phase=phase,
            index=index,
            status_code=0,
            latency_s=time.perf_counter() - started,
            error=str(exc),
        )


async def run_phase(
    client: httpx.AsyncClient,
    *,
    phase: str,
    count: int,
    concurrency: int,
    prompt: str,
    max_tokens: int,
    delay_s: float = 0.0,
) -> list[RequestResult]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[RequestResult] = []

    async def one(index: int) -> None:
        async with semaphore:
            if delay_s > 0:
                await asyncio.sleep(index * delay_s)
            results.append(
                await send_request(
                    client,
                    phase=phase,
                    index=index,
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
            )

    await asyncio.gather(*(one(i) for i in range(count)))
    return sorted(results, key=lambda item: item.index)


def summarize(results: list[RequestResult]) -> dict[str, Any]:
    by_status: dict[int, int] = {}
    latencies = [r.latency_s for r in results if r.status_code == 200]
    header_samples: list[dict[str, str]] = []
    for result in results:
        by_status[result.status_code] = by_status.get(result.status_code, 0) + 1
        if result.headers:
            header_samples.append(result.headers)

    latest_headers = header_samples[-1] if header_samples else {}
    return {
        "total": len(results),
        "status_counts": by_status,
        "success_rate": by_status.get(200, 0) / len(results) if results else 0.0,
        "latency_s": {
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "mean": statistics.mean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
        },
        "latest_rate_limit_headers": latest_headers,
        "first_429_index": next(
            (r.index for r in results if r.status_code == 429),
            None,
        ),
        "first_503_index": next(
            (r.index for r in results if r.status_code == 503),
            None,
        ),
        "sample_errors": [
            {"index": r.index, "status": r.status_code, "error": r.error}
            for r in results
            if r.status_code != 200
        ][:5],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        raise SystemExit("FIREWORKS_API_KEY is required")

    timeout = httpx.Timeout(120.0, connect=30.0)
    headers = {"Authorization": f"Bearer {api_key}"}

    report: dict[str, Any] = {
        "model": MODEL,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phases": {},
        "raw_results": [],
    }

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        phases = [
            {
                "name": "baseline_single",
                "count": 1,
                "concurrency": 1,
                "prompt": "Reply with exactly one word: hello.",
                "max_tokens": 16,
            },
            {
                "name": "steady_low_parallel",
                "count": 10,
                "concurrency": 2,
                "prompt": "In one short sentence, explain what rate limiting means.",
                "max_tokens": 64,
            },
            {
                "name": "moderate_parallel",
                "count": 20,
                "concurrency": 5,
                "prompt": "Write a 2-sentence summary of adaptive token rate limits.",
                "max_tokens": 128,
            },
            {
                "name": "burst_parallel",
                "count": 30,
                "concurrency": 15,
                "prompt": "List five synonyms for 'fast'.",
                "max_tokens": 64,
            },
            {
                "name": "heavy_output",
                "count": 8,
                "concurrency": 4,
                "prompt": "Write a detailed 150-word explanation of HTTP 429 errors.",
                "max_tokens": 256,
            },
            {
                "name": "recovery_wait",
                "count": 5,
                "concurrency": 1,
                "prompt": "Say OK.",
                "max_tokens": 8,
                "delay_s": 2.0,
            },
        ]

        for spec in phases:
            phase_name = spec["name"]
            print(f"Running phase: {phase_name}", flush=True)
            results = await run_phase(
                client,
                phase=phase_name,
                count=spec["count"],
                concurrency=spec["concurrency"],
                prompt=spec["prompt"],
                max_tokens=spec["max_tokens"],
                delay_s=spec.get("delay_s", 0.0),
            )
            report["phases"][phase_name] = summarize(results)
            report["raw_results"].extend(asdict(r) for r in results)
            await asyncio.sleep(3)

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
