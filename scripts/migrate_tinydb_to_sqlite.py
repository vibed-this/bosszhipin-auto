"""TinyDB -> SQLite data migration script."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tinydb import TinyDB
from bzauto.models_doc import AccountDoc, ConvDoc, JobDoc, RunDoc
from bzauto.storage import Storage


def migrate(
    old_path: str | Path = "data/bzauto.tinydb",
    new_path: str | Path = "data/bzauto.db",
) -> None:
    old_path = Path(old_path)
    new_path = Path(new_path)

    if not old_path.exists():
        print(f"[ERROR] TinyDB file not found: {old_path}")
        sys.exit(1)

    if new_path.exists():
        new_path.unlink()
        for suffix in ("-wal", "-shm"):
            p = new_path.with_name(new_path.name + suffix)
            if p.exists():
                p.unlink()

    size_mb = old_path.stat().st_size / 1024 / 1024
    print(f"Opening TinyDB: {old_path} ({size_mb:.1f} MB)")
    tinydb = TinyDB(str(old_path), access_mode="r", encoding="utf-8")

    print(f"Creating SQLite: {new_path}")
    store = Storage(new_path)

    start = time.monotonic()
    stats: dict[str, int] = {}

    # 1. jobs
    print("\n--- jobs ---")
    job_table = tinydb.table("jobs")
    old_jobs = len(job_table)
    new_jobs = 0
    for raw in job_table.all():
        raw.pop("doc_id", None)
        doc = JobDoc(**raw)
        store.jobs.upsert(doc)
        new_jobs += 1
    print(f"  {old_jobs} -> {new_jobs} rows")

    # 2. conversations (dedup by conv_id+account composite PK)
    print("\n--- conversations ---")
    conv_table = tinydb.table("conversations")
    old_conv_raw = len(conv_table)
    new_convs = 0
    seen_pks: set[tuple[str, str]] = set()
    for raw in conv_table.all():
        raw.pop("doc_id", None)
        pk = (raw.get("conv_id", ""), raw.get("account", ""))
        if pk in seen_pks:
            continue
        seen_pks.add(pk)
        doc = ConvDoc(**raw)
        store.conversations.upsert(doc)
        new_convs += 1
    print(f"  {old_conv_raw} raw -> {len(seen_pks)} unique -> {new_convs} rows")

    # 3. accounts
    print("\n--- accounts ---")
    acc_table = tinydb.table("accounts")
    old_accs = len(acc_table)
    new_accs = 0
    for raw in acc_table.all():
        raw.pop("doc_id", None)
        enabled = raw.get("enabled", True)
        if isinstance(enabled, bool):
            raw["enabled"] = int(enabled)
        doc = AccountDoc(**raw)
        store.accounts.tbl.upsert(doc.model_dump(), pk="account_id")
        new_accs += 1
    print(f"  {old_accs} -> {new_accs} rows")

    # 4. schedule_runs
    print("\n--- schedule_runs ---")
    run_table = tinydb.table("schedule_runs")
    old_runs = len(run_table)
    new_runs = 0
    for raw in run_table.all():
        raw.pop("doc_id", None)
        doc = RunDoc(**raw)
        store.runs.insert(doc)
        new_runs += 1
    print(f"  {old_runs} -> {new_runs} rows")

    # 5. meta
    print("\n--- meta ---")
    meta_table = tinydb.table("meta")
    old_meta = len(meta_table)
    new_meta = 0
    for raw in meta_table.all():
        key = raw.get("key", "")
        value = raw.get("value", "")
        store.meta.set(key, value)
        new_meta += 1
    print(f"  {old_meta} -> {new_meta} rows")

    # 6. seen_job_hrefs from meta
    print("\n--- seen_job_hrefs ---")
    seen_hrefs = store.meta.get("seen_job_hrefs", [])
    if isinstance(seen_hrefs, list) and seen_hrefs:
        added = store.seen_hrefs.add(seen_hrefs)
        print(f"  expanded {len(seen_hrefs)} hrefs -> {added} rows")
    else:
        print("  no seen_job_hrefs data")

    elapsed = time.monotonic() - start

    # verification
    print("\n" + "=" * 50)
    print("Verification")
    print("=" * 50)
    all_ok = True
    checks = [
        ("jobs", old_jobs, store.db["jobs"].count),
        ("conversations", len(seen_pks), store.db["conversations"].count),
        ("accounts", old_accs, store.db["accounts"].count),
        ("schedule_runs", old_runs, store.db["schedule_runs"].count),
    ]
    for name, old_c, new_c in checks:
        ok = old_c == new_c
        label = "OK" if ok else "FAIL"
        print(f"  {name}: {old_c} == {new_c}  [{label}]")
        if not ok:
            all_ok = False

    print(f"\nElapsed: {elapsed:.2f}s")
    if all_ok:
        print("\n[OK] Migration complete, all tables match.")
        print(f"  New SQLite DB: {new_path.resolve()}")
    else:
        print("\n[FAIL] Row counts mismatch, check logs.")

    tinydb.close()


if __name__ == "__main__":
    old = sys.argv[1] if len(sys.argv) > 1 else "data/bzauto.tinydb"
    new = sys.argv[2] if len(sys.argv) > 2 else "data/bzauto.db"
    migrate(old, new)
