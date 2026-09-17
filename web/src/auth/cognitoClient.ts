import type { CognitoConfig } from "./cognitoConfig";
import type { StoredTokens } from "./tokens";

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

interface TokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
}

export class CognitoAuthError extends Error {
  constructor(
    message: string,
    readonly cause_?: unknown,
  ) {
    super(message);
    this.name = "CognitoAuthError";
  }
}

function tokenEndpoint(config: CognitoConfig): string {
  return `https://${config.domain}/oauth2/token`;
}

async function toTokens(response: Response, now: () => number): Promise<StoredTokens> {
  if (!response.ok) {
    throw new CognitoAuthError(`Cognito token endpoint returned ${response.status}.`);
  }
  const body = (await response.json()) as TokenResponse;
  return {
    accessToken: body.access_token,
    idToken: body.id_token,
    refreshToken: body.refresh_token ?? null,
    expiresAt: now() + body.expires_in * 1000,
  };
}

export async function exchangeAuthorizationCode(
  config: CognitoConfig,
  code: string,
  codeVerifier: string,
  fetchImpl: FetchLike = fetch,
  now: () => number = Date.now,
): Promise<StoredTokens> {
  const response = await fetchImpl(tokenEndpoint(config), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      code,
      redirect_uri: config.redirectUri,
      code_verifier: codeVerifier,
    }).toString(),
  });
  return toTokens(response, now);
}

export async function refreshTokens(
  config: CognitoConfig,
  refreshToken: string,
  fetchImpl: FetchLike = fetch,
  now: () => number = Date.now,
): Promise<StoredTokens> {
  const response = await fetchImpl(tokenEndpoint(config), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: config.clientId,
      refresh_token: refreshToken,
    }).toString(),
  });
  const tokens = await toTokens(response, now);
  // A refresh response may omit refresh_token when rotation is off; keep the old one.
  return tokens.refreshToken === null ? { ...tokens, refreshToken } : tokens;
}

export function buildAuthorizeUrl(
  config: CognitoConfig,
  params: { codeChallenge: string; state: string },
): string {
  const url = new URL(`https://${config.domain}/oauth2/authorize`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", config.scopes.join(" "));
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("state", params.state);
  return url.toString();
}

export function buildLogoutUrl(config: CognitoConfig): string {
  const url = new URL(`https://${config.domain}/logout`);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("logout_uri", config.logoutUri);
  return url.toString();
}
