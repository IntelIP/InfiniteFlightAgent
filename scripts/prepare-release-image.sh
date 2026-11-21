#!/usr/bin/env bash
# Run from deploy/cloudflare on the protected release runner after loading the CI image.
set -euo pipefail
name=infinite-flight-dispatcher-dispatchercontainer-base
tag="$name:$GITHUB_SHA-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
docker tag ifd-ci "$tag"
./node_modules/.bin/wrangler containers push "$tag"
registry="registry.cloudflare.com/$CLOUDFLARE_ACCOUNT_ID/$name"
digest="$(docker inspect "$registry:${tag##*:}" --format '{{json .RepoDigests}}' |
  jq -er --arg prefix "$registry@" '.[] | select(startswith($prefix)) | select(test("@sha256:[0-9a-f]{64}$"))')"
python3 - "$digest" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path("wrangler.toml").read_text())
container, = config["containers"]
container["images"]["base"] = {"image": sys.argv[1]}
Path(".ci-release.json").write_text(json.dumps(config))
PY
mkdir -p "$RUNNER_TEMP/evidence"
printf '%s\n' "$digest" > "$RUNNER_TEMP/evidence/release-image.txt"
awk '/^FROM / {print $2}' ../../Dockerfile > "$RUNNER_TEMP/evidence/build-inputs.txt"
