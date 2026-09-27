"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, getToken, setToken } from "./api";
import type { Me, Role } from "./types";

interface AuthCtx {
  me: Me | null; loading: boolean; authed: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  roleFor: (eventId: string | undefined) => Role;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => { if (!getToken()) return null; try { return await api.auth.me(); } catch (e) { if (e instanceof ApiError && e.status === 401) { setToken(null); return null; } throw e; } },
    staleTime: 60_000, retry: false,
  });
  const me = q.data ?? null;

  // resetQueries drops every cached answer (never leak one user's data to the next) and refetches whatever is on screen, including "me".
  const refresh = useCallback(async () => { await qc.resetQueries(); }, [qc]);
  const login = useCallback(async (email: string, password: string) => { const r = await api.auth.login({ email, password }); setToken(r.token); await refresh(); }, [refresh]);
  const signup = useCallback(async (name: string, email: string, password: string) => { const r = await api.auth.signup({ name, email, password }); setToken(r.token); await refresh(); }, [refresh]);
  const logout = useCallback(async () => { try { await api.auth.logout(); } catch { /* ignore */ } setToken(null); await refresh(); }, [refresh]);

  const roleFor = useCallback((eventId: string | undefined): Role => {
    if (!me) return "visitor";
    if (me.user.is_admin) return "admin";
    const rs = me.roles.filter((r) => r.event_id === eventId).map((r) => r.role);
    if (rs.includes("organizer")) return "organizer";
    if (rs.includes("judge")) return "judge";
    return "participant";
  }, [me]);

  const value = useMemo(() => ({ me, loading: q.isLoading, authed: !!me, login, signup, logout, roleFor }), [me, q.isLoading, login, signup, logout, roleFor]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export function useAuth() { const c = useContext(Ctx); if (!c) throw new Error("useAuth outside AuthProvider"); return c; }

export const isStaff = (r: Role) => r === "organizer" || r === "admin";

/** Redirect helper for pages that need a session. */
export function useRequireAuth() {
  const { authed, loading } = useAuth();
  useEffect(() => {
    if (!loading && !authed) { const next = encodeURIComponent(window.location.pathname + window.location.search); window.location.replace(`/login?next=${next}`); }
  }, [authed, loading]);
  return { authed, loading };
}
