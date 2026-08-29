import { useEffect, useState } from "react";
import App from "./App";
import EvaluationApp from "./evaluation/EvaluationApp";
import { LoginPage } from "./auth/LoginPage";
import { fetchMe } from "./auth/api";
import { readToken, readUser, type SessionUser } from "./auth/session";
import { useHashRoute } from "./lib/router";

/**
 * Screen switcher, behind the sign-in gate.
 *
 * Two independent surfaces share the bundle: the research console (light,
 * document-like, one question at a time) and the evaluation dashboard (dark,
 * dense, many runs at once). They share no state and no chrome — only the
 * link that moves between them — so the split lives here rather than in a
 * shared layout that neither screen would fit comfortably.
 *
 * The gate is a convenience, not the control. Every route the two surfaces
 * call is guarded server-side by require_role; hiding a screen here only
 * saves the reader from a wall of 401s.
 */
export default function Root() {
  const [path] = useHashRoute();
  const [user, setUser] = useState<SessionUser | null>(() => readUser());

  // A stored token can be expired or revoked. Ask the server whose it is
  // rather than trusting what localStorage claims about the role.
  const [checked, setChecked] = useState(() => readToken() === null);

  useEffect(() => {
    if (checked) {
      return;
    }

    let cancelled = false;

    fetchMe()
      .then((confirmed) => {
        if (cancelled) {
          return;
        }

        if (confirmed) {
          setUser(confirmed);
        }

        setChecked(true);
      })
      .catch(() => {
        if (!cancelled) {
          setChecked(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [checked]);

  if (!checked) {
    // Nothing rendered rather than a flash of the sign-in page for someone
    // who is already signed in.
    return null;
  }

  if (!user) {
    return <LoginPage onSignedIn={() => setUser(readUser())} />;
  }

  // The dashboard is an admin surface: every route behind it now requires
  // the admin role, so an analyst who types the URL would get a screen of
  // 401s. Send them to the console they can actually use.
  if (path.startsWith("/evaluation") && user.role === "admin") {
    return <EvaluationApp user={user} />;
  }

  return <App user={user} />;
}
