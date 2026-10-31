#!/usr/bin/env bash
# Copy the dispatcher's Worker secrets from Doppler to Cloudflare without printing values.
#
#   DOPPLER_PROJECT=... DOPPLER_CONFIG=... scripts/sync-secrets.sh
#       Pipes the secrets into `wrangler secret bulk` (creates and deploys a new
#       Worker version immediately, keeping the current code).
#   DOPPLER_PROJECT=... DOPPLER_CONFIG=... scripts/sync-secrets.sh --to-file PATH
#       Writes them to PATH (mode 600) for `wrangler versions upload --secrets-file`.
#       The caller must delete PATH afterwards.
#
# Requires doppler (authenticated, or DOPPLER_TOKEN set), jq, and npm dependencies
# installed in deploy/cloudflare. Only key names are ever printed.
set -euo pipefail

: "${DOPPLER_PROJECT:?Set DOPPLER_PROJECT}"
: "${DOPPLER_CONFIG:?Set DOPPLER_CONFIG}"

keys=(
  DATABASE_URL IFD_CREDENTIAL_KEY IFD_INTERNAL_TOKEN
  AEROAPI_KEY BROWSERBASE_API_KEY BROWSERBASE_SIMBRIEF_CONTEXT_ID SIMBRIEF_USERID
  LANGSMITH_API_KEY LANGSMITH_PROJECT LANGSMITH_TRACING
  R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET
  IFD_PAID_OPERATIONS_ENABLED
)
required='["DATABASE_URL","IFD_CREDENTIAL_KEY","IFD_INTERNAL_TOKEN"]'

out_file=""
case "${1:-}" in
  "") ;;
  --to-file) out_file="${2:?--to-file needs a path}" ;;
  *) echo "usage: $0 [--to-file PATH]" >&2; exit 2 ;;
esac

wanted="$(printf '%s\n' "${keys[@]}" | jq -R . | jq -cs .)"
worker_dir="$(cd "$(dirname "$0")/../deploy/cloudflare" && pwd)"

# Values stay inside this pipeline and the in-memory variable; nothing is echoed.
filtered="$(
  doppler secrets download --no-file --format json \
    --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" \
  | jq -c --argjson wanted "$wanted" \
      'with_entries(select((.key | IN($wanted[])) and (.value | type == "string") and .value != ""))'
)"

missing="$(printf '%s' "$filtered" | jq -r --argjson required "$required" '$required - keys | join(", ")')"
if [[ -n "$missing" ]]; then
  echo "Doppler $DOPPLER_PROJECT/$DOPPLER_CONFIG is missing required secrets: $missing" >&2
  exit 1
fi
if ! printf '%s' "$filtered" | jq -e '(.IFD_PAID_OPERATIONS_ENABLED // "false") | IN("true", "false")' >/dev/null; then
  echo 'IFD_PAID_OPERATIONS_ENABLED must be "true" or "false"' >&2
  exit 1
fi

echo "Syncing secrets: $(printf '%s' "$filtered" | jq -r 'keys | join(", ")')"
if [[ -n "$out_file" ]]; then
  (umask 077 && printf '%s' "$filtered" >"$out_file")
else
  printf '%s' "$filtered" | (cd "$worker_dir" && npx wrangler secret bulk)
fi
