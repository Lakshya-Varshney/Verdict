"use client";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { NeedAuth } from "./NeedAuth";
import { Denied } from "./ui";

/** UI-level convenience gate. The real enforcement is the API — this just avoids showing dead ends. */
export function Gate({ allow, children, what }: { allow: Role[]; children: React.ReactNode; what?: string }) {
  const { id } = useParams<{ id: string }>(); const { roleFor, authed, loading } = useAuth(); const role = roleFor(id);
  return (
    <NeedAuth what={what ?? "continue"}>
      {loading ? null : role === "admin" || allow.includes(role) ? <>{children}</> : <Denied need={allow.filter((r) => r !== "admin").join(" / ")} what={`You're signed in as ${role} for this event.`} />}
      {authed ? null : null}
    </NeedAuth>
  );
}
