#!/usr/bin/env python3
"""Aggressive Kimi K2.6 rate-limit stress test."""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx

MODEL = "accounts/fireworks/models/kimi-k2p6"
URL = "https://api.fireworks.ai/inference/v1/chat/completions"


async def one(client: httpx.AsyncClient, i: int) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write a detailed 300-word essay about distributed systems, "
                    "covering consistency, availability, and partition tolerance."
                ),
            }
        ],
        "max_tokens": 512,
    }
    started = time.perf_counter()
    try:
        resp = await client.post(URL, json=payload)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return {
            "index": i,
            "status": resp.status_code,
            "latency_s": round(time.perf_counter() - started, 3),
            "error": body.get("error"),
            "headers": {
                k: v
                for k, v in resp.headers.items()
                if k.startswith("x-ratelimit") or k == "retry-after"
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "index": i,
            "status": 0,
            "latency_s": round(time.perf_counter() - started, 3),
            "error": str(exc),
            "headers": {},
        }


async def main() -> None:
    api_key = os.environ["FIREWORKS_API_KEY"]
    timeout = httpx.Timeout(180.0, connect=30.0)
    headers = {"Authorization": f"Bearer {api_key}"}

    scenarios = [
        {"name": "stress_50x20", "count": 50, "concurrency": 20},
        {"name": "stress_100x50", "count": 100, "concurrency": 50},
    ]

    report: dict = {"scenarios": {}}
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        for spec in scenarios:
            print(f"Running {spec['name']}", flush=True)
            sem = asyncio.Semaphore(spec["concurrency"])

            async def run(i: int) -> dict:
                async with sem:
                    return await one(client, i)

            results = await asyncio.gather(*(run(i) for i in range(spec["count"])))
            status_counts: dict[int, int] = {}
            for r in results:
                status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
            report["scenarios"][spec["name"]] = {
                "status_counts": status_counts,
                "first_429": next((r for r in results if r["status"] == 429), None),
                "sample_429s": [r for r in results if r["status"] == 429][:3],
                "sample_503s": [r for r in results if r["status"] == 503][:3],
            }
            await asyncio.sleep(5)

    with open("/workspace/kimi-k2p6-stress-results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
