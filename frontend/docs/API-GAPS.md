# API gaps & assumptions (frontend ↔ FastAPI)

The UI was built against a **mock API** (`src/lib/mock/`) that mirrors the contract as I understood it. Everything below is where
the UI *guesses*. Confirm each item against the backend's real `/openapi.json`, then run `npm run gen:api` and align `src/lib/types.ts`.

## 1. Endpoints the UI calls that are NOT in the contract (marked `// ASSUMED` in `src/lib/api.ts`)
| Endpoint | Used by | Why |
|---|---|---|
| `DELETE /events/{id}/rubric/criteria/{cid}` | Rubric | remove a criterion |
| `GET /events/{id}/judging/assignments` | Assign | organiser view of all assignments |
| `GET /events/{id}/judging/pairwise/next` · `POST …/pairwise/vote` · `GET …/pairwise/ranking` | Duel mode (bonus) | pairwise judging |
| `GET /webhooks` · `DELETE /webhooks/{id}` | Webhooks | list / remove subscriptions |

## 2. Endpoints/shapes I could not verify against the contract text — please check paths and bodies
- Judge queue: `GET /events/{id}/judging/assignments/mine`
- Role list: `GET /events/{id}/roles`; invite body `{ email, role }`
- Team lookup for invite links: `GET /teams/{id}` (invite link format is `/join/{team_id}?code={invite_code}`)
- Comments / vote / count paths: `/submissions/{id}/comments`, `/submissions/{id}/vote`, `/submissions/{id}/votes/count`
- Organiser draft listing: `GET /events/{id}/submissions?include_drafts=1`
- Publishing results = `PATCH /events/{id}` with `{ status: "published" }`
- Certificate: `GET /events/{id}/certificates/{user_id}`
- All response field names (see `src/lib/types.ts`), and `Page<T>` = `{ items, total, page, limit }`

## 3. Event status enum (assumed)
`draft | open | judging | voting | published | archived` — defined once in `src/lib/types.ts` (`EVENT_STATUSES`).

## 4. Behaviour the UI relies on the API to enforce (the UI only hides things)
- 401 → sign-in prompt; 403 → "denied at the API" screen (never a crash).
- PATCH/submit after the deadline → 403 (UI shows a countdown but the server is the authority).
- Results endpoint → 403 until published (non-organisers); no per-judge scores in the public payload.
- Vote count endpoint → `{ hidden: true, count: null }` for non-organisers while status is `voting`.
- Scoring only while status is `judging`, only for assigned judges.

## 5. Not built
- Image upload: submissions use URLs only; cover art is generated client-side from the project name.
