# VERDICT — frontend

Next.js 16 · React 19 · Tailwind 4 · TanStack Query · TypeScript. "VERDICT" is a placeholder product name (`src/lib/brand.ts`).
Design system: **The Verdict Board** — split-flap departures board × judging panel (dark "Board" + light "Paper" themes, self-hosted fonts, zero third-party requests).

## Run
```bash
npm install
cp .env.example .env.local
npm run dev            # http://localhost:3000  — runs on the built-in mock API (NEXT_PUBLIC_MOCK=true)
```
Demo accounts (password `verdict`): `mira@demo.dev` participant · `judge@demo.dev` judge · `organizer@demo.dev` organizer · `admin@demo.dev` admin.
In mock mode a floating **Role lens** switches accounts; **⌘/Ctrl-K** opens the command palette; scoring is keyboard-first (`1`–`5`).

## Real backend
Set `NEXT_PUBLIC_MOCK=false`. The browser calls `/api/*`; `next.config.mjs` proxies it to `API_INTERNAL_URL` (FastAPI). Then `npm run gen:api` to generate exact types from `/openapi.json`.
Docker: `Dockerfile` builds a standalone image (rewrite target and `NEXT_PUBLIC_*` are baked in at build time — pass them as build args).
See `docs/API-GAPS.md` for every place the UI assumes something about the backend.

## Screens (26 routes)
Public: `/` · `/events` · `/events/[id]` (+`/gallery`) · `/submissions/[sid]` · `/login` · `/signup` · `/embed/[id]`
Participant: `/team` · `/submit` · `/join/[teamId]` · certificate · ballot (`/vote`)
Judge: `/judge` (queue) · `/judge/[sid]` (scoring desk) · `/judge/duel` (pairwise)
Organiser/admin: `/rubric` · `/assign` · `/progress` · `/results` (raw vs normalised proof) · `/audit` · `/settings` · `/data` · `/webhooks` · `/events/new` · `/admin/audit`

## Status — what was and wasn't verified
- ✅ `next build` and `tsc` pass. ~30 views screenshotted in headless Chromium across all five roles (desktop, 390px mobile, both themes); no console errors in those runs.
- ✅ Exercised in mock mode: sign-in, scoring key presses, normalisation, quadratic ballot, role-denial screens.
- ⚠️ Not tested: against the real FastAPI backend, the Docker build, other browsers, accessibility audit. No automated tests yet.
- ⚠️ The mock's normalisation (per-judge z-score, tanh soft-limit) is a UI stand-in; the real maths lives in the backend.
