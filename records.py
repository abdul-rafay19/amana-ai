"""Work Record Agent storage: canonical JSON -> SHA-256 fingerprint, chained
to the previous record. A hash detects CHANGES after the fact; it does not
prove that the worker's original information was true."""
from __future__ import annotations

import hashlib
import json
import os

import db

GENESIS = "GENESIS"


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def _payload(order_no, version, prev_hash, data, created_at) -> dict:
    return {"order_no": order_no, "version": version, "prev_hash": prev_hash,
            "created_at": created_at, "data": data}


def compute_hash(order_no, version, prev_hash, data, created_at) -> str:
    return sha256_hex(canonical(_payload(order_no, version, prev_hash, data, created_at)))


def field_hashes(data: dict) -> dict:
    return {k: sha256_hex(canonical(v)) for k, v in data.items()}


def _last_hash(c, owner) -> str:
    r = c.execute("SELECT hash FROM records WHERE owner=? ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
    return r["hash"] if r else GENESIS


def next_order_no(owner: str) -> str:
    with db.conn() as c:
        n = c.execute("SELECT COUNT(DISTINCT order_no) n FROM records WHERE owner=?", (owner,)).fetchone()["n"]
    return f"AM-{db.now()[2:4]}{db.now()[5:7]}-{n + 1:03d}"


def create_record(owner: str, data: dict, order_no: str | None = None, is_sample=False) -> dict:
    """data = confirmed order fields + calculated fields + `sources` map."""
    order_no = order_no or next_order_no(owner)
    data = dict(data, order_no=order_no)
    ts = db.now()
    with db.conn() as c:
        prev = _last_hash(c, owner)
        version = 1
        h = compute_hash(order_no, version, prev, data, ts)
        c.execute(
            "INSERT INTO records(owner,order_no,version,data_json,original_json,field_hashes,prev_hash,hash,created_at,is_sample)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (owner, order_no, version, canonical(data), canonical(data), canonical(field_hashes(data)),
             prev, h, ts, int(is_sample)))
    return latest_record(owner, order_no)


def add_version(owner: str, order_no: str, changes: dict) -> dict:
    """Edits never overwrite: they create version n+1 that points to the previous hash."""
    cur = latest_record(owner, order_no)
    if not cur:
        raise KeyError(order_no)
    data = dict(cur["data"], **changes)
    sources = dict(data.get("sources", {}))
    for k in changes:
        sources[k] = "reported_by_worker"
    data["sources"] = sources
    ts = db.now()
    with db.conn() as c:
        prev = _last_hash(c, owner)
        version = cur["version"] + 1
        h = compute_hash(order_no, version, prev, data, ts)
        c.execute(
            "INSERT INTO records(owner,order_no,version,data_json,original_json,field_hashes,prev_hash,hash,created_at,is_sample)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (owner, order_no, version, canonical(data), canonical(data), canonical(field_hashes(data)),
             prev, h, ts, cur["is_sample"]))
    return latest_record(owner, order_no)


def _row(r) -> dict:
    d = dict(r)
    d["data"] = json.loads(d["data_json"])
    d["original"] = json.loads(d["original_json"])
    d["field_hashes"] = json.loads(d["field_hashes"])
    return d


def latest_record(owner: str, order_no: str):
    with db.conn() as c:
        r = c.execute("SELECT * FROM records WHERE owner=? AND order_no=? ORDER BY version DESC LIMIT 1",
                      (owner, order_no)).fetchone()
    return _row(r) if r else None


def all_versions(owner: str, order_no: str) -> list[dict]:
    with db.conn() as c:
        rs = c.execute("SELECT * FROM records WHERE owner=? AND order_no=? ORDER BY version", (owner, order_no)).fetchall()
    return [_row(r) for r in rs]


def list_orders(owner: str) -> list[dict]:
    """Latest version of each order, newest first."""
    with db.conn() as c:
        nos = [r["order_no"] for r in c.execute(
            "SELECT order_no, MAX(id) m FROM records WHERE owner=? GROUP BY order_no ORDER BY m DESC", (owner,))]
    return [latest_record(owner, n) for n in nos]


