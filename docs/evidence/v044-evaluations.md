# v0.4.4 matched workflow evaluations

Observed November 11, 2026 UTC. Baseline application: v0.4.3 source
`710513f5d6c868a90e1aa8041dbcf689c0c476c0`. Candidate application bytes match
`e064d2fa9f793fade23742e7bab50e28fa0ebc58`; the final application change is
`839d3647e086e60ee46ebca4b08ce62d8ff267b1`.

The expanded acceptance manifest was established before fixes. Its 28 cases retain the
original eight case definitions unchanged. Matched baseline and candidate runs use the
same final fixtures, synthetic airframe options, verifier, loopback MCP transport and
frozen clock (`2026-11-08T11:00:00Z`). Both actual-model runs use the existing configured
GPT-6 Luna model, low effort, through the existing ChatGPT-plan access.

| Lane/application | Applicable cases passed | Invalid | Clarification turns | LangSmith |
| --- | ---: | ---: | ---: | --- |
| scripted-baseline | 20/28 | 0 | 1 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=66c7355c-3e9a-438e-9738-f916d4fbece2) |
| scripted-candidate | 28/28 | 0 | 1 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=341724a2-5494-4ff5-b874-0a95fb0daace) |
| model-baseline | 17/28 | 0 | 2 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=e5ad88c9-0fea-4d94-90ff-d76e30a5c0e5) |
| model-candidate | 28/28 | 0 | 2 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=c8f35a7a-6d25-413b-89f1-9932d2d59065) |

Clarification counts include necessary incomplete-intent questions. They are not a claim
of reduced unnecessary clarification. Settled-input and missing-arrival outcomes have
separate deterministic checks. Both final comparisons have zero case regressions and
zero fixture/model/clock/harness compatibility errors. Every final scenario has zero tool
schema errors. Candidate checks establish exact approval, no duplicate Generate, no
unauthorized generation, no lost retained legs and bounded controlled browser behavior.
Expected refusals and unavailable outcomes count as passing only when their scenario
contract is satisfied; 28/28 does not mean every requested flight was generated.

The fast lane uses a scripted model and controlled services. The second lane uses the
actual production agent and configured model with the same controlled services. Both
exercise actual MCP tools, saved snapshots/briefings/revisions, approvals and persistent
checkpoint recovery. Neither lane opens Browserbase, calls FlightAware, or exercises
Cloudflare Access OAuth. Actual queue/browser latency is null; simulated failures are
not live provider incidents. Per-scenario completion, clarification/continuation,
tool/schema errors, stage/turn latency, token usage and provider-call fields are retained
in the reports and LangSmith records. Model invoice cost and owner ratings are unknown.

Suite SHA-256: `417223bbf3635f844ec1afeee7434b602f36b9b1d17d8441b58ccaf2ae778e3b`.
Harness SHA-256: `34ad226ba9c6f2bf839a90be76af2e715a9b7633984933cd256f059889cc227e`.
The baseline uses the documented evaluation-only overlay over v0.4.3. Candidate runs
recorded a dirty worktree before the final evaluation commits; their per-file source
hashes were compared with the committed checkout and match exactly. They are evidence
for those recorded bytes, rather than falsely described as clean-commit executions.

Earlier diagnostic runs exposed missing airframe fixtures, a replay transport read timeout,
parallel-approval handling and safe pre-click refill guidance. Their failures/invalid
labels remain retained. The final complete matched sets above were rerun after corrections;
no failed run was relabeled as successful. Private full reports, original diagnostics,
source comparisons and LangSmith readback receipts are under Git-ignored
`artifacts/private/v044/`. LangSmith readback confirmed 28 root runs with deterministic
feedback in each experiment.

These are individual scenario observations. They establish neither a statistical quality
or latency improvement nor live routing timing, numerical aircraft accuracy or simulator
support. Bounded deployed and exact-release-image acceptance are recorded separately.
