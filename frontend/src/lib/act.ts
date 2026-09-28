"use client";
import { useCallback } from "react";
import { ApiError } from "./api";
import { useToast } from "@/components/toast";

/** Run an API call; toast success/failure; never throws. Returns undefined on failure. */
export function useAct() {
  const toast = useToast();
  return useCallback(async <T,>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> => {
    try { const r = await fn(); if (okMsg) toast(okMsg, "ok"); return r; }
    catch (e) {
      if (e instanceof ApiError) toast(e.status === 401 ? "Sign in first — " + e.detail : e.detail, "error");
      else toast("Unexpected error — check the console.", "error");
      return undefined;
    }
  }, [toast]);
}
