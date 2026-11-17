# This fork: turing-labs-hq/graphiti

A fork of graphiti (via `Briancorish/graphiti`) that builds the graph service Turing's Brain runs
inside loop (`loop.turinglabs.ai`). Its image is built by `.github/workflows/image.yml` on a push to
`main`, pushed to Turing's AWS ECR as `loop-stack/graphiti`, and reported to Mission Control. It is
deployed into loop as the `graphiti` block of loop-stack.

## What differs from upstream, and why

| Change | Why |
| --- | --- |
| `.github/workflows/image.yml` (ours) | builds and reports the image loop runs; the report bearer lives in the `image-report` environment, restricted to `main` |
| Deleted: `ai-moderator.yml`, `cla.yml`, `claude.yml`, `claude-code-review.yml`, `claude-code-review-manual.yml`, `pr-triage.yml`, `release-graphiti-core.yml`, `release-mcp-server.yml`, `release-server-container.yml` | upstream's own automation: AI review and triage bots, the contributor agreement bot and the PyPI and Docker Hub releases. None is used here, several ran on outsiders' events (`pull_request_target`, issue comments) with `id-token: write` or write permissions, which this repo must not offer since it deploys into loop. Deleting them is what keeps them off: workflows that never ran cannot be disabled through GitHub's API |
| `lint.yml` runs on `pull_request`, not `pull_request_target` | no workflow runs in the base context for a PR here |
| `runs-on: ubuntu-latest` instead of `depot-ubuntu-*` | Depot runners are upstream's paid pool and do not exist in this org: every run of lint, type check and the tests was cancelled before this change |
| The test jobs start `falkordb/falkordb:v4.20.6`, not `latest` | the version loop runs (tl-platform catalog block `falkordb`); `latest` moved `db.idx.fulltext.createNodeIndex` to a new signature and broke the database integration tests, and production should be what is tested |
| `actions/checkout` steps set `persist-credentials: false`; `mcp_server/docker/Dockerfile` builds `FROM falkordb/falkordb:v4.20.6@sha256:...`, not `latest` | Aikido findings: no job here pushes, so none keeps the token in `.git/config`; a moving base tag is a supply-chain risk. Keep both through a sync |
| `graphiti_core/telemetry/telemetry.py` reads its PostHog key from `GRAPHITI_POSTHOG_API_KEY` (unset: telemetry off) | Aikido leaked-secret finding on upstream's hard-coded (public, write-only) Zep project key; this fork does not report usage to Zep by default. Keep through a sync |
| The root `Dockerfile` mounts `uv` from a pinned `ghcr.io/astral-sh/uv` image only while building, runs `apt-get upgrade`, upgrades pip and installs no curl | Aikido container findings: the uv binary bundles vulnerable Rust crates (quinn-proto, quinn-udp, zerovec) even in its latest release and is not needed at runtime; pip and the Debian packages lag the base tag. Keep through a sync |

## Syncing from upstream

Keep the deletions: a modify/delete conflict on one of the files above resolves to "deleted". Keep
`ubuntu-latest` and the `pull_request` trigger. Re-read any new upstream workflow before it reaches
`main`: a new one that runs on outsiders' events or asks for `id-token: write` gets deleted or
disabled here, a new `depot-` runner gets `ubuntu-latest`, and the FalkorDB pin follows loop's catalog when loop upgrades.
