# v0.4.5 resumed actual-model evaluation

Observed November 11, 2026. The owner increased the ChatGPT Subscription Sharing cap from
10% to 100%; the configured GPT-6-Luna/low probe returned READY at 23:31 UTC. This establishes
working model access after the setting change, not a measured credit balance or a credit charge.
No API key, alternate model, purchase or subscription change was made by the agent.

## Matched configured-model replay

Application baseline: v0.4.4 source `eef57bcaec856b1bd56bc9b1a1a2f992b67fb61f`. Candidate
application code: `170c4f1415613d8504c4f60d0937644847fcdd58`, unchanged through `bbc04f0`.
Both lanes use GPT-6-Luna, low effort, the same frozen clock, fixture and MCP harness. The
original 28-case v0.4.4 manifest remains unchanged. All cases below are valid observations;
none called Browserbase, FlightAware, R2 uploads or a production Store.

| Recorded run | Passed / cases | Observed elapsed seconds | Model calls | LangSmith |
| --- | ---: | ---: | ---: | --- |
| model-baseline | 5/5 | 185.057 | 35 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=c12cd490-966f-46ca-a229-e28f2a61afd7) |
| model-candidate | 4/5 | 197.220 | 37 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=9e6010da-94a1-4025-ad6d-339ab0bd78c3) |
| model-baseline-WF025-rerun | 0/1 | 45.403 | 10 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=62c9a0b5-dca1-479a-8cfc-644a75733a6d) |
| model-candidate-WF025-rerun | 0/1 | 56.819 | 10 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/b0daccec-86bb-471c-a31d-6a726bf736e3/compare?selectedSessions=f1164665-127f-4a15-a92a-4dbf6602808d) |
| supplement-baseline | 0/1 | 57.629 | 12 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/faea30d1-a167-4250-8299-bdfbc6866743/compare?selectedSessions=22f9dfe4-082d-460c-afa6-7ccb1138a446) |
| supplement-candidate | 1/1 | 60.166 | 9 | [experiment](https://smith.langchain.com/o/90b24546-f3e2-4f48-af72-b06e73b27b49/datasets/faea30d1-a167-4250-8299-bdfbc6866743/compare?selectedSessions=109d171e-1784-4d85-a699-25816c295b95) |

The first pair covers WF-001/003/006/025/026. WF-025 failed on the candidate; its initial
request lists two revisions simultaneously without explicitly ordering two generations.
The candidate prepared only revision 2. On the single targeted paired rerun, both applications
retained revision 1 but did not complete revision 2; candidate also exceeded the clarification
bound. These failures remain recorded and published. The original comparison therefore reports
regressions for WF-025; this is not an all-passing actual-model comparison.

The separately frozen [WF-025-S1 supplement](../../evals/workflow_cases_v045_supplement.json)
explicitly requests generation and retention of revision 1, then revision 2, with separate exact
approvals. It was established before running either application, with unchanged fixture/clock
and harness bytes matched between checkouts. The candidate passed; baseline prepared revision 2
after approval but did not generate/finalize it. The controlled supplement also passed.
The supplemental pass does not erase the original failures or establish statistical improvement.
No application code or system prompt was changed to obtain it.

The original four other targeted scenarios passed in both lanes. Existing 28-case controlled
replay and the numerical/software matrices are recorded in the [candidate assessment](../research/v045-thrust-compatibility.md).
No duplicate Generate, unauthorized generation, changed retained OFP hash or tool/schema error
was observed in these replay runs. Expected-but-uncreated revisions account for failed retention
counts; simulator behavior and live provider behavior are outside these controlled scenarios.

## Usage and limitations

| Run | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| model-baseline | 273195 | 145024 | 3390 |
| model-candidate | 285532 | 129280 | 3984 |
| model-baseline-WF025-rerun | 86240 | 54400 | 828 |
| model-candidate-WF025-rerun | 90834 | 58624 | 1101 |
| supplement-baseline | 103316 | 68224 | 807 |
| supplement-candidate | 77702 | 48384 | 1694 |

Stage/turn latency, per-scenario tool calls, approval inputs, snapshots, raw outputs and model
usage metadata remain in the private JSON reports under `artifacts/private/v045/resumed-acceptance/`
and in the linked LangSmith outputs. Browser/queue latency is unavailable in replay; provider
HTTP/session usage is zero because those services are controlled. Model invoice/credit cost is
unknown. LangSmith root latency measures recorded-result upload lookup; actual scenario time
is in `outputs.metrics`. Isolated runs do not establish quality or latency improvements.

WF-025 remains an explicit conversation/evaluation limitation for release review. No simulator
engine, native PERF, import behavior or numerical aircraft accuracy is verified by these results.
Verified aircraft support remains 0/51.
