/**
 * Cognito hosted-UI configuration, resolved from Vite env vars so the same
 * build works across environments (WP-01 deploys the actual user pool/client;
 * this module only reads what it's given). See `web/.env.example`.
 */
export interface CognitoConfig {
  domain: string;
  clientId: string;
  redirectUri: string;
  logoutUri: string;
  scopes: readonly string[];
}

export class MissingCognitoConfigError extends Error {
  constructor(missing: readonly string[]) {
    super(`Missing Cognito configuration: ${missing.join(", ")}. See web/.env.example.`);
    this.name = "MissingCognitoConfigError";
  }
}

export function loadCognitoConfig(env: Record<string, string | undefined> = import.meta.env): CognitoConfig {
  const domain = env["VITE_COGNITO_DOMAIN"];
  const clientId = env["VITE_COGNITO_CLIENT_ID"];
  const redirectUri = env["VITE_COGNITO_REDIRECT_URI"];
  const logoutUri = env["VITE_COGNITO_LOGOUT_URI"];
  const missing = [
    domain === undefined ? "VITE_COGNITO_DOMAIN" : null,
    clientId === undefined ? "VITE_COGNITO_CLIENT_ID" : null,
    redirectUri === undefined ? "VITE_COGNITO_REDIRECT_URI" : null,
    logoutUri === undefined ? "VITE_COGNITO_LOGOUT_URI" : null,
  ].filter((value): value is string => value !== null);
  if (missing.length > 0) {
    throw new MissingCognitoConfigError(missing);
  }
  const scopesRaw = env["VITE_COGNITO_SCOPES"] ?? "openid email";
  return {
    domain: domain as string,
    clientId: clientId as string,
    redirectUri: redirectUri as string,
    logoutUri: logoutUri as string,
    scopes: scopesRaw.split(/\s+/).filter((s) => s.length > 0),
  };
}
