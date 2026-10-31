# Cloudflare deployment

Status October 31, 2026: scaffolding only. Nothing has been deployed, no cloud resources exist, and the release workflows have not run. Owner decision: single-user personal deployment of the open-source app with the owner's own keys and ChatGPT plan.

## Architecture

```text
MCP client (ChatGPT / Claude / Codex)
  │  HTTPS, Cloudflare Access managed OAuth (owner's email only)
  ▼
Cloudflare Access ── rejects unauthenticated requests at the edge
  │  Cf-Access-Jwt-Assertion
  ▼
Worker  infinite-flight-dispatcher            deploy/cloudflare/src/index.ts
  • verifies the Access JWT against the team JWKS (iss = team domain, aud = ACCESS_AUD),
    optional ACCESS_ALLOWED_EMAIL; missing config → 503, no token → 401, bad token → 403
  • forwards only /mcp and /health (all methods, streamed both ways)
  • strips the Access JWT and cookies, adds X-IFD-Internal-Token
  ▼
Durable Object "dispatcher" (DispatcherContainer, durable_object scheduling policy)
  • starts one container (standard-1, internet on, 15 min inactivity timeout)
    with secrets as environment variables
  • restarts it when secrets, the paid-operations flag, or the image change
  ▼
Container  repo-root Dockerfile → uv run --locked --no-dev ifd-serve on 0.0.0.0:8080
  └─► OpenAI (ChatGPT plan), FlightAware AeroAPI, SimBrief, Browserbase, Neon, R2, LangSmith
```

Cloudflare Access does the OAuth for MCP clients; the Worker does not implement OAuth. The Worker's JWT check exists so a deleted or misconfigured Access application fails closed.

## Resources the owner creates

| Resource | Notes |
| --- | --- |
| Cloudflare Workers Paid plan | Required for Containers |
| Access application for the Worker hostname | Self-hosted app with managed OAuth for MCP clients enabled; one Allow policy containing only the owner's email. Copy the team domain (`https://<team>.cloudflareaccess.com`) and the application AUD tag |
| Cloudflare API token | Workers Scripts and Containers edit permissions, scoped to the one account |
| Neon project and database | Pooled connection string → `DATABASE_URL` |
| R2 bucket and S3 API token | Bucket-scoped read/write token → `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`; plus `R2_ACCOUNT_ID`, `R2_BUCKET` |
| Doppler project and config | Holds `DATABASE_URL`, `IFD_CREDENTIAL_KEY`, `IFD_INTERNAL_TOKEN` (random, 32+ bytes), `AEROAPI_KEY`, `BROWSERBASE_API_KEY`, `BROWSERBASE_SIMBRIEF_CONTEXT_ID`, `SIMBRIEF_USERID`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`, the four `R2_*` values, and `IFD_PAID_OPERATIONS_ENABLED` (`"false"` until the first validation passes). Create a read-only service token for that config |
| GitHub repository secrets | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `DOPPLER_TOKEN` |
| GitHub repository variables | `DOPPLER_PROJECT`, `DOPPLER_CONFIG`, `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ACCESS_ALLOWED_EMAIL` (optional) |
| GitHub environment `production` | Required reviewer: the owner. Gates promotion and bootstrap |

`DATABASE_URL`, `IFD_CREDENTIAL_KEY`, and `IFD_INTERNAL_TOKEN` are required: `scripts/sync-secrets.sh` and Wrangler's `secrets.required` check refuse to upload without them. `IFD_PAID_OPERATIONS_ENABLED` is a Worker secret rather than a `[vars]` entry so the emergency stop can change it without new code; a missing value is passed to the container as `"false"`.

## Workflows

- `ci.yml`: pull requests, pushes to `main`, and release checks. Python: `uv sync --locked`, pytest, ruff, dead-code check. Worker: `npm ci`, `wrangler types --check`, `tsc --noEmit`, auth-gate unit tests (`node --test`).
- `release.yml` (manual): checks the exact commit, syncs secrets from Doppler into a temporary file, then `wrangler versions upload --secrets-file …` builds the image with Docker and uploads a version with no traffic. The version id is in the job summary. With `promote=true`, the `production` environment approval gates `wrangler versions deploy <id>@100% -y`.
- `emergency-stop.yml` (manual, type `STOP`): sets `IFD_PAID_OPERATIONS_ENABLED=false` with `wrangler secret put`.

`scripts/sync-secrets.sh` can also be run locally (`DOPPLER_PROJECT=… DOPPLER_CONFIG=… scripts/sync-secrets.sh`) to push secrets with `wrangler secret bulk`, which deploys a new version of the current code immediately. It prints key names only.

## First deploy

1. Create the resources above with `IFD_PAID_OPERATIONS_ENABLED=false` in Doppler.
2. Import ChatGPT-plan credentials (below).
3. Run **Release** with `bootstrap=true` and approve `production`. A first upload must use `wrangler deploy`: `wrangler versions upload` cannot create a Worker or apply the Durable Object migration. This version takes traffic immediately, behind Access, with paid operations off. The first container provisioning can take several minutes.
4. Validate: from an Access-authenticated browser open `https://<worker-host>/health` (expect 200 JSON); without Access, expect a block or 401/403. Connect one MCP client and make one call, such as a flight lookup.
5. Set `IFD_PAID_OPERATIONS_ENABLED=true` in Doppler when ready, then release again.

