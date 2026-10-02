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

## Syncing from upstream

Keep the deletions: a modify/delete conflict on one of the files above resolves to "deleted". Keep
`ubuntu-latest` and the `pull_request` trigger. Re-read any new upstream workflow before it reaches
`main`: a new one that runs on outsiders' events or asks for `id-token: write` gets deleted or
disabled here, and a new `depot-` runner gets `ubuntu-latest`.
