"use client";
import { Gate, useEventCtx } from "@/components/EventContext";
import { AuditView } from "@/components/AuditView";
import { PageHead } from "@/components/ui";

export default function EventAudit() {
  const { event: e } = useEventCtx();
  return <Gate allow={["organizer"]} what="The audit log is an organiser tool."><PageHead kicker="Accountability" title={<>Everything, <em>as a sentence.</em></>} sub={`Every mutation and every denied attempt for ${e.name}, in plain language. Denials are highlighted — they're the interesting part.`} /><AuditView eventId={e.id} /></Gate>;
}
