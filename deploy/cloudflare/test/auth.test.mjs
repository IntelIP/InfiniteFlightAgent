// Auth gate unit tests (Node's built-in runner; token verification is injected).
import assert from "node:assert/strict";
import { test } from "node:test";
import { checkAccess, normalizeTeamDomain } from "../src/auth.ts";

const settings = { teamDomain: "team.cloudflareaccess.com", audience: "aud-123", allowedEmail: "" };

function request(token) {
  const headers = token ? { "cf-access-jwt-assertion": token } : {};
  return new Request("https://worker.example/mcp", { headers });
}

const accept = (payload) => async () => payload;
const reject = async () => {
  throw new Error("bad signature");
};

test("fails closed when Access settings are missing", async () => {
  for (const partial of [{}, { teamDomain: "team.cloudflareaccess.com" }, { audience: "aud-123" }]) {
    const result = await checkAccess(request("t"), partial, accept({ email: "a@b.c" }));
    assert.equal(result.ok, false);
    assert.equal(result.response.status, 503);
  }
});

test("rejects a request without the Access header", async () => {
  const result = await checkAccess(request(), settings, accept({ email: "a@b.c" }));
  assert.equal(result.response.status, 401);
});

test("rejects a token that fails verification", async () => {
  const result = await checkAccess(request("t"), settings, reject);
  assert.equal(result.response.status, 403);
});

test("verifies against the team issuer and configured audience", async () => {
  let seen;
  const result = await checkAccess(request("tok"), settings, async (token, options) => {
    seen = { token, ...options };
    return { email: "Owner@Example.com" };
  });
  assert.deepEqual(seen, { token: "tok", issuer: "https://team.cloudflareaccess.com", audience: "aud-123" });
  assert.deepEqual(result, { ok: true, identity: "owner@example.com" });
});

test("enforces the optional allowed email", async () => {
  const strict = { ...settings, allowedEmail: "owner@example.com" };
  assert.equal((await checkAccess(request("t"), strict, accept({ email: "other@example.com" }))).response.status, 403);
  assert.equal((await checkAccess(request("t"), strict, accept({ sub: "abc" }))).response.status, 403);
  assert.equal((await checkAccess(request("t"), strict, accept({ email: "OWNER@example.com" }))).ok, true);
});

test("normalizes team domains and rejects unusable values", () => {
  assert.equal(normalizeTeamDomain("https://team.cloudflareaccess.com/"), "https://team.cloudflareaccess.com");
  assert.equal(normalizeTeamDomain("team.cloudflareaccess.com"), "https://team.cloudflareaccess.com");
  assert.equal(normalizeTeamDomain("http://team.cloudflareaccess.com"), null);
  assert.equal(normalizeTeamDomain("https://team.cloudflareaccess.com/path"), null);
  assert.equal(normalizeTeamDomain(""), null);
});
