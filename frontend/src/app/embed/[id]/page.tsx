"use client";
import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Cover } from "@/components/Cover";
import { ErrorState, LoadingBlock } from "@/components/ui";
import { BRAND } from "@/lib/brand";

export default function Embed() {
  const { id } = useParams<{ id: string }>();
  useEffect(() => { const t = new URLSearchParams(location.search).get("theme"); if (t === "paper") document.documentElement.dataset.theme = "paper"; }, []);
  const q = useQuery({ queryKey: ["embed", id], queryFn: () => api.data.embed(id) });
  return (
    <div className="relative z-10 min-h-screen p-5">
      {q.isLoading ? <LoadingBlock /> : q.error || !q.data ? <ErrorState error={q.error} /> : (
        <>
          <div className="mb-5 flex items-baseline justify-between"><h1 className="display text-4xl">{q.data.event.name} <em>gallery</em></h1><span className="label">{q.data.items.length} projects</span></div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {q.data.items.map((s) => (
              <a key={s.id} href={`/submissions/${s.id}`} target="_blank" rel="noopener noreferrer" className="panel hover-lift group block overflow-hidden">
                <div className="aspect-[16/10] border-b border-line"><Cover seed={s.id + s.name} label={s.name} rounded={false} /></div>
                <div className="p-4"><div className="display text-2xl leading-none">{s.name}</div><div className="mt-1 line-clamp-1 text-[12.5px] text-ink2">{s.tagline}</div></div>
              </a>
            ))}
          </div>
          <div className="label mt-6 text-center">Powered by {BRAND.name}</div>
        </>
      )}
    </div>
  );
}
