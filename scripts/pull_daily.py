"""【日频】市场快照拉取 —— template_daily.xlsx 三 sheet → daily_market.

[a] sheet 19 列: close, volume, amount, turnover_rate, mkt_cap_yi,
                 ev_mn, ev1_mn, amount_1m_wind,
                 pe_ttm, pb, div_yield, ev_ebitda, beta_24m, profit_alert, ytd_return,
                 iw_50, iw_300, iw_500, iw_1000

[hk] sheet 18 列: close, volume, amount, turnover_rate, mkt_cap_yi,
                  ev_mn, ev1_mn, amount_1m_wind,
                  pe_ttm, pb, div_yield, ev_ebitda, beta_24m, profit_alert, ytd_return,
                  iw_hsi, iw_hscei, iw_hstech

[index] sheet 5 列: close, pe_ttm, pb, div_yield, fy1_eps

注: A/HK 的 PB 都写入 daily_market.pb 列；指数权重日频来自 s_info_indexweight。
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
TEMPLATE = ROOT / "templates" / "template_daily.xlsx"
DB = ROOT / "data" / "wind_history.db"
LOG_DIR = ROOT / "logs"

BROAD_INDEX_CODES = {
    "000016.SH",
    "000300.SH",
    "000852.SH",
    "000905.SH",
    "HSCEI.HI",
    "HSCI.HI",
    "HSCNCI.HI",
    "HSI.HI",
    "HSTECH.HI",
}


def _setup_log():
    LOG_DIR.mkdir(exist_ok=True)
    fn = LOG_DIR / f"pull_daily_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(fn, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return logging.getLogger("pull_daily")


def _date_iso(yyyymmdd: str) -> str:
    s = str(yyyymmdd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _date_value(value: str) -> date:
    return datetime.strptime(_date_iso(value), "%Y-%m-%d").date()


def _num(v):
    if v is None or v == "": return None
    try: return float(v)
    except (ValueError, TypeError): return None


def _entity_type(code: str) -> str:
    return "index" if code in BROAD_INDEX_CODES else "industry"


def _market(code: str) -> str:
    return "HK" if code.endswith(".HI") else "A"


def _ensure_daily_market_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(daily_market)")}
    if "fy1_eps" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN fy1_eps REAL")
    if "ev_mn" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN ev_mn REAL")
    if "ev1_mn" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN ev1_mn REAL")
    if "amount_1m_wind" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN amount_1m_wind REAL")
    if "beta_24m" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN beta_24m REAL")
    if "profit_alert" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN profit_alert REAL")
    if "ytd_return" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN ytd_return REAL")
    if "iw_50" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_50 REAL")
    if "iw_300" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_300 REAL")
    if "iw_500" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_500 REAL")
    if "iw_1000" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_1000 REAL")
    if "iw_hsi" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_hsi REAL")
    if "iw_hscei" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_hscei REAL")
    if "iw_hstech" not in existing:
        conn.execute("ALTER TABLE daily_market ADD COLUMN iw_hstech REAL")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    p.add_argument("--wait", type=int, default=240)
    return p.parse_args()


def main():
    args = parse_args()
    log = _setup_log()
    trade_date = _date_iso(args.date)
    log.info(f"daily 拉取  date={trade_date}  wait={args.wait}s")

    if not TEMPLATE.exists():
        log.error(f"模板不存在: {TEMPLATE}"); sys.exit(1)

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

        sheet_names = {sheet.name for sheet in wb.sheets}
        excel_date = _date_value(args.date)
        for sheet_name in ("a", "hk", "index"):
            if sheet_name in sheet_names:
                wb.sheets[sheet_name].range("B1").value = excel_date
                wb.sheets[sheet_name].range("B1").number_format = "yyyy-mm-dd"

        if args.wait > 0:
            log.info(f"等待 Wind 计算 {args.wait}s ...")
            time.sleep(args.wait)

        def _read(ws, n_cols):
            data = ws.range("A3").expand("down").value
            if data is None: return []
            if not isinstance(data, list): data = [data]
            n = len(data)
            block = ws.range((3, 1), (2 + n, 1 + n_cols)).value
            if n == 1: block = [block]
            return block

        rows_a  = _read(wb.sheets["a"],  19)
        rows_hk = _read(wb.sheets["hk"], 18)
        rows_index = _read(wb.sheets["index"], 5) if "index" in sheet_names else []
        log.info(f"读取: A={len(rows_a)} HK={len(rows_hk)} INDEX={len(rows_index)}")

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        _ensure_daily_market_columns(conn)
        cur.execute(
            "DELETE FROM daily_market WHERE trade_date = ? AND entity_type IN ('stock', 'index', 'industry')",
            (trade_date,),
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        n_a = 0
        for row in rows_a:
            code = row[0]
            if not code: continue
            (
                _, close, volume, amt, turn, mcap, ev_mn, ev1_mn, amount_1m_wind,
                pe, pb, divy, ev, beta, alert, ytd,
                iw_50, iw_300, iw_500, iw_1000,
            ) = (code, *row[1:])
            cur.execute(
                "INSERT OR REPLACE INTO daily_market "
                "(trade_date, entity_type, wind_code, market, close, volume, amount, "
                " turnover_rate, mkt_cap_yi, ev_mn, ev1_mn, amount_1m_wind, mkt_freeshares_yi, pe_ttm, pb, div_yield, "
                " fy1_eps, ev_ebitda, beta_24m, profit_alert, ytd_return, iw_50, iw_300, iw_500, iw_1000, iw_hsi, iw_hscei, iw_hstech, last_update) "
                "VALUES (?, 'stock', ?, 'A', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trade_date, str(code).strip(),
                 _num(close), _num(volume), _num(amt), _num(turn), _num(mcap),
                 _num(ev_mn), _num(ev1_mn), _num(amount_1m_wind),
                 _num(pe), _num(pb), _num(divy), _num(ev), _num(beta), _num(alert), _num(ytd),
                  _num(iw_50), _num(iw_300), _num(iw_500), _num(iw_1000), None, None, None,
                 now),
            )
            n_a += 1

        n_hk = 0
        for row in rows_hk:
            code = row[0]
            if not code: continue
            (
                _, close, volume, amt, turn, mcap, ev_mn, ev1_mn, amount_1m_wind,
                pe, pb, divy, ev, beta, alert, ytd,
                iw_hsi, iw_hscei, iw_hstech,
            ) = (code, *row[1:])
            cur.execute(
                "INSERT OR REPLACE INTO daily_market "
                "(trade_date, entity_type, wind_code, market, close, volume, amount, "
                " turnover_rate, mkt_cap_yi, ev_mn, ev1_mn, amount_1m_wind, mkt_freeshares_yi, pe_ttm, pb, div_yield, "
                " fy1_eps, ev_ebitda, beta_24m, profit_alert, ytd_return, iw_50, iw_300, iw_500, iw_1000, iw_hsi, iw_hscei, iw_hstech, last_update) "
                "VALUES (?, 'stock', ?, 'HK', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trade_date, str(code).strip(),
                 _num(close), _num(volume), _num(amt), _num(turn), _num(mcap),
                 _num(ev_mn), _num(ev1_mn), _num(amount_1m_wind),
                 _num(pe), _num(pb), _num(divy), _num(ev), _num(beta), _num(alert), _num(ytd),
                  None, None, None, None, _num(iw_hsi), _num(iw_hscei), _num(iw_hstech),
                 now),
            )
            n_hk += 1

        n_index = 0
        n_industry = 0
        for row in rows_index:
            code = str(row[0]).strip() if row and row[0] else ""
            if not code:
                continue
            (_, close, pe, pb, divy, fy1_eps) = (code, *row[1:])
            entity_type = _entity_type(code)
            cur.execute(
                "INSERT OR REPLACE INTO daily_market "
                "(trade_date, entity_type, wind_code, market, close, volume, amount, "
                 " turnover_rate, mkt_cap_yi, ev_mn, ev1_mn, amount_1m_wind, mkt_freeshares_yi, pe_ttm, pb, div_yield, "
                 " fy1_eps, ev_ebitda, beta_24m, profit_alert, ytd_return, iw_50, iw_300, iw_500, iw_1000, iw_hsi, iw_hscei, iw_hstech, last_update) "
                 "VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)",
                (trade_date, entity_type, code, _market(code),
                 _num(close), _num(pe), _num(pb), _num(divy), _num(fy1_eps), now),
            )
            if entity_type == "index":
                n_index += 1
            else:
                n_industry += 1

        cur.execute(
            "INSERT OR REPLACE INTO pipeline_freshness (dataset, last_run, status, rows, notes) "
            "VALUES ('daily_market', ?, 'ok', ?, ?)",
            (
                now,
                n_a + n_hk + n_index + n_industry,
                f"date={trade_date} A={n_a} HK={n_hk} index={n_index} industry={n_industry}",
            ),
        )
        conn.commit()
        conn.close()
        log.info(f"✅ daily_market {trade_date}: A={n_a} HK={n_hk} index={n_index} industry={n_industry}")
    finally:
        if opened_wb and wb is not None:
            try: wb.close()
            except Exception: pass


if __name__ == "__main__":
    main()
