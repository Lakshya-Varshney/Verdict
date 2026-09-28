#!/usr/bin/env python3
"""Verify a DOGFOOD certificate / judge participation record OFFLINE.

Needs only the Python standard library and the server's *public* key. No secret, no server round-trip
(the Ed25519 verification is the RFC 8032 reference algorithm, implemented right here).

    python verify_certificate.py --key <public_key_b64url> certificate.json
    python verify_certificate.py --key <public_key_b64url> certificate.html        (the verifiable-HTML download)
    python verify_certificate.py --server http://localhost:8000 certificate.json   (fetches the public key first)

`certificate.json` is the response of GET /events/{id}/certificates/{user_id} (or just {"payload":..,"signature":..}).
Exit status: 0 = valid, 1 = INVALID, 2 = usage / unreadable input.
"""

import argparse
import base64
import hashlib
import json
import re
import sys
import urllib.request

# ----------------------------------------------------------------------------- Ed25519 (RFC 8032, section 6)
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _Q - 2, _Q) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _inv(x: int) -> int:
    return pow(x, _Q - 2, _Q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    return _Q - x if x % 2 != 0 else x


_BY = 4 * _inv(5) % _Q
_B = (_xrecover(_BY) % _Q, _BY)


def _add(p, q):
    x1, y1 = p
    x2, y2 = q
    t = _D * x1 * x2 * y1 * y2
    return ((x1 * y2 + x2 * y1) * _inv(1 + t) % _Q, (y1 * y2 + x1 * x2) * _inv(1 - t) % _Q)


def _mul(p, e: int):
    result, addend = (0, 1), p
    while e:
        if e & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        e >>= 1
    return result


def _on_curve(p) -> bool:
    x, y = p
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _Q == 0


def _decode_point(s: bytes):
    if len(s) != 32:
        raise ValueError("bad point length")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if (x & 1) != (s[31] >> 7):
        x = _Q - x
    p = (x, y)
    if not _on_curve(p):
        raise ValueError("point is not on the curve")
    return p


def ed25519_verify(signature: bytes, message: bytes, public_key: bytes) -> bool:
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        r = _decode_point(signature[:32])
        a = _decode_point(public_key)
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _L
    return _mul(_B, s) == _add(r, _mul(a, h))


# ----------------------------------------------------------------------------- DOGFOOD document handling
def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(payload: dict) -> bytes:
    """UTF-8 JSON, keys sorted, no whitespace: the exact bytes the server signed."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_document(doc: dict, public_key_b64: str) -> tuple[bool, list[str]]:
    """Returns (valid, human-readable findings)."""
    notes: list[str] = []
    payload, signature = doc.get("payload"), doc.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False, ["document has no payload/signature"]
    key = b64u_decode(public_key_b64)
    key_id = hashlib.sha256(key).hexdigest()[:16]
    if doc.get("key_id") and doc["key_id"] != key_id:
        return False, [f"signed by key {doc['key_id']}, but the key you supplied is {key_id}"]
    ok = ed25519_verify(b64u_decode(signature), canonical(payload), key)
    notes.append("Ed25519 signature " + ("matches the payload" if ok else "does NOT match the payload"))
    code = hashlib.sha256(canonical(payload)).hexdigest()
    if doc.get("verify_hash") and doc["verify_hash"] != code:
        ok = False
        notes.append(f"verification code {doc['verify_hash']} does not match the payload hash {code}")
    return ok, notes


def load(path: str) -> dict:
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    m = re.search(r'<script type="application/json" id="dogfood-certificate">(.*?)</script>', text, re.S)
    return json.loads(m.group(1) if m else text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="certificate .json or verifiable .html ('-' = stdin)")
    ap.add_argument("--key", help="server public key (base64url), from /.well-known/dogfood-signing-key")
    ap.add_argument("--server", help="fetch the public key from this server instead of --key")
    args = ap.parse_args()
    try:
        doc = load(args.file)
        key = args.key
        if not key:
            base = (args.server or "http://localhost:8000").rstrip("/")
            key = json.load(urllib.request.urlopen(base + "/.well-known/dogfood-signing-key", timeout=10))["public_key"]
        ok, notes = verify_document(doc, key)
    except (OSError, ValueError, KeyError) as e:
        print(f"cannot verify: {e}", file=sys.stderr)
        return 2
    p = doc.get("payload", {})
    who = p.get("recipient", {}).get("name", "?")
    print(("VALID  " if ok else "INVALID  ") + f"{p.get('kind', '?')} for {who} at {p.get('event', {}).get('name', '?')} (issued {p.get('issued_at', '?')})")
    for n in notes:
        print("  -", n)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