def verify_record(row: dict) -> dict:
    """Recompute the hash from the stored data and compare to the stored hash."""
    data = json.loads(row["data_json"]) if "data" not in row else row["data"]
    actual = compute_hash(row["order_no"], row["version"], row["prev_hash"], data, row["created_at"])
    ok = actual == row["hash"]
    changed = []
    if not ok:
        stored = row["field_hashes"]
        now_h = field_hashes(data)
        changed = sorted({k for k in set(stored) | set(now_h) if stored.get(k) != now_h.get(k)})
    return {"ok": ok, "stored_hash": row["hash"], "recomputed_hash": actual, "changed_fields": changed}


def verify_chain(owner: str) -> dict:
    with db.conn() as c:
        rs = [_row(r) for r in c.execute("SELECT * FROM records WHERE owner=? ORDER BY id", (owner,))]
    prev, bad = GENESIS, []
    for r in rs:
        v = verify_record(r)
        if not v["ok"]:
            bad.append((r["order_no"], r["version"], "data changed"))
        if r["prev_hash"] != prev:
            bad.append((r["order_no"], r["version"], "chain link broken"))
        prev = r["hash"]
    return {"ok": not bad, "length": len(rs), "problems": bad}


# ----- demo helpers (used by the "tamper test" button) -----
def tamper_demo(owner: str, order_no: str) -> str:
    """Silently change the rate inside the stored data WITHOUT re-hashing."""
    r = latest_record(owner, order_no)
    data = dict(r["data"])
    data["rate_per_piece"] = (data.get("rate_per_piece") or 0) + 50
    with db.conn() as c:
        c.execute("UPDATE records SET data_json=? WHERE id=?", (canonical(data), r["id"]))
    return "rate_per_piece"


def restore_original(owner: str, order_no: str):
    r = latest_record(owner, order_no)
    with db.conn() as c:
        c.execute("UPDATE records SET data_json=original_json WHERE id=?", (r["id"],))


# ----- payments -----
def save_payment(owner: str, order_no: str, agreement_hash: str, data: dict, evidence_hash=None) -> dict:
    ts = db.now()
    data = dict(data, order_no=order_no, agreement_hash=agreement_hash)
    h = sha256_hex(canonical({"created_at": ts, "data": data}))
    with db.conn() as c:
        c.execute("INSERT INTO payments(owner,order_no,agreement_hash,data_json,hash,evidence_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                  (owner, order_no, agreement_hash, canonical(data), h, evidence_hash, ts))
    return {"hash": h, "created_at": ts, "data": data}


def list_payments(owner: str, order_no: str | None = None) -> list[dict]:
    q, a = "SELECT * FROM payments WHERE owner=?", [owner]
    if order_no:
        q += " AND order_no=?"; a.append(order_no)
    with db.conn() as c:
        rs = c.execute(q + " ORDER BY id", a).fetchall()
    out = []
    for r in rs:
        d = dict(r); d["data"] = json.loads(d["data_json"]); out.append(d)
    return out


def save_evidence(owner: str, file_bytes: bytes, filename: str) -> str:
    h = sha256_hex(file_bytes)
    folder = os.path.join(os.path.dirname(__file__), "evidence", sha256_hex(owner)[:12])
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(filename)[1][:6].lower()
    with open(os.path.join(folder, h[:16] + ext), "wb") as f:
        f.write(file_bytes)
    return h


def save_followup(owner: str, order_no: str, text: str, status: str):
    with db.conn() as c:
        c.execute("INSERT INTO followups(owner,order_no,text,status,created_at) VALUES(?,?,?,?,?)",
                  (owner, order_no, text, status, db.now()))


def list_followups(owner: str, order_no: str):
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM followups WHERE owner=? AND order_no=? ORDER BY id", (owner, order_no))]
