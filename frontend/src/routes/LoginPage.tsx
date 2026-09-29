import { useState } from "react";
import { useAuth } from "../lib/auth";
import { app, login as t } from "../lib/hebrew";
import { Notice, Spinner } from "../components/ui";

export default function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch {
      setError(t.failed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">
          <h1>{app.title}</h1>
          <p>{app.subtitle}</p>
        </div>
        <form className="login__form" onSubmit={submit}>
          {error && <Notice tone="danger">{error}</Notice>}
          <div className="field">
            <label htmlFor="email">{t.email}</label>
            <input
              id="email"
              className="input input--mono"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">{t.password}</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? <Spinner /> : null}
            {busy ? t.working : t.submit}
          </button>
        </form>
      </div>
    </div>
  );
}
