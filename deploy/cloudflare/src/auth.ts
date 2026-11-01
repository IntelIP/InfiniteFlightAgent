// Cloudflare Access JWT gate. Access already authenticates at the edge; this
// check makes a missing or misconfigured Access application fail closed.
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";

export interface AccessSettings {
  teamDomain?: string;
  audience?: string;
  allowedEmail?: string;
}

export type VerifyToken = (
  token: string,
  options: { issuer: string; audience: string },
) => Promise<JWTPayload>;

export type AccessResult =
  | { ok: true; identity: string }
  | { ok: false; response: Response };

const jwksByIssuer = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

export const verifyWithAccessCerts: VerifyToken = async (token, { issuer, audience }) => {
  let jwks = jwksByIssuer.get(issuer);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`));
    jwksByIssuer.set(issuer, jwks);
  }
  const { payload } = await jwtVerify(token, jwks, {
    issuer,
    audience,
    algorithms: ["RS256"],
  });
  return payload;
};

/** Returns `https://<team>.cloudflareaccess.com`, or null when unusable. */
export function normalizeTeamDomain(raw: string | undefined): string | null {
  const value = raw?.trim();
  if (!value) return null;
  try {
    const url = new URL(value.includes("://") ? value : `https://${value}`);
    if (url.protocol !== "https:" || url.pathname.replace(/\/+$/, "") !== "") return null;
    return url.origin;
  } catch {
    return null;
  }
}

function deny(status: 401 | 403 | 503, message: string): AccessResult {
  return {
    ok: false,
    response: Response.json({ error: message }, { status, headers: { "cache-control": "no-store" } }),
  };
}

export async function checkAccess(
  request: Request,
  settings: AccessSettings,
  verify: VerifyToken = verifyWithAccessCerts,
): Promise<AccessResult> {
  const issuer = normalizeTeamDomain(settings.teamDomain);
  const audience = settings.audience?.trim();
  if (!issuer || !audience) return deny(503, "Access verification is not configured");

  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return deny(401, "Missing Cloudflare Access token");

  let payload: JWTPayload;
  try {
    payload = await verify(token, { issuer, audience });
  } catch {
    return deny(403, "Invalid Cloudflare Access token");
  }

  const email = typeof payload.email === "string" ? payload.email.toLowerCase() : undefined;
  const allowed = settings.allowedEmail?.trim().toLowerCase();
  if (allowed && email !== allowed) return deny(403, "Identity is not allowed");

  const identity = email ?? (typeof payload.sub === "string" ? payload.sub : "");
  if (!identity) return deny(403, "Access token has no identity");
  return { ok: true, identity };
}
