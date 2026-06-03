"""把 5 张选股表从某个源 SQLite 复制到本仓库 data/wind_history.db(精简 db)。

场景: 你在另一处(如 tech100)拉了数, 想同步到本仓库再 push。
日常其实不用它 —— 本仓库的 pull_*.py 直接写 data/wind_history.db。

用法:
    python scripts/export_db.py --src /Users/macbook/tech100/data/wind_history.db
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DST = ROOT / "data" / "wind_history.db"
TABLES = ["static_info", "monthly_membership", "daily_market",
          "annual_fundamental", "periodic_financials", "pipeline_freshness"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="源 wind_history.db 路径")
    args = ap.parse_args()
    src = Path(args.src).resolve()
    assert src.exists(), f"源库不存在: {src}"

    spec = importlib.util.spec_from_file_location("initdb", ROOT / "scripts" / "init_db_master_v4.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    DST.parent.mkdir(exist_ok=True)
    if DST.exists():
        os.remove(DST)
    dst = sqlite3.connect(DST)
    m._drop_ambiguous(dst)
    dst.executescript(m.SCHEMA)
    dst.commit()
    dst.execute(f"ATTACH DATABASE '{src}' AS s")
    for t in TABLES:
        cols = ",".join(r[1] for r in dst.execute(f"PRAGMA table_info({t})"))
        dst.execute(f"DELETE FROM {t}")
        dst.execute(f"INSERT INTO {t} ({cols}) SELECT {cols} FROM s.{t}")
        print(f"  {t:22s} {dst.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} 行")
    dst.commit()
    dst.execute("DETACH DATABASE s")
    dst.execute("VACUUM")
    dst.commit()
    dst.close()
    print(f"✅ 精简 db → {DST}  ({DST.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
