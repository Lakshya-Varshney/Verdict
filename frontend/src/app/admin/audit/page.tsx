"use client";
import { useRequireAuth } from "@/lib/auth";
import { AuditView } from "@/components/AuditView";
import { LoadingBlock, PageHead } from "@/components/ui";

export default function AdminAudit() {
  const { authed } = useRequireAuth();
  if (!authed) return <LoadingBlock rows={2} />;
  return <><PageHead kicker="Admin · all events" title={<>The <em>ledger.</em></>} sub="Cross-event audit trail. Admins see everything; organisers see only the events they run." /><AuditView /></>;
}
