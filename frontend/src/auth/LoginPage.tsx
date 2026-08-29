import { useState } from "react";
import { Eye, EyeOff, LoaderCircle } from "lucide-react";
import { Logo } from "../components/Logo";
import { login } from "./api";
import { saveSession } from "./session";
import "./LoginPage.css";

/**
 * The gate in front of both surfaces.
 *
 * No registration and no password reset: accounts are made by an operator
 * running scripts/create_user.py, so the footer points at a person rather
 * than at a flow that does not exist. A "Sign in with Google" button is
 * absent for the same reason — there is no OAuth backend behind it.
 */
export function LoginPage({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    setBusy(true);
    setError(null);

    try {
      const result = await login(email, password);

      saveSession(result.access_token, {
        email: result.email,
        role: result.role,
      });

      onSignedIn();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not sign in. Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__panel">
        <header className="login__brand">
          <Logo size={44} title="FinIntel" />
          <div>
            <h1 className="login__wordmark">FinIntel</h1>
            <p className="login__tagline">AI Financial Intelligence Platform</p>
          </div>
        </header>

        <form className="login__card" onSubmit={handleSubmit} noValidate>
          <h2 className="login__title">Sign in</h2>
          <p className="login__lede">
            Welcome back. Please sign in to your account.
          </p>

          <label className="login__field">
            <span className="login__label">Email address</span>
            <input
              className="login__input"
              type="email"
              name="email"
              autoComplete="username"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoFocus
            />
          </label>

          <label className="login__field">
            <span className="login__label">Password</span>
            <span className="login__password">
              <input
                className="login__input"
                type={revealed ? "text" : "password"}
                name="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                type="button"
                className="login__reveal"
                onClick={() => setRevealed((shown) => !shown)}
                aria-label={revealed ? "Hide password" : "Show password"}
              >
                {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </span>
          </label>

          {error && (
            <p className="login__error" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            className="login__submit"
            disabled={busy || !email || !password}
          >
            {busy && <LoaderCircle size={15} className="login__spin" />}
            {busy ? "Signing in…" : "Sign in"}
          </button>

          <p className="login__footnote">
            Accounts are created by your administrator.
          </p>
        </form>

        <ul className="login__roles">
          <li>
            <span className="login__role-name">Admin</span>
            Everything an analyst can do, plus providers, indexing, and the
            evaluation dashboard.
          </li>
          <li>
            <span className="login__role-name">Analyst</span>
            Ask questions and read evidence-backed answers.
          </li>
        </ul>
      </div>
    </div>
  );
}
