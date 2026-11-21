# Security policy

Report vulnerabilities privately through [GitHub security advisories](https://github.com/IntelIP/InfiniteFlightAgent/security/advisories/new). Do not open a public issue.

Include what you found, how to reproduce it, and its impact. We aim to reply within a week.

## Scope

In scope: this repository's code, including the MCP servers, the Cloudflare Worker's authentication gate, credential storage (`ifd-credentials`), and the release workflows.

Out of scope: vulnerabilities in FlightAware, SimBrief, Browserbase, OpenAI, Cloudflare, Neon, or Doppler themselves. Report those to the vendor.

## If your keys leak

Every deployment uses its owner's own keys. `NAVIGRAPH_PASSWORD`, if set, is your Navigraph account password: the cloud browser types it into Navigraph's sign-in form and nothing else reads, logs, or returns it. If any key is exposed, rotate it at the provider first, then update your secret store and redeploy. On a deployed server, `IFD_PAID_OPERATIONS_ENABLED=false` stops new paid work but does not revoke keys; see [deployment](docs/implementation/deployment.md#kill-switch-and-emergency-stop).

## Dependency advisories

The release owner triages an advisory against the exact package versions in uv.lock, the Worker package-lock.json, or the container named by the release's image digest. Record the advisory ID, affected range, installed version, production or development use, and owner. Check dependencies covered by Dependabot ignore rules individually. For a replacement, check applicable vendor and model provenance before selecting it.

For an affected component, record the first fixed version and open a patch against the locked dependency or base-image digest. Run the affected path, including the Linux Playwright driver smoke test for browser changes. If a fixed version breaks compatibility, record the mitigation, owner, expiry date and retest condition privately. Close the finding after linking the release or deployed digest that carries the fix.

A November 20, 2026 exercise traced historical CVE-2022-29217 to production PyJWT. Both uv.lock and package metadata in the local Linux image reported 2.15.1, beyond the advisory's 2.4.0 fix. GitHub returned zero open Dependabot alerts at the time of the exercise. [Upstream advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffqj-6fqr-9h24)
