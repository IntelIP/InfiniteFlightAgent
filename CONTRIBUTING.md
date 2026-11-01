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

## Adding an evaluation case

Add a line to `evals/dispatch_prompts.jsonl` and run `python3 evals/validate_dataset.py`. Cases describe the first message, scripted follow-up answers, and the expected behavior, not exact wording.

## License

By contributing, you agree that your contributions are licensed under [GPL-3.0-only](LICENSE).
