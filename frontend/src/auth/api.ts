import type { Role } from "./session";
import { onUnauthorized, withAuth } from "./session";

export interface LoginResult {
  access_token: string;
  email: string;
  role: Role;
}

/** Signs in. The server decides the role; the client never infers it. */
export async function login(
  email: string,
  password: string,
): Promise<LoginResult> {
  let response: Response;

  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new Error("Could not reach the server. Is the backend running?");
  }

  if (response.status === 401) {
    throw new Error("Email or password is incorrect.");
  }

  if (response.status === 422) {
    throw new Error("That does not look like a valid email address.");
  }

  if (!response.ok) {
    throw new Error(`Sign-in failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as LoginResult;
}

/**
 * Confirms a stored token is still good, and re-reads the role from the
 * server rather than trusting what localStorage says.
 */
export async function fetchMe(): Promise<{ email: string; role: Role } | null> {
  let response: Response;

  try {
    response = await fetch("/api/auth/me", withAuth());
  } catch {
    // The backend being down is not the same as being signed out; keep the
    // session and let the screen show its own connection error.
    return null;
  }

  if (response.status === 401) {
    onUnauthorized();
    return null;
  }

  if (!response.ok) {
    return null;
  }

  return (await response.json()) as { email: string; role: Role };
}


/**
 * Whether this deployment has a login at all.
 *
 * The public portfolio demo serves the console unauthenticated, so asking
 * for credentials there would be asking for accounts that do not exist.
 * Defaults to requiring auth: if /health cannot be reached, showing the
 * sign-in page is the safer wrong answer.
 */
export async function authRequired(): Promise<boolean> {
  try {
    const response = await fetch("/health");

    if (!response.ok) {
      return true;
    }

    const body = (await response.json()) as { auth_required?: boolean };

    return body.auth_required !== false;
  } catch {
    return true;
  }
}
