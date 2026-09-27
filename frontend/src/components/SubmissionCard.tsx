import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { Submission } from "@/lib/types";
import { Cover } from "./Cover";
import { safeHref } from "@/lib/utils";

export function SubmissionCard({ s, index = 0, href, preview, badge }: { s: Pick<Submission, "id" | "name" | "tagline" | "team_name" | "track_name" | "tags" | "thumbnail_url"> & Partial<Submission>; index?: number; href?: string; preview?: boolean; badge?: React.ReactNode }) {
  const inner = (
    <>
      <div className="relative aspect-[4/3] overflow-hidden border-b border-line">
        <div className="h-full transition-transform duration-700 group-hover:scale-[1.06]">
          {s.thumbnail_url ? // eslint-disable-next-line @next/next/no-img-element
            <img src={safeHref(s.thumbnail_url)} alt="" className="h-full w-full object-cover" /> : <Cover seed={s.id + (s.name || "untitled")} label={s.name || "Untitled"} rounded={false} />}
        </div>
        {s.track_name && <span className="chip absolute left-3 top-3 bg-bg/80 backdrop-blur">{s.track_name}</span>}
        {s.status === "draft" && <span className="chip chip-signal absolute right-3 top-3 bg-bg/80">draft</span>}
        {!preview && <ArrowUpRight size={18} className="absolute bottom-3 right-3 text-ink3 opacity-0 transition-all group-hover:opacity-100 group-hover:text-amberink" />}
      </div>
      <div className="p-5">
        <div className="flex items-start justify-between gap-3"><h3 className="display text-[2.1rem] leading-[0.95]">{s.name || <span className="text-ink3">Untitled project</span>}</h3>{badge}</div>
        <p className="mt-2 line-clamp-2 min-h-[2.9em] text-[13.5px] text-ink2">{s.tagline || "No tagline yet."}</p>
        <div className="mt-4 flex items-center justify-between gap-3"><span className="label truncate">{s.team_name}</span>
          <span className="flex gap-1.5 overflow-hidden">{s.tags.slice(0, 2).map((t) => <span key={t} className="chip !px-2 !py-0.5 !text-[9px]">{t}</span>)}</span></div>
      </div>
    </>
  );
  const cls = "panel hover-lift fade-up group block overflow-hidden";
  const style = { ["--i" as string]: Math.min(index, 10) } as React.CSSProperties;
  return preview || !href ? <div className={cls} style={style}>{inner}</div> : <Link href={href} className={cls} style={style}>{inner}</Link>;
}
