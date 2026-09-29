/** Session state. Small enough not to need a library. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import * as api from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // A token in storage is not proof of a live session: it may have expired
    // while the tab was closed. Ask the server before showing anything.
    if (!api.getToken()) {
      setReady(true);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => api.setToken(null))
      .finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    setUser(await api.me());
  }, []);

  const signOut = useCallback(() => {
    api.setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, signIn, signOut }), [user, ready, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

/** Only owner and lawyer may decide a value is correct. Staff may read and
 *  upload — that split is a product rule, not a UI convenience. */
export function canDecide(user: User | null): boolean {
  return user?.role === "owner" || user?.role === "lawyer";
}
