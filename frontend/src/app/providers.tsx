"use client";
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/toast";

export function Providers({ children }: { children: ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: (n, e) => !(e instanceof ApiError) && n < 1 } },
  }));
  return <QueryClientProvider client={qc}><ToastProvider><AuthProvider>{children}</AuthProvider></ToastProvider></QueryClientProvider>;
}
