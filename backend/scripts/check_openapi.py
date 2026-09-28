"""OpenAPI completeness checker.

    python backend/scripts/check_openapi.py [base_url]        (default http://localhost:8000)

Checks the *served* /openapi.json (so it tests what a consumer sees), then cross-checks the spec
against every endpoint the frontend calls (frontend/src/lib/api.ts) so "the API covers every UI
action" is a measured claim. Exit code 1 on any failure. Uses only the standard library.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[2]
API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"

# UI calls that the backend does not implement (yet). Shrink this list as T4 items land; anything the UI
# calls that is neither in the spec nor listed here fails the check.
# T4 endpoints that are planned but not built yet: reported as "pending", not failures. Delete an entry
# when it ships (the stale-entry check below enforces that).
PENDING_T4: set[tuple[str, str]] = set()  # every planned T4 endpoint now exists
MOCK_ONLY = ("/__mock",)  # frontend mock-server helpers, not part of the API

KNOWN_UNIMPLEMENTED: set[tuple[str, str]] = {
    ("GET", "/events/{}/judging/pairwise/next"),      # bonus: pairwise (Bradley-Terry) judging
    ("POST", "/events/{}/judging/pairwise/vote"),
    ("GET", "/events/{}/judging/pairwise/ranking"),
}

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print("FAIL", msg)


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


spec = get(BASE + "/openapi.json")
paths: dict = spec["paths"]
ops = [(m.upper(), p, o) for p, ms in paths.items() for m, o in ms.items()]
schemas = spec.get("components", {}).get("schemas", {})

# ------------------------------------------------------------------ structure
if not str(spec.get("openapi", "")).startswith("3."):
    fail(f"not an OpenAPI 3 document: {spec.get('openapi')}")
info = spec.get("info", {})
for key in ("title", "version", "description", "license", "contact"):
    if not info.get(key):
        fail(f"info.{key} missing")
if not spec.get("servers"):
    fail("servers missing")
if "BearerAuth" not in spec.get("components", {}).get("securitySchemes", {}):
    fail("securitySchemes.BearerAuth missing")
if "ErrorOut" not in schemas:
    fail("ErrorOut schema missing")
declared_tags = {t["name"] for t in spec.get("tags", [])}
ids: list[str] = []


def bare_object(schema: dict | None) -> bool:
    if schema is None:
        return False
    if not schema:
        return True  # `{}` = "anything"
    it = schema.get("items", schema) if schema.get("type") == "array" else schema
    return it.get("type") == "object" and not it.get("properties") and "$ref" not in it


for method, path, op in ops:
    where = f"{method} {path}"
    ids.append(op.get("operationId", ""))
    if not op.get("summary") or op["summary"].lower() == op["summary"].title().lower() and "_" in op["summary"]:
        fail(f"{where}: missing/auto summary")
    if not op.get("description"):
        fail(f"{where}: missing description")
    if not op.get("tags") or not set(op["tags"]) <= declared_tags:
        fail(f"{where}: tag missing or undeclared: {op.get('tags')}")
    ok_codes = [c for c in op["responses"] if c.startswith("2")]
    if not ok_codes:
        fail(f"{where}: no 2xx response documented")
    for c in ok_codes:
        for ctype, body in op["responses"][c].get("content", {}).items():
            if ctype == "application/json" and bare_object(body.get("schema")):
                fail(f"{where}: {c} response is an untyped object")
    sec = op.get("security")
    if sec and any(sec) and not any(any(s) for s in sec):
        fail(f"{where}: bad security requirement")
    if sec and "401" not in op["responses"] and sec == [{"BearerAuth": []}]:
        fail(f"{where}: requires auth but 401 not documented")
    for code, resp in op["responses"].items():
        if code.startswith(("4", "5")) and code != "422":
            ref = json.dumps(resp)
            if "ErrorOut" not in ref:
                fail(f"{where}: {code} does not reference ErrorOut")
    for prm in op.get("parameters", []):
        if not prm.get("description"):
            fail(f"{where}: parameter {prm['name']} has no description")
    if op.get("requestBody"):
        schema = op["requestBody"]["content"].get("application/json", {}).get("schema", {})
        ref = (schema.get("$ref") or next((a["$ref"] for a in schema.get("anyOf", []) if "$ref" in a), "")).split("/")[-1]
        if ref and "example" not in schemas.get(ref, {}) and not schemas.get(ref, {}).get("examples"):
            fail(f"{where}: request schema {ref} has no example")

dupes = {i for i in ids if ids.count(i) > 1 or not i}
if dupes:
    fail(f"operationIds not unique/present: {sorted(dupes)}")

# ------------------------------------------------------------------ every UI call exists
def norm(p: str) -> str:
    p = re.sub(r"\$\{[^}]*[?&][^}]*\}", "", p)  # `${cond ? "?x=1" : ""}` is a query-string suffix, not a path segment
    return re.sub(r"\{[^}]*\}|\$\{[^}]*\}", "{}", p).split("?")[0]


spec_ops = {(m, norm(p)) for m, p, _ in ops}
ts = API_TS.read_text(encoding="utf-8")
calls: set[tuple[str, str]] = set()
for fn, method in (("g", "GET"), ("post", "POST"), ("patch", "PATCH"), ("del", "DELETE"), ("put", "PUT")):
    # a backtick template runs to the closing backtick (it may contain quotes inside `${...}`)
    for m in re.finditer(r"\b" + fn + r"(?:<[^()]*?>)?\(\s*(?:`(/[^`]*)`|\"(/[^\"]*)\")", ts):
        calls.add((method, norm(m.group(1) or m.group(2))))
for m in re.finditer(r"request<[^>]*>\(\s*\"(GET|POST|PATCH|DELETE|PUT)\"\s*,\s*[`\"](/[^`\"]*)[`\"]", ts):
    calls.add((m.group(1), norm(m.group(2))))

calls = {c for c in calls if not c[1].startswith(MOCK_ONLY)}
missing = sorted(c for c in calls if c not in spec_ops and c not in KNOWN_UNIMPLEMENTED and c not in PENDING_T4)
stale = sorted(c for c in KNOWN_UNIMPLEMENTED | PENDING_T4 if c in spec_ops)
for m, p in missing:
    fail(f"frontend calls {m} {p} but the API spec has no such operation")
for m, p in stale:
    fail(f"{m} {p} is implemented now: remove it from KNOWN_UNIMPLEMENTED")

typed = sum(1 for _, _, o in ops if not any(
    bare_object(b.get("schema")) for c, r in o["responses"].items() if c.startswith("2")
    for t, b in r.get("content", {}).items() if t == "application/json"))
print(f"\noperations: {len(ops)} | typed 2xx responses: {typed}/{len(ops)} | schemas: {len(schemas)}")
print(f"frontend endpoints: {len(calls)} | covered by spec: {len([c for c in calls if c in spec_ops])} | "
      f"bonus-unimplemented: {len([c for c in calls if c in KNOWN_UNIMPLEMENTED])} | pending T4: {len(PENDING_T4 - spec_ops)}")
for m, p in sorted(PENDING_T4 - spec_ops):
    print(f"  pending T4: {m} {p}")
print(f"\nRESULT: {'FAILED, ' + str(len(failures)) + ' problem(s)' if failures else 'OK'}")
sys.exit(1 if failures else 0)
