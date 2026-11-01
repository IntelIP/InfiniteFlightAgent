# Offline flight fixtures

These assets were authored by GPT-6-Astra for offline evaluation. Astra authored the deterministic generator in the coding session; the generator itself makes no provider or model API calls.

## Synthetic dataset

`synthetic_cases.jsonl` contains 12 prompts in the existing dispatch-prompt shape, plus a repo-relative `fixture` path. `synthetic/SYNTH-001.json` through `SYNTH-012.json` contain invented flights; every synthetic flight ID starts with `SYNTH-`. These are not real-world schedules or provider recordings.

Cases cover normal route search, successful empty results, missing gates/equipment, codeshares, truncated pagination, delays, cancellation, US DST fallback, UTC/local date rollover, flight-number lookup, departure-board filtering, and an HTTP 503 failure. The synthetic clock is fixed at `2026-10-31T09:13:00+00:00`. Airport names follow the cited historical transcript; the test timezone follows the existing flight tests. All flight-level values are invented.

```sh
python3 evals/fixtures/build_recordings.py --source-root /path/to/artifacts/evals
python3 evals/fixtures/build_synthetic.py
python evals/fixtures/validate_assets.py
```

The generators use only the standard library. Validation needs the project's existing Python environment (`httpx` is imported by `flights.py`). Validation replaces the HTTP function with exact fixture lookup before invoking flight functions: it cannot make provider requests. The synthetic generator reads `synthetic_sources.json` for source provenance, so it can regenerate the invented fixtures without access to the private historical captures.

## Reconstructed historical snapshots

`recorded/IFD-*.json` contains **87 partial reconstructed snapshots**, marked `kind: derived_recording`, selected from the latest available capture with reconstructable flight source references. These are **not raw HTTP replays**. `recording_coverage.json` lists all 100 original case IDs: 87 have some reconstructable requests and 13 are uncovered. **24 of the 87 have missing airport metadata**, listed per case. Missing names/timezones stay absent, rather than being fabricated. No placeholder fixtures are emitted for uncovered cases.

The original captures contain normalized tool results without tool arguments or raw responses. The builder:

- Uses the first `current_time` result per selected case, or the first observed timestamp if no clock tool was recorded.
- Extracts endpoint and UTC bounds from source references, and applies the constants in `flights.py` to reconstruct the query. Bounds inferred to be relative to the clock are rebased to the frozen clock.
- Restores raw-shaped fields only from available normalized values. It retains only the already filtered flight subset and the first result for each exact request.
- Recovers airport names from approval text and `check_airports`, including other historical cases with source attribution. UTC/local pairs support fixed `Etc/GMT` offsets only; these are not recovered IANA zones and cannot reconstruct DST transitions. Fractional offsets are left unresolved.
- Leaves discarded arrival timestamps unavailable, so the original `historical` classification is not guaranteed to round-trip. It does not invent timestamps to force that classification.
- Uses `num_pages: 1` as an explicitly documented structural placeholder, not measured usage. A recorded truncation flag becomes a nonempty placeholder link; it is not a valid continuation URL.
- Cannot recover departure-board airline query arguments, omitted pre-filter flights, or raw occurrences behind `recent_gates` summaries. Only the generic board query is reconstructed; recent-gate summaries are omitted.

Every recovered metadata source appears in provenance with original path, SHA-256 and case ID. Original captures remain untouched. `covered_count` means a fixture has some supported requests; it does not mean a full agent conversation can replay successfully. Changed search dates, alternative query arguments, unsupported metadata lookups and unrecorded calls must fail closed in the parent runtime. An HTTP failure must never be replaced with an empty successful response.

## Direct checks

`validate_assets.py` validates all 99 fixture contracts, unique exact request keys, and all 12 synthetic scenarios against the current `flights.py`. It checks missing values, marketing/operating codeshare identity, pagination, delays, cancellation, the 25-hour fallback date, repeated 01:30 EDT/EST times, UTC/local date rollover, flight lookup, board padding/exclusive end filtering and HTTP error handling. This is offline fixture validation, not evidence of live provider behavior or successful model evaluation. The existing 100-case dataset validator has hard-coded IDs/counts and is not intended for this separate synthetic manifest.
