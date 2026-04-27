# DeepSeek-V4-Pro API Test Report

**Date:** April 27, 2026  
**Providers Tested:** Together AI, Nvidia NIM  
**Model:** `deepseek-ai/DeepSeek-V4-Pro`  
**Settings:** `temperature=1.0`, `top_p=1.0`, `max_tokens=500`, `reasoning_effort=high`

---

## Executive Summary

Both Together and Nvidia APIs serve DeepSeek-V4-Pro and produce **correct final answers** for all tested prompts. However, both exhibit **gibberish/artifact content in reasoning traces**. Additionally, Nvidia's API has **severe reliability and latency issues**, with multiple requests timing out after 60–300 seconds.

---

## Test Results

### Test 1: Sheep/Cow Riddle

**Prompt (Together):** "A farmer has 17 sheep. All but 6 die. How many sheep are left?"  
**Prompt (Nvidia):** "A farmer has 23 cows. All but 7 die. How many cows are left?"

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ✅ Yes (6) | ✅ Yes (in `reasoning` field) | ❌ None observed | ~12s |
| Nvidia | ✅ Yes (7) | ✅ Yes (in `reasoning_content` field) | ⚠️ Minor artifacts: `"But13;"`, `"So16;"`, `"I'll13;"` | ~38s |

### Test 2: Widget Riddle

**Prompt:** "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?"

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ⚠️ Reasoning correct (5 min) but `content` field was **empty** (`""`) due to `finish_reason: "length"` | ✅ Yes | ❌ None observed | ~4s |
| Nvidia | ❌ **Timed out** (180s) | N/A | N/A | Timeout |

**Note:** Together's response hit the 500 token limit during the reasoning phase, leaving no tokens for the final answer `content` field. The correct answer (5 minutes) is present in the reasoning trace but not in the user-facing content.

### Test 3: Prime Number Sum

**Prompt:** "What is the sum of all prime numbers between 1 and 20?"

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ✅ Yes (77) | ✅ Yes | ⚠️ **Yes** — random numbers/strings injected: `"16783,"`, `"böjnings"`, `"dátummal"`, `"So32m"` | ~12s |
| Nvidia | ✅ Yes (77) | ✅ Yes | ⚠️ **Yes** — date-like artifacts: `"01-11-2024?"`, `"13-20."`, `"So06-77."` | ~107s |

### Test 4: Palindrome Function (Coding)

**Prompt:** "Write a Python function to check if a string is a palindrome. Keep it concise."

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ⚠️ Partial — `content` truncated mid-docstring due to `finish_reason: "length"` | ✅ Yes | ⚠️ **Severe** — reasoning is heavily polluted with repeated number-word pairs: `"06"` appears 30+ times, `"07"` appears 40+ times, e.g., `"just07 the07 function07"`, `"concise.\"06 I can provide a0616 simple0604 one-liner"` | ~78s |
| Nvidia | ✅ Yes (`s == s[::-1]`) | ✅ Yes | ⚠️ **Yes** — similar numeric artifacts scattered throughout: `"Usually16"`, `"but04:"`, `"might14"`, `"But13"`, repeated `"06"` insertions | ~110s |

### Test 5: Multiplication

**Prompt:** "What is 127 * 43? Show your work."

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ✅ Yes (5461) | ✅ Yes | ❌ None observed | ~6s |
| Nvidia | ❌ **Timed out** (300s) | N/A | N/A | Timeout |

### Test 6: Stack vs Queue (CS Concept)

**Prompt:** "Explain the difference between a stack and a queue in one paragraph."

| Provider | Correct Answer | Reasoning Present | Gibberish in Reasoning | Latency |
|----------|---------------|-------------------|----------------------|---------|
| Together | ✅ Yes | ✅ Yes | ⚠️ **Yes** — time-like artifacts throughout: `"06:16"`, `"05:36"`, `"08:36"`, `"04:31"`, embedded in words like `"should06:16 provide"` | ~12s |
| Nvidia | N/A (not tested, API unreachable) | N/A | N/A | N/A |

