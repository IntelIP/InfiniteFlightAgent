# Security policy

Report vulnerabilities privately through [GitHub security advisories](https://github.com/IntelIP/InfiniteFlightAgent/security/advisories/new). Do not open a public issue.

Include what you found, how to reproduce it, and its impact. We aim to reply within a week.

## Scope

In scope: this repository's code, including the MCP servers, the Cloudflare Worker's authentication gate, credential storage (`ifd-credentials`), and the release workflows.

Out of scope: vulnerabilities in FlightAware, SimBrief, Browserbase, OpenAI, Cloudflare, Neon, or Doppler themselves. Report those to the vendor.

## If your keys leak

Every deployment uses its owner's own keys. If one is exposed, rotate it at the provider first, then update your secret store and redeploy. On a deployed server, `IFD_PAID_OPERATIONS_ENABLED=false` stops new paid work but does not revoke keys; see [deployment](docs/implementation/deployment.md#kill-switch-and-emergency-stop).
