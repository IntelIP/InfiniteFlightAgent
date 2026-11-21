# v0.5.2 staging acceptance

The temporary Worker `infinite-flight-dispatcher-v052-acceptance` ran
source `27648102c77ad067a4fd16f609d348dab691daa9` as Worker version
`212c406d-6898-49c8-9e21-5f863ec4f9a0`. Its public health endpoint
returned 401. The acceptance client used an authenticated Container SSH
tunnel to the deployed MCP service, which reported v0.5.2 and a database connection.

On November 21, 2026 UTC, trip `v052-acceptance-20261121` generated two
private A320neo legs through SimBrief after separate approval waits.

| Leg | Route | Result |
| --- | --- | --- |
| 1 | KIAD–KEWR | Generated and retained with takeoff data |
| 2 | KEWR–KIAD | Generated and retained with takeoff data |

Both approval prompts and both dispatch results included distinct LangSmith
trace links. The [database record](live-acceptance.json) shows both retained
plans, distinct snapshots, takeoff data and the approval/resume checkpoints.
All four BUILD-04 outcomes passed. Browserbase recorded two completed sessions
totaling 99.2 seconds, with zero active sessions after the run.

This run used the staging Worker. Production promotion and the production
smoke check are recorded separately. Thrust values remain simulation-grade estimates.
