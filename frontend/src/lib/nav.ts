import type { EventStatus, Role } from "./types";

export interface Tab { key: string; href: string; label: string; exact?: boolean; }

export function eventTabs(id: string, role: Role, status: EventStatus): Tab[] {
  const b = `/events/${id}`;
  const staff = role === "organizer" || role === "admin";
  const t: Tab[] = [{ key: "overview", href: b, label: "Overview", exact: true }, { key: "gallery", href: `${b}/gallery`, label: "Gallery" }];
  if (role === "visitor" || role === "participant") { t.push({ key: "team", href: `${b}/team`, label: "My team" }, { key: "submit", href: `${b}/submit`, label: "Submission" }); }
  if (role === "judge") t.push({ key: "judge", href: `${b}/judge`, label: "Judge desk" }, { key: "duel", href: `${b}/judge/duel`, label: "Duel mode" });
  if (status === "voting" || staff) t.push({ key: "vote", href: `${b}/vote`, label: "Ballot" });
  if (status === "published" || staff) t.push({ key: "results", href: `${b}/results`, label: "Results" });
  if (staff) t.push(
    { key: "rubric", href: `${b}/rubric`, label: "Rubric" }, { key: "assign", href: `${b}/assign`, label: "Assign" },
    { key: "progress", href: `${b}/progress`, label: "Progress" }, { key: "audit", href: `${b}/audit`, label: "Audit" },
    { key: "settings", href: `${b}/settings`, label: "Settings" }, { key: "data", href: `${b}/data`, label: "Data" }, { key: "hooks", href: `${b}/webhooks`, label: "Webhooks" },
  );
  return t;
}

/** The full permission matrix from the brief (Fig. 02) — single source of truth for UI copy. */
export const MATRIX: { action: string; visitor: boolean | string; participant: boolean | string; judge: boolean | string; organizer: boolean | string; admin: boolean | string }[] = [
  { action: "View public gallery (submitted only)", visitor: true, participant: true, judge: true, organizer: true, admin: true },
  { action: "Create / edit own team's submission", visitor: false, participant: "own team", judge: false, organizer: true, admin: true },
  { action: "View assigned submissions & own scores", visitor: false, participant: false, judge: "own only", organizer: true, admin: true },
  { action: "View another judge's scores", visitor: false, participant: false, judge: false, organizer: true, admin: true },
  { action: "View aggregate / normalised results before publish", visitor: false, participant: false, judge: false, organizer: true, admin: true },
  { action: "Configure rubric, assign judges", visitor: false, participant: false, judge: false, organizer: true, admin: true },
  { action: "View audit log", visitor: false, participant: false, judge: false, organizer: "own event", admin: true },
  { action: "Vote (during voting window)", visitor: "per event", participant: true, judge: true, organizer: true, admin: true },
];
