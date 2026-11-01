# Contributing

Thanks for helping. Bug reports, aircraft data, evaluation cases, and fixes are all welcome.

## Set up

```bash
uv sync --locked
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
bash scripts/check-dead-code.sh
```

The Cloudflare Worker lives in `deploy/cloudflare` (`npm ci`, `npx tsc --noEmit`, `node --test`). Pull requests run the same checks in CI.

Set `TEST_DATABASE_URL` to a disposable Postgres database to run the Postgres-only tests.

## Ground rules

- **Never invent flight data or thrust numbers.** Flights come from FlightAware; takeoff performance comes from SimBrief. If a value is unavailable, say so explicitly.
- **Keep thrust mode, FLEX temperature, N1 target, and throttle position distinct.** An aircraft only counts as supported when it meets the acceptance criteria in [docs/goal.md](docs/goal.md).
- **Anything that spends money or writes to someone's account needs explicit user approval.** That includes FlightAware calls, Browserbase sessions, and SimBrief generation.
- **Unit tests do not prove live behavior.** Changes to agent behavior should be checked with the evaluation set (`evals/run_eval.py`). That run spends your own AeroAPI and ChatGPT-plan usage, so say in the pull request what you ran.
- **Never commit secrets.** `.env` is Git-ignored; use `.env.example` for new setting names.

## Live acceptance

The **Product validation** check (`scripts/validate.py`) passes only when the local checks pass and [`docs/evidence/live-acceptance.json`](docs/evidence/live-acceptance.json) shows every live outcome the SimBrief integration needs: generation through the deployed MCP service, a real neo plan, two legs kept after the latest plan changed, and an approval wait and resume. The evidence is tied to the integration code that was live (`src/ifdispatcher`, the Worker, the Dockerfile and `uv.lock`). When a pull request changes that code, the check reports `blocked` until someone releases it, runs a live two-leg trip, and records it with `scripts/record_live_acceptance.py` (usage is in its docstring). Changes to docs, tests and evaluations keep the existing evidence valid.

## Adding an evaluation case

Add a line to `evals/dispatch_prompts.jsonl` and run `python3 evals/validate_dataset.py`. Cases describe the first message, scripted follow-up answers, and the expected behavior, not exact wording.

## License

By contributing, you agree that your contributions are licensed under [GPL-3.0-only](LICENSE).