Later releases: run **Release** with `promote=false`, review the uploaded version, then rerun with `promote=true` (a new upload of the same commit), or promote the recorded id with `npx wrangler versions deploy <id>@100% -y`. Version preview URLs are not generated for Workers with Durable Objects, so validation happens after promotion. Durable Object–managed containers do not take part in image rollouts; the Worker restarts the running container on its next request when the image or secrets differ from what it started with, ending any in-flight stream.

## Kill switch and emergency stop

- **Paid operations flag**: `IFD_PAID_OPERATIONS_ENABLED=false` stops spending inside the Python server. Run **Emergency stop**, then also set it to `false` in Doppler, or the next release restores the old value.
- Limits: `wrangler secret put` fails if an uploaded version is waiting for promotion (Wrangler refuses to edit secrets when the latest version is not deployed). Use the Cloudflare dashboard (Worker → Settings → Variables and Secrets → deploy) in that case, and do not leave uploads unpromoted. Requests already running continue until they finish; the container restarts with the new value on the next request. The flag does not revoke keys: for a leaked or compromised key, rotate it at the provider (OpenAI, AeroAPI, Browserbase, Neon, R2, LangSmith), update Doppler, and release.
- **Full stop**: disable the Access application's Allow policy or the Worker route in the dashboard. Every request is then rejected at the edge.

## Rollback

`npx wrangler rollback <version-id>` (or `npx wrangler versions deploy <version-id>@100% -y`) from `deploy/cloudflare`. Rollback cannot cross a Durable Object migration. Rolling back restores that version's code, secrets, and image reference; the Worker restarts the container on the next request.

## Costs to watch

- Cloudflare Containers: billed for CPU, memory, and disk while the instance runs (standard-1: 1/2 vCPU, 4 GiB); the 15-minute inactivity timeout limits idle time. Workers Paid base fee and request/Durable Object usage.
- Browserbase session minutes (each SimBrief generation opens a cloud browser).
- FlightAware AeroAPI per-result-set charges.
- ChatGPT plan limits: the five-hour limit is shared with every app on the plan, including Codex.
- Neon compute hours and R2 storage/operations (small at single-user volume).

## ChatGPT-plan credentials

The OAuth callback goes to `127.0.0.1`, so Sign in with ChatGPT runs locally (`uv run ifd-login`). Then import the resulting credential once into the deployment with `ifd-credentials import` (Python side; uses `IFD_CREDENTIAL_KEY` and `DATABASE_URL`). After import the deployed host owns refreshes; stop using the same credential locally. This follows OpenAI's [self-hosted VM guidance](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms): complete OAuth locally with the same client and user, transfer the protected credential over a secure channel, keep a stable host id on the server, and let the server own refreshes. OpenAI notes that host-specific usage attribution and revocation for transferred sessions are not yet available. Confirm the ChatGPT-plan terms permit this personal hosted use before enabling it.

## Not yet validated

The container image has not been built (Docker was not running on the authoring Mac). `wrangler deploy --dry-run` was validated only with a placeholder registry image. No Access, Doppler, Neon, R2, or GitHub resources exist, and none of the workflows has run.
