/**
 * Cognito Hosted UI login with Authorization Code + PKCE (no client secret, no SDK).
 *
 * Enabled when VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID are set at build
 * time (terraform outputs cognito_domain / cognito_client_id). Without them the
 * app runs in local-dev mode with no login.
 */

const DOMAIN = (import.meta.env.VITE_COGNITO_DOMAIN || '').replace(/\/$/, '');
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || '';
const TOKENS_KEY = 'pc-auth-tokens';
const PKCE_KEY = 'pc-auth-pkce';

export const authEnabled = Boolean(DOMAIN && CLIENT_ID);

function redirectUri() {
  return `${window.location.origin}/auth/callback`;
}

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function base64url(bytes) {
  let s = '';
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomString(len = 64) {
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

export function decodeJwt(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload));
  } catch {
    return {};
  }
}

function readTokens() {
  try {
    return JSON.parse(storage()?.getItem(TOKENS_KEY) || 'null');
  } catch {
    return null;
  }
}

export function getAccessToken() {
  const t = readTokens();
  if (!t || Date.now() >= t.expiresAt - 30_000) return null;
  return t.accessToken;
}

export function getUser() {
  const t = readTokens();
  if (!t) return null;
  const claims = decodeJwt(t.idToken);
  return { email: claims.email, groups: claims['cognito:groups'] || [] };
}

export function isAdmin() {
  if (!authEnabled) return true; // local dev
  return (getUser()?.groups || []).includes('admins');
}

export async function login(returnTo = window.location.pathname) {
  const verifier = randomString();
  const state = randomString(24);
  storage()?.setItem(PKCE_KEY, JSON.stringify({ verifier, state, returnTo }));
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    redirect_uri: redirectUri(),
    scope: 'openid email profile',
    code_challenge_method: 'S256',
    code_challenge: await challengeFor(verifier),
    state,
  });
  window.location.assign(`${DOMAIN}/oauth2/authorize?${params}`);
}

/** Exchange ?code= for tokens. Returns the path to navigate back to. */
export async function handleCallback(search = window.location.search) {
  const q = new URLSearchParams(search);
  const saved = JSON.parse(storage()?.getItem(PKCE_KEY) || 'null');
  storage()?.removeItem(PKCE_KEY);
  if (q.get('error')) throw new Error(q.get('error_description') || q.get('error'));
  if (!saved || q.get('state') !== saved.state) throw new Error('Login state mismatch, please try again.');

  const res = await fetch(`${DOMAIN}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CLIENT_ID,
      code: q.get('code') || '',
      redirect_uri: redirectUri(),
      code_verifier: saved.verifier,
    }),
  });
  if (!res.ok) throw new Error(`Token exchange failed (${res.status})`);
  const body = await res.json();
  storage()?.setItem(TOKENS_KEY, JSON.stringify({
    accessToken: body.access_token,
    idToken: body.id_token,
    expiresAt: Date.now() + body.expires_in * 1000,
  }));
  return saved.returnTo || '/';
}

export function logout() {
  storage()?.removeItem(TOKENS_KEY);
  if (!authEnabled) return;
  const params = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: `${window.location.origin}/` });
  window.location.assign(`${DOMAIN}/logout?${params}`);
}
