"""【静态/低频】公司基础信息拉取 —— template_static.xlsx 双 sheet → static_info.

[a] sheet: wind_code, name, sw_l1, sw_l2, ipo_date
[hk] sheet: wind_code, name, sw_l1, sw_l2, ipo_date

board 保留为兼容列，但当前目标产物不用，入库写 NULL。
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
TEMPLATE = ROOT / "templates" / "template_static.xlsx"
DB = ROOT / "data" / "wind_history.db"
LOG_DIR = ROOT / "logs"


def _setup_log():
    LOG_DIR.mkdir(exist_ok=True)
    fn = LOG_DIR / f"pull_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(fn, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return logging.getLogger("pull_info")


def _norm_date(s):
    if s is None or s == "":
        return None
    if hasattr(s, "strftime"):
        return s.strftime("%Y-%m-%d")
    s = str(s).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s[:10] if s else None


def _txt(v):
    if v is None: return None
    s = str(v).strip()
    return s if s and s.lower() != "none" else None


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    p.add_argument("--wait", type=int, default=120)
    return p.parse_args()


def main():
    args = parse_args()
    log = _setup_log()
    log.info(f"info 拉取  date={args.date}  wait={args.wait}s")

    if not TEMPLATE.exists():
        log.error(f"模板不存在: {TEMPLATE}")
        sys.exit(1)

    import xlwings as xw
    apps = list(xw.apps)
    created_app = not apps
    app = apps[0] if apps else xw.App(visible=True)
    app.display_alerts = False
    log.info(f"{'新建' if created_app else '复用'} Excel pid={app.pid}")

    wb = None; opened_wb = False
    try:
        for b in app.books:
            if Path(b.fullname).name == TEMPLATE.name:
                wb = b; log.info("模板已打开, 复用"); break
        if wb is None:
            wb = app.books.open(str(TEMPLATE))
            opened_wb = True
            log.info(f"打开 {TEMPLATE.name}")

        wb.sheets["a"].range("B1").value = args.date
        wb.sheets["hk"].range("B1").value = args.date

        if args.wait > 0:
            log.info(f"等待 Wind 计算 {args.wait}s ...")
            time.sleep(args.wait)

        # ----- 读 sheets -----
        ws_a = wb.sheets["a"]
        ws_hk = wb.sheets["hk"]

        # 用 expand 自动找数据底, 但保险起见以 last A 列空判定
        # A 列 row3 起读, 直到第一个空
        def _read(ws, n_cols):
            data = ws.range("A3").expand("down").value
            if data is None:
                return []
            if not isinstance(data, list):
                data = [data]
            n = len(data)
            block = ws.range((3, 1), (2 + n, 1 + n_cols)).value
            if n == 1:
                block = [block]
            return block

        rows_a  = _read(ws_a,  4)  # name, sw_l1, sw_l2, ipo_date
        rows_hk = _read(ws_hk, 4)  # name, sw_l1, sw_l2, ipo_date
        log.info(f"读取: A={len(rows_a)} HK={len(rows_hk)}")

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM static_info")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        n_a = 0
        for row in rows_a:
            code, name, sw1, sw2, ipo = row
            if not code: continue
            cur.execute(
                 "INSERT OR REPLACE INTO static_info "
                 "(wind_code, market, name, board, sw_l1, sw_l2, gics_l1, ipo_date, "
                 " industry_l1, industry_l2, list_date, last_update) "
                 "VALUES (?, 'A', ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (str(code).strip(), _txt(name),
                  _txt(sw1), _txt(sw2), _norm_date(ipo),
                  _txt(sw1), _txt(sw2), _norm_date(ipo), now),
            )
            n_a += 1

        n_hk = 0
        for row in rows_hk:
            code, name, sw1, sw2, ipo = row
            if not code: continue
            cur.execute(
                 "INSERT OR REPLACE INTO static_info "
                 "(wind_code, market, name, board, sw_l1, sw_l2, gics_l1, ipo_date, "
                 " industry_l1, industry_l2, list_date, last_update) "
                 "VALUES (?, 'HK', ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (str(code).strip(), _txt(name),
                  _txt(sw1), _txt(sw2), _norm_date(ipo),
                  _txt(sw1), _txt(sw2), _norm_date(ipo), now),
            )
            n_hk += 1

        cur.execute(
            "INSERT OR REPLACE INTO pipeline_freshness (dataset, last_run, status, rows, notes) "
            "VALUES ('static_info', ?, 'ok', ?, ?)",
            (now, n_a + n_hk, f"A={n_a} HK={n_hk}"),
        )
        conn.commit()
        conn.close()
        log.info(f"✅ static_info: A={n_a} HK={n_hk}")
    finally:
        if opened_wb and wb is not None:
            try: wb.close()
            except Exception: pass


if __name__ == "__main__":
    main()
