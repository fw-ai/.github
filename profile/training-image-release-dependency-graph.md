# Training Image Release — GitHub Actions Dependency Graph

## Overview

The "training image" release pipeline spans **two primary repos** and involves
**six GitHub Actions workflows** plus a **server-side (internal) training image
build** that is not managed in any public GitHub Action. The public repos build
and validate the **dependencies** that go into the training image (FlashInfer
wheels, CI Docker images) and the **client-side SDK/cookbook** that exercises
the training image via smoke tests.

---

## Repos and Workflows

### 1. `fw-ai/flashinfer` (14 workflows total, 4 relevant)

| Workflow | File | Triggers | Purpose |
|----------|------|----------|---------|
| **Release CI Docker** | `release-ci-docker.yml` | push to `main` (paths: `docker/**`), PR, `workflow_dispatch` | Builds multi-arch CI Docker images (`flashinfer-ci-cu{126,128,129,130}`) and pushes to Docker Hub |
| **Nightly Release** | `nightly-release.yml` | cron daily 00:00 UTC, `workflow_dispatch` | Builds flashinfer-python, flashinfer-cubin, and flashinfer-jit-cache wheels; runs GPU tests; creates nightly GitHub Release; updates wheel index |
| **Release** | `release.yml` | `workflow_dispatch` (with tag), PR (dry-run) | Stable release: builds all wheels, creates GitHub Release, publishes to PyPI, updates wheel index |
| **PR Test** | `pr-test.yml` | push to `main`, PR, `workflow_dispatch` | Runs AOT build import tests + GPU unit tests (A10G, T4, H100) using the CI Docker images |

### 2. `fw-ai/cookbook` (2 workflows total, 2 relevant)

| Workflow | File | Triggers | Purpose |
|----------|------|----------|---------|
| **Training CI** | `training-ci.yml` | PR (paths: `training/**`), push to `main`, `workflow_dispatch` | Unit + import tests for the training SDK/cookbook |
| **Training Smoke** | `training-smoke.yml` | cron daily 08:13 UTC, `workflow_dispatch` | End-to-end smoke tests (SFT, DPO, GRPO) against `dev.api.fireworks.ai` using real GPU trainers |

### 3. Server-Side (Internal — not a public GitHub Action)

The actual **training image** (the Docker image that runs on Fireworks GPU
trainers) is built internally. The smoke tests reference it via
`FIREWORKS_CUSTOM_IMAGE_TAG` (a GitHub Actions variable, not a workflow).

---

## Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────┐
│                    fw-ai/flashinfer                                  │
│                                                                     │
│  ┌──────────────────────┐                                           │
│  │ Release CI Docker    │  (1) Builds CI Docker images              │
│  │ release-ci-docker.yml│──────────┐                                │
│  │                      │          │ creates PR to update            │
│  │ Trigger: push main   │          │ ci/docker-tags.yml              │
│  │   (docker/**),       │          ▼                                │
│  │   workflow_dispatch  │  ┌──────────────────┐                     │
│  └──────────────────────┘  │ ci/docker-tags.yml│                    │
│                            │ (pinned image     │                    │
│                            │  tags for CI)     │                    │
│                            └────────┬─────────┘                     │
│                                     │ read by                       │
│                                     ▼                               │
│  ┌──────────────────────┐  ┌──────────────────────┐                 │
│  │ Nightly Release      │  │ PR Test              │                 │
│  │ nightly-release.yml  │  │ pr-test.yml          │                 │
│  │                      │  │                      │                 │
│  │ Trigger: cron daily  │  │ Trigger: push main,  │                 │
│  │   workflow_dispatch  │  │   PR, dispatch       │                 │
│  └──────────┬───────────┘  └──────────────────────┘                 │
│             │                                                       │
│             │ builds wheels                                         │
│             ▼                                                       │
│  ┌──────────────────────┐                                           │
│  │ Release              │                                           │
│  │ release.yml          │                                           │
│  │                      │                                           │
│  │ Trigger: manual      │                                           │
│  │   (workflow_dispatch │                                           │
│  │    with tag)         │                                           │
│  └──────────┬───────────┘                                           │
│             │                                                       │
│             │ publishes to PyPI                                     │
│             │ + wheel index                                         │
│             ▼                                                       │
│  ┌──────────────────────┐                                           │
│  │ flashinfer wheels    │                                           │
│  │ on PyPI + GitHub     │                                           │
│  │ Releases             │                                           │
│  └──────────┬───────────┘                                           │
│             │                                                       │
└─────────────┼───────────────────────────────────────────────────────┘
              │
              │ installed as dependency
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              SERVER-SIDE (Internal)                                  │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                   │
│  │ Training Image Build (internal CI/CD)        │                   │
│  │                                              │                   │
│  │ Consumes:                                    │                   │
│  │  • flashinfer wheels (from Release/Nightly)  │                   │
│  │  • flash-attention wheels                    │                   │
│  │  • PyTorch, CUDA base images                 │                   │
│  │  • fireworks training SDK                    │                   │
│  │                                              │                   │
│  │ Produces: training Docker image              │                   │
│  │  (referenced by FIREWORKS_CUSTOM_IMAGE_TAG)  │                   │
│  └──────────────────┬───────────────────────────┘                   │
│                     │                                               │
└─────────────────────┼───────────────────────────────────────────────┘
                      │
                      │ validated by
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    fw-ai/cookbook                                    │
│                                                                     │
│  ┌──────────────────────┐     ┌──────────────────────┐              │
│  │ Training CI          │     │ Training Smoke       │              │
│  │ training-ci.yml      │     │ training-smoke.yml   │              │
│  │                      │     │                      │              │
│  │ Trigger: PR, push    │     │ Trigger: cron daily  │              │
│  │   main, dispatch     │     │   workflow_dispatch  │              │
│  │                      │     │                      │              │
│  │ Runs: unit tests,    │     │ Runs: e2e smoke on   │              │
│  │   import checks      │     │   dev.api.fireworks  │              │
│  │   (no GPU needed)    │     │   (real GPU trainers) │              │
│  └──────────────────────┘     └──────────────────────┘              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Internal Job Dependency Chains

### Release CI Docker (`release-ci-docker.yml`)
```
generate-tag ──► build (matrix: 4 CUDA × 2 arch) ──► create-manifests ──► update-docker-tags
                                                          │                      │
                                                     (only on push)        (only push to main)
                                                                           Creates PR to update
                                                                           ci/docker-tags.yml
```

### Nightly Release (`nightly-release.yml`)
```
setup ──┬──► build-flashinfer-python ──┐
        ├──► build-flashinfer-cubin  ──┤
        └──► build-flashinfer-jit-cache┤ (matrix: 3 CUDA × 2 arch)
                                       │
                              all three ▼
                         ┌─► create-release
                         │
                         └─► test-nightly-build (matrix: 2 CUDA × 5 shards)
                                    │
                                    ▼
                              jit-cache-summary
                                    │
                         (both complete)
                                    ▼
                           update-wheel-index
```

### Release (`release.yml`)
```
setup ──┬──► build-flashinfer-python ──┐
        ├──► build-flashinfer-cubin  ──┤
        └──► build-flashinfer-jit-cache┤
                                       │
                              all three ▼
                           create-release
                                 │
                         ┌───────┴───────┐
                         ▼               ▼
                  publish-to-pypi  update-wheel-index
```

### PR Test (`pr-test.yml`)
```
gate (permission check)
  │
  ▼
setup (reads ci/docker-tags.yml for image tag)
  │
  ├──► aot-build-import (spot, matrix: 2 arch × 4 CUDA)
  │        │ (on failure)
  │        ▼
  │    analyze-aot-failure ──► aot-build-import-rerun (on-demand)
  │
  ├──► gpu-tests-a10g (spot, 5 shards)
  │        │ (on failure)
  │        ▼
  │    analyze-gpu-a10g-failure ──► gpu-tests-a10g-rerun (on-demand)
  │
  ├──► gpu-tests-t4 (spot)
  │        │ (on failure)
  │        ▼
  │    analyze-gpu-t4-failure ──► gpu-tests-t4-rerun (on-demand)
  │
  └──► gpu-tests-h100 (capacity block, no rerun)
                │
                ▼
       test-results-summary (aggregates all results)
```

---

## What Blocks Training Image Release

The training image is built **server-side** (internally), not by a public
GitHub Action. However, the following public workflows form the **dependency
chain** that must succeed before a training image can be released:

### Critical Path (blocking)

1. **FlashInfer Release CI Docker** → CI Docker images must be built and
   tagged before any FlashInfer tests can run.

2. **FlashInfer PR Test** → Must pass on PRs before merging FlashInfer
   changes. Uses CI Docker images from step 1.

3. **FlashInfer Nightly Release** (or **Release**) → Must succeed to produce
   the flashinfer wheels (flashinfer-python, flashinfer-cubin,
   flashinfer-jit-cache) that get installed into the training image.

4. **Internal Training Image Build** → Consumes flashinfer wheels + other
   deps to produce the training Docker image.

5. **Training Smoke** (`fw-ai/cookbook`) → Validates the training image
   end-to-end by running SFT/DPO/GRPO against `dev.api.fireworks.ai`. Uses
   `FIREWORKS_CUSTOM_IMAGE_TAG` to target a specific training image version.

### Non-blocking (gating quality, not release)

- **Training CI** (`fw-ai/cookbook`) → Runs unit/import tests for the
  client-side SDK. Does not interact with the training image. Blocks
  cookbook PRs but not the image release.

- **FlashInfer pre-commit, docs, Claude review, CODEOWNERS** → Quality/hygiene
  workflows in `fw-ai/flashinfer`. Not on the release critical path.

---

## Cross-Repo Workflow Interactions

| From | To | Mechanism |
|------|----|-----------|
| `flashinfer/release-ci-docker` | `flashinfer/pr-test` | Indirect: Docker images built by release-ci-docker are referenced via `ci/docker-tags.yml` which pr-test reads |
| `flashinfer/release-ci-docker` | `flashinfer/nightly-release` | Same: nightly-release reads `ci/docker-tags.yml` to get Docker image tags for test jobs |
| `flashinfer/nightly-release` | Internal training image build | Wheels from nightly release are consumed by the internal build |
| `flashinfer/release` | Internal training image build | Wheels from stable release are consumed by the internal build |
| Internal training image | `cookbook/training-smoke` | Smoke tests validate the training image via `FIREWORKS_CUSTOM_IMAGE_TAG` |

**No direct `workflow_call` or `workflow_run` cross-repo triggers exist.**
All cross-repo dependencies are **artifact-based** (Docker images on Docker Hub,
wheels on PyPI/GitHub Releases, training images in internal registry).

---

## Key Environment Variables / Secrets

| Variable | Repo | Used By | Purpose |
|----------|------|---------|---------|
| `FIREWORKS_CUSTOM_IMAGE_TAG` | cookbook | training-smoke | Pin specific training image version |
| `FIREWORKS_API_KEY` | cookbook | training-smoke | Auth for dev.api.fireworks.ai |
| `DOCKERHUB_TOKEN` | flashinfer | release-ci-docker | Push CI Docker images |
| `FLASHINFER_BOT_TOKEN` | flashinfer | release-ci-docker, ci-bot-commands | Create PRs for docker tag updates |
| `PYPI_API_TOKEN` | flashinfer | release | Publish wheels to PyPI |
| `WHL_TOKEN` | flashinfer | release, nightly-release | Push to flashinfer-ai/whl index |

---

## Summary Diagram (Simplified)

```
FlashInfer Docker Build ──► FlashInfer CI/Tests ──► FlashInfer Wheel Release
                                                            │
                                                            ▼
                                              Internal Training Image Build
                                                            │
                                                            ▼
                                              Cookbook Training Smoke Tests
                                                            │
                                                            ▼
                                                    Training Image GA
```

Each arrow represents a blocking dependency. A failure at any stage prevents
the downstream stages from completing successfully.
