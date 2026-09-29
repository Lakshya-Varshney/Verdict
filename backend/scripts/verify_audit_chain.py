#!/usr/bin/env python3
"""Verify the platform's audit log hash chain.

    python verify_audit_chain.py [base_url]                 (default http://localhost:8000; logs
                                                               in as the demo organizer)
    python verify_audit_chain.py --token <bearer> [base_url] (use your own organizer/admin token)

Calls `GET /admin/audit/verify`, which recomputes every row's hash from its own stored fields in
insertion order (see `app/services/audit_service.verify_chain`). Unlike `verify_certificate.py`,
this does not reimplement the check from scratch: a certificate is handed to a third party with
no API access at all, so it has to carry its own proof; the audit log never leaves the system,
and anyone who can call this already has the credentials to just ask the server. Exit status:
0 = chain intact, 1 = tampering detected, 2 = usage / request error.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8000"


def _call(method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw else raw)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("base_url", nargs="?", default=DEFAULT_BASE)
    p.add_argument("--token", help="organizer/admin bearer token (default: log in as the demo organizer)")
    p.add_argument("--email", default="organizer@dogfoodhack.com")
    p.add_argument("--password", default="organizer123")
    args = p.parse_args()
    base = args.base_url.rstrip("/")

    token = args.token
    if not token:
        status, body = _call("POST", f"{base}/auth/login", body={"email": args.email, "password": args.password})
        if status != 200:
            print(f"could not log in as {args.email}: {status} {body}", file=sys.stderr)
            return 2
        token = body["token"]

    status, result = _call("GET", f"{base}/admin/audit/verify", token=token)
    if status != 200:
        print(f"GET /admin/audit/verify -> {status}: {result}", file=sys.stderr)
        return 2

    if result["valid"]:
        head = f"head seq={result['head_seq']} hash={result['head_hash'][:16]}..." if result["checked"] else "(empty log)"
        print(f"OK: {result['checked']} row(s) verified, chain intact. {head}")
        return 0

    broken = result["broken"]
    print(f"TAMPERING DETECTED after {result['checked']} verified row(s):")
    print(f"  first broken row: seq={broken['seq']} id={broken['id']}")
    print(f"  reason: {broken['reason']}")
    print("  (the row's own content is not shown here - only that it, or the one before it, was altered)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
