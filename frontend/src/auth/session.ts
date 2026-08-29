/**
 * The signed-in session, as the browser holds it.
 *
 * localStorage rather than a cookie: the API is a separate origin in every
 * deployment, and the token has to be attached as a header anyway. It
 * survives a reload, which is the whole point — a dashboard that logs you
 * out on refresh is unusable.
 *
 * The token is not decoded here to find the role. The server puts the role
 * in the login response and /api/auth/me confirms it, so nothing in the UI
 * has to trust a value it parsed out of a token itself.
 */

const TOKEN_KEY = "fintel.token";
const USER_KEY = "fintel.user";

export type Role = "admin" | "analyst";

export interface SessionUser {
  email: string;
  role: Role;
}

/** Reads survive a browser that blocks site data; they return null instead. */
export function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function readUser(): SessionUser | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY);

    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as SessionUser;

    // A hand-edited or half-written entry must not become a logged-in
    // session with an undefined role.
    if (parsed?.email && (parsed.role === "admin" || parsed.role === "analyst")) {
      return parsed;
    }

    return null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: SessionUser): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // A private window still gets a working session for this tab; it just
    // will not survive a reload.
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Adds the bearer header to a fetch init, leaving the rest untouched. */
export function withAuth(init: RequestInit = {}): RequestInit {
  const token = readToken();

  if (!token) {
    return init;
  }

  return {
    ...init,
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      Authorization: `Bearer ${token}`,
    },
  };
}

/**
 * Called when the API rejects the token.
 *
 * Clearing and reloading is deliberate: every screen reads the session on
 * mount, so a reload is what puts the reader back at the sign-in page
 * without threading an "expired" flag through unrelated components.
 */
export function onUnauthorized(): void {
  clearSession();
  window.location.reload();
}
