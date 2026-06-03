"""【财报回拉】对历史每一年的【年报 12-31 + 半年报 06-30】一期一期拉进 periodic_financials。

复用同一个 Excel 会话 + template_financials.xlsx, 逐期改 B1 → 等 Wind → 写库, 最后统一算同比。
这样不把好几年塞进一张大宽表 (macOS Excel 一次算太多会假死)。

    python scripts/backfill_financials.py --start-year 2021 --end-year 2025 --wait 240
    python scripts/backfill_financials.py --start-year 2021 --end-year 2025 --periods FY   # 只年报
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "scripts"))

from pull_financials import (  # noqa: E402
    DB, TEMPLATE, _recompute_yoy, _setup_log, pull_period,
)

_PERIOD_MMDD = {"FY": "12-31", "1H": "06-30", "Q1": "03-31", "Q3": "09-30"}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--periods", default="FY,1H,Q1,Q3",
                   help="逗号分隔, 默认 FY,1H,Q1,Q3 (年报+半年报+一/三季报, 全季度)")
    p.add_argument("--wait", type=float, default=5.0,
                   help="写 B1 后最小等待(s), 之后 wait_calc 轮询至收敛(超时600s)。默认5即可, 不要调小")
    return p.parse_args()


def main():
    args = parse_args()
    log = _setup_log()
    periods = [p.strip() for p in args.periods.split(",") if p.strip() in _PERIOD_MMDD]
    if not periods:
        log.error("无有效 periods (取值 FY/1H/Q1/Q3)")
        sys.exit(1)

    # 期末列表: 新年份在前
    dates = []
    for y in range(args.end_year, args.start_year - 1, -1):
        for pt in periods:
            dates.append(f"{y}-{_PERIOD_MMDD[pt]}")
    log.info(f"backfill periodic_financials: {len(dates)} 期 {dates}")

    if not TEMPLATE.exists():
        log.error(f"模板不存在: {TEMPLATE} (先跑 make_template_financials.py)")
        sys.exit(1)

    import xlwings as xw

    apps = list(xw.apps)
    app = apps[0] if apps else xw.App(visible=True)
    app.display_alerts = False
    log.info(f"{'复用' if apps else '新建'} Excel pid={app.pid}")

    wb = None
    opened = False
    try:
        for b in app.books:
            if Path(b.fullname).name == TEMPLATE.name:
                wb = b
                break
        if wb is None:
            wb = app.books.open(str(TEMPLATE))
            opened = True
            log.info(f"打开 {TEMPLATE.name}")

        conn = sqlite3.connect(DB, timeout=60)   # 遇到锁等 60s 再报错 (防多终端短暂占用)
        total = 0
        prev_flats = None
        for i, period_iso in enumerate(dates, 1):
            log.info(f"[{i}/{len(dates)}] {period_iso}")
            n, prev_flats = pull_period(wb, conn, period_iso, log,
                                        prev_flats=prev_flats, min_wait=args.wait)
            total += n

        _recompute_yoy(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_freshness (dataset, last_run, status, rows, notes) "
            "VALUES ('periodic_financials', ?, 'ok', ?, ?)",
            (now, total, f"backfill {dates[-1]}..{dates[0]} periods={periods}"),
        )
        conn.commit()
        conn.close()
        log.info(f"✅ backfill 完成: 共写 {total} 行, {len(dates)} 期")
    finally:
        if opened and wb is not None:
            try:
                wb.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
