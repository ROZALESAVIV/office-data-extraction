import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { app } from "../lib/hebrew";

export default function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  return (
    <div className="app">
      <header className="header">
        <Link to="/cases" className="header__brand">
          {app.title}
          <span>{app.subtitle}</span>
        </Link>
        <div className="header__spacer" />
        <div className="header__user">
          <span>{user?.full_name}</span>
          <button className="btn btn--ghost btn--sm" onClick={signOut}>
            {app.signOut}
          </button>
        </div>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