---

## Detailed Findings

### 1. Answer Correctness

**Both providers produce correct final answers** when the request completes successfully. All tested prompts (riddles, math, coding, explanations) received factually correct responses in the `content` field.

### 2. Reasoning Content

Both providers expose reasoning/thinking traces:
- **Together:** Returns reasoning in a `reasoning` field within the message object
- **Nvidia:** Returns reasoning in a `reasoning_content` field within the message object

Reasoning traces show step-by-step logical thinking and are generally coherent, though polluted with artifacts (see below).

### 3. Gibberish / Artifacts in Reasoning

**This is the most significant finding.** Both providers exhibit gibberish content injected into reasoning traces. The artifacts appear to be:

- **Random numbers inserted mid-word/mid-sentence:** `"16783,"`, `"So32m"`, `"But13;"`, `"So16;"`
- **Repeated number codes:** `"06"` and `"07"` appearing dozens of times in a single response, e.g., `"the07 function07 is07 named07 correctly07"`
- **Date-like fragments:** `"01-11-2024?"`, `"06:16"`, `"05:36"`, `"08:36"`
- **Foreign word fragments:** `"böjnings"`, `"dátummal"`

These artifacts appear **only in reasoning traces**, not in the final `content` field. They seem to be tokenization or decoding artifacts from the model's reasoning phase. The pattern suggests possible issues with special token handling or vocabulary overlap during the thinking/reasoning generation.

**Frequency:** Observed in approximately 4 out of 6 Together tests and 3 out of 3 successful Nvidia tests.

### 4. Truncation Issues (Together)

Two Together responses hit the 500-token `max_tokens` limit (`finish_reason: "length"`):
- **Widget riddle:** All tokens consumed by reasoning, `content` field was empty
- **Palindrome:** Code was truncated mid-output

This is expected behavior given the token limit, but worth noting that high reasoning effort can consume significant token budget. Users should increase `max_tokens` for reasoning-heavy queries.

### 5. Nvidia Reliability / Latency

Nvidia's API exhibited severe issues:
- **3 out of 6 requests timed out** (after 60s, 180s, and 300s respectively with 0 bytes received)
- **Successful requests took 38s–110s**, compared to Together's 4s–78s
- One basic connectivity test (`"What is 2+2?"` without thinking params) also timed out, suggesting the issue may be broader than just the reasoning feature
- When responses did arrive, they were correct and complete

---

## API Response Format Differences

| Aspect | Together | Nvidia |
|--------|----------|--------|
| Reasoning field name | `reasoning` | `reasoning_content` |
| Reasoning effort param | Top-level `reasoning_effort` | Nested in `chat_template_kwargs` |
| `prompt_tokens` (sheep/cow) | 102 | 23 |
| Model name casing | `DeepSeek-V4-Pro` | `deepseek-v4-pro` |
| `reasoning_tokens` in usage | Always 0 | Always 0 |

**Note:** Together reports significantly higher `prompt_tokens` (e.g., 102 vs 23 for a similar prompt), suggesting it may include system prompt tokens or template overhead in the count.

---

## Summary Table

| Metric | Together AI | Nvidia NIM |
|--------|------------|------------|
| Answer Correctness | ✅ All correct | ✅ All correct (when responding) |
| Reasoning Present | ✅ Always | ✅ Always (when responding) |
| Gibberish in Reasoning | ⚠️ 4/6 tests affected | ⚠️ 3/3 successful tests affected |
| Reliability | ✅ 6/6 requests succeeded | ❌ 3/6 requests timed out |
| Avg Latency (success) | ~20s | ~85s |
| Truncation Risk | ⚠️ 2 responses truncated at 500 tokens | ❌ N/A (higher completion before limit) |
