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

## Screens (27 routes)
Public: `/` · `/events` · `/events/[id]` (+`/gallery`) · `/submissions/[sid]` · `/login` · `/signup` · `/embed/[id]` · `/verify/[code]`
Participant: `/team` · `/submit` · `/join/[teamId]` · certificate · ballot (`/vote`)
Judge: `/judge` (queue) · `/judge/[sid]` (scoring desk) · `/judge/duel` (pairwise, not built: `501`)
Organiser/admin: `/rubric` · `/assign` · `/progress` · `/results` (raw vs normalised proof) · `/audit` · `/settings` · `/data` · `/webhooks` · `/events/new` · `/admin/audit`

## Status — what was and wasn't verified
This file predates the backend integration; that work is done and is documented at the repo root, not here. Current status:
- ✅ `next build` and `tsc` pass; the Docker image builds and boots against the real FastAPI backend (`docker compose up -d --build`).
- ✅ Automated tests exist and pass against the real backend: `frontend/e2e-ui.py` (27 pages × 5 roles, real browser), `frontend/e2e-ui-flows.py` (13 interactive flows), `frontend/e2e-embed.py` (cross-origin embed). See root `README.md` → Testing and verification.
- ✅ Exercised in mock mode too: sign-in, scoring key presses, normalisation, quadratic ballot, role-denial screens.
- ⚠️ Not tested: other browsers besides Chromium, a formal accessibility audit.
- ⚠️ The mock's normalisation (per-judge z-score, tanh soft-limit) is a UI stand-in; the real maths lives in the backend (see `JUDGING.md`).
