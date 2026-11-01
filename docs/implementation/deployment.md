# Cloudflare deployment

Status October 31, 2026: nothing has been deployed and the release workflows have not run. Created so far (none are secrets):

- GitHub repository [IntelIP/InfiniteFlightAgent](https://github.com/IntelIP/InfiniteFlightAgent) (public), `production` environment (owner review, `main` only), variables `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ACCESS_ALLOWED_EMAIL`, secret `CLOUDFLARE_ACCOUNT_ID`.
- Neon project `InfiniteFlightDispatcher` (`summer-fog-90424455`, aws-us-east-1, Postgres 18, database `neondb`).
- R2 bucket `infinite-flight-dispatcher` (ENAM).
- Access application "Infinite Flight Agent MCP" (`82c02dde-b5fa-4a48-b518-5c3256608d55`) for `infinite-flight-dispatcher.hudson-228.workers.dev`: managed OAuth with dynamic client registration on, one Allow policy for the owner's email, team domain `restless-mouse-67bc.cloudflareaccess.com`.
- Workers Paid was already active on the account.
- Doppler project `infinite-flight-agent`, config `prd`: every key above, with `IFD_PAID_OPERATIONS_ENABLED=false`. `IFD_INTERNAL_TOKEN` and `IFD_CREDENTIAL_KEY` were generated directly into Doppler; `DATABASE_URL` is the Neon pooled endpoint (connection checked). The R2 keys come from an account API token limited to Object Read & Write on `infinite-flight-dispatcher`; write, read and delete there succeeded, and listing all buckets or reading two other buckets was denied. Read-only service token `github-release-readonly` is the GitHub secret `DOPPLER_TOKEN`; variables `DOPPLER_PROJECT` and `DOPPLER_CONFIG` are set.

- GitHub secret `CLOUDFLARE_API_TOKEN`: account API token with Workers Scripts Edit, Workers Containers Edit and Account Settings Read (verified active; R2 access refused). Account API tokens cannot be created with CLI OAuth, so it and the R2 token were made in the dashboard.

Still needed: merge to `main`, the ChatGPT credential import, then the bootstrap release. Owner decision: single-user personal deployment of the open-source app with the owner's own keys and ChatGPT plan. License: GPL-3.0-only (owner decision, October 31, 2026), because the thrust estimator ports GPL-3.0 FlyByWire tables.

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
- `release.yml` (manual): refuses anything but the current `main` commit, runs CI on it, syncs secrets from Doppler into a temporary file, then `wrangler versions upload --secrets-file …` builds the image with Docker and uploads a version with no traffic. The version id is in the job summary, and each job uploads a `release-*` evidence artifact (Wrangler output, `wrangler versions view` of the candidate, deployment status before and after, commit and version id). With `promote=true`, the `production` environment approval gates `wrangler versions deploy <id>@100% -y`.
- `emergency-stop.yml` (manual, type `STOP`): sets `IFD_PAID_OPERATIONS_ENABLED=false` with `wrangler secret put`.

`scripts/sync-secrets.sh` can also be run locally (`DOPPLER_PROJECT=… DOPPLER_CONFIG=… scripts/sync-secrets.sh`). Without arguments it is a dry run that checks the required keys and lists the names it would sync; `--apply` pushes them with `wrangler secret bulk`, which deploys a new version of the current code immediately. It prints key names only.

## First deploy

1. Create the resources above with `IFD_PAID_OPERATIONS_ENABLED=false` in Doppler.
2. Import ChatGPT-plan credentials (below).
3. Run **Release** with `bootstrap=true` and approve `production`. A first upload must use `wrangler deploy`: `wrangler versions upload` cannot create a Worker or apply the Durable Object migration. This version takes traffic immediately, behind Access, with paid operations off. The first container provisioning can take several minutes.
4. Validate: from an Access-authenticated browser open `https://<worker-host>/health` (expect 200 JSON); without Access, expect a block or 401/403. Connect one MCP client and make one call, such as a flight lookup.
5. Set `IFD_PAID_OPERATIONS_ENABLED=true` in Doppler when ready, then release again.

Later releases: run **Release** with `promote=false`, review the uploaded version, then rerun with `promote=true` (a new upload of the same commit), or promote the recorded id with `npx wrangler versions deploy <id>@100% -y`. Version preview URLs are not generated for Workers with Durable Objects, so validation happens after promotion. Durable Object–managed containers do not take part in image rollouts; the Worker restarts the running container on its next request when the image or secrets differ from what it started with, ending any in-flight stream.

## Notes from Condere's release process

Read from `Products/Condere` on October 31, 2026 (`apps/mcp/docs/release-policy.md`, `.buildkite/release.yml`, `.buildkite/scripts/release-prepare.sh`, `docs/cloud-run.md`, `docs/environment-policy.md`). Condere deploys to Google Cloud Run through Buildkite rather than Cloudflare, so the practices transfer but the commands do not. These are observations and proposals, not decisions. Condere's own write-up is `Products/Condere/docs/release-playbook.md` (draft, covering `main` at `1dfc2379`). It reports that the trusted Buildkite release path is fully written but **has never run end to end**: no candidate has been prepared, accepted, promoted, or rolled back. Treat it as a design. The deployment that has actually run in production is the spin-off's, recorded in the shared `deployment-playbook.md`.

Already matched here:

- Prepare a candidate with no traffic; live acceptance and promotion are separate gates.
- A paid-operations kill switch that fails closed: the Worker passes anything other than `"true"` as `"false"`. Condere's runtime keeps a compatibility default of enabled when the value is missing, so it binds the switch explicitly on every deploy.
- Doppler is the operator source of truth, and runtime secrets are copied into the platform's secret store (Secret Manager there, Worker secrets here). The container never holds a `DOPPLER_TOKEN`.
- A documented emergency stop and rollback. Condere's stop targets job names that its new release no longer creates. Ours cannot drift this way: the stop and the release both use `deploy/cloudflare/wrangler.toml`, so they target the same Worker.

Gaps found, and their state:

1. **Release only the exact `origin/main` commit.** Condere's prepare script refuses anything other than a trusted, non-PR build whose `HEAD` equals `origin/main`. Closed: `release.yml` now fails unless dispatched from `main` at its current head.
2. **Keep release evidence.** Condere saves `preflight.json`, `previous.json` (traffic before), `candidate.json`, and `verification.json` as build artifacts and fails if the candidate does not match. Closed: each release job uploads the Wrangler output, `wrangler deployments status` before and after, the candidate's `wrangler versions view`, and the commit and version id.
3. **Pin the image by digest.** Condere deploys `repository@sha256:…` and records commit, digest, and acceptance source in the runtime environment. Wrangler builds and pushes our image during `versions upload` and pins it in the version; the evidence artifact keeps the version record. Whether that record shows the image digest is unverified until the first real upload.
4. **Secret sync should default to a dry run.** Condere documented this pattern (`sync_doppler_gcp_secrets.sh`, list keys unless `--apply`), but that script was removed on 2026-08-24 and its syncs are now manual. Closed: `scripts/sync-secrets.sh` is now a dry run unless given `--apply`.
5. **Approve before preparing.** Condere puts a manual block step before candidate preparation as well as before promotion. Our upload runs without approval; that is acceptable only while it cannot take traffic or spend.
6. **Before enabling paid work:** one bounded live run with retained usage receipts (AeroAPI result sets, Browserbase minutes, ChatGPT plan usage), stop on uncertain cost, and pin the exercised version before moving traffic.

Checked against the shared playbook's pitfalls (`AgenticEngineering/openwiki/deployment-playbook.md`, the executed Condere spin-off deployment):

- **R2 checksums:** fixed. `artifacts.py` now sets `request_checksum_calculation` and `response_checksum_validation` to `when_required`; R2 rejects botocore's default CRC checksums.
- **R2 key scope:** at creation, round-trip an object in our bucket and confirm another bucket returns `AccessDenied`. The playbook observed an all-bucket key.
- **Neon pooler:** verified. Our locks are transaction-scoped (`pg_advisory_xact_lock`) and every connection disables server-side prepared statements. The playbook sends DDL and the LangGraph checkpointer to the direct endpoint; here the full Postgres suite (57 tests, including checkpointer setup and the credential refresh lock) passed through the pooled endpoint of a throwaway branch of the new project on October 31, 2026.
- **Long MCP tool calls:** closed. `approve_dispatch` can take about two minutes (Browserbase generation), and the playbook observed client timeouts. Agent turns now run in a background thread; a tool returns its result within 25 seconds or `status: running`, and the client polls `turn_status`. A container restart loses the in-memory turn (the checkpoint survives), and `turn_status` then reports `not_found`.
- **Cloudflare API token:** CLI OAuth cannot mint API tokens; create the release token in the dashboard.
- **Rotating refresh token:** handled. `ifd-credentials import --move` gives the deployment its own host id, removes the local session, and refreshes under a database lock.
- **Per-process limits:** the AeroAPI rate limiter is in memory. That is correct while the Durable Object runs one container; it needs a database slot if more instances run.

Open owner decisions this raises:

- **CI provider.** Condere's repository CI and release run on Buildkite, using workload identity federation instead of stored cloud keys. This repository uses GitHub Actions. Either works with Wrangler. Buildkite would match the portfolio; GitHub Actions avoids another agent queue for a single-user app.
- **Doppler layout.** Condere uses one Doppler project per deployable with `dev`/`stg`/`prd` configs (`intelip-agent-mcp`, `intelip_api`). This deployment follows that pattern with its own `infinite-flight-agent` project, created after the October 31 consolidation freed slots.

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

The container image builds for linux/amd64 and was run locally: `/health` returns ok, `/mcp` returns 401 without the internal token, an MCP client lists the two tools, and `plan_flight` returns `paid_operations_disabled` with the switch off. `wrangler deploy --dry-run` was validated only with a placeholder registry image. No Access, Doppler, Neon, R2, or GitHub resources exist, and none of the workflows has run.
