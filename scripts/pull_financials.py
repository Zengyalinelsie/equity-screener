"""【财报】template_financials.xlsx (单报告期) → periodic_financials (长表)。

一次写一个报告期 (B1 = 报告期末)。营收/成本/费用/利息/税前/归母净利/经营现金流/Capex/EPS 取
Wind 原值, 毛利率/营业利润/营业利润率/净利息/营业外/FCF 在此派生。同比 (vs 去年同报告期)
由 _recompute_yoy 在写完后统一回填 (回拉历史时去年同期可能同批写入)。

backfill_financials.py 复用 pull_period() 对每年 FY+1H 一期一期回拉。

    python scripts/pull_financials.py --date 20251231 --wait 240
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from _wind_xl import MIN_WAIT, TIMEOUT, wait_calc

ROOT = Path(__file__).parent.parent.resolve()
TEMPLATE = ROOT / "templates" / "template_financials.xlsx"
DB = ROOT / "data" / "wind_history.db"
LOG_DIR = ROOT / "logs"

_PERIOD_TYPE = {"03-31": "Q1", "06-30": "1H", "09-30": "Q3", "12-31": "FY"}


def _setup_log():
    LOG_DIR.mkdir(exist_ok=True)
    fn = LOG_DIR / f"pull_financials_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(fn, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return logging.getLogger("pull_financials")


def _date_iso(yyyymmdd: str) -> str:
    s = str(yyyymmdd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _date_value(value: str):
    return datetime.strptime(_date_iso(value), "%Y-%m-%d").date()


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _sub(a, b):
    return (a - b) if (a is not None and b is not None) else None


def _ratio(a, b):
    return (a / b) if (a is not None and b not in (None, 0)) else None


def _read_sheet(ws):
    headers = ws.range("B2").expand("right").value
    if headers is None:
        return [], []
    if not isinstance(headers, list):
        headers = [headers]
    data = ws.range("A3").expand("down").value
    if data is None:
        return headers, []
    if not isinstance(data, list):
        data = [data]
    n = len(data)
    block = ws.range((3, 1), (2 + n, 1 + len(headers))).value
    if n == 1:
        block = [block]
    return headers, block


def _emit(conn, headers, rows, market, period_iso, now) -> int:
    col = {h: i + 1 for i, h in enumerate(headers) if isinstance(h, str)}
    period_type = _PERIOD_TYPE.get(period_iso[5:], "")
    cur = conn.cursor()

    def g(r, name):
        return _num(r[col[name]]) if name in col else None

    n = 0
    for r in rows:
        if not r or not r[0]:
            continue
        code = str(r[0]).strip()
        rev = g(r, "revenue_raw"); cogs = g(r, "cogs_raw")
        selling = g(r, "selling_exp_raw"); admin = g(r, "admin_exp_raw"); rd = g(r, "rd_exp_raw")
        int_exp = g(r, "interest_expense_raw"); int_inc = g(r, "interest_income_raw")
        pretax = g(r, "pretax_profit_raw"); net_profit = g(r, "net_profit_raw")
        ocf = g(r, "operating_cashflow_raw"); capex = g(r, "capex_raw")
        eps = g(r, "basic_eps")
        ar = g(r, "ar_turn_days"); ap = g(r, "ap_turn_days"); inv = g(r, "inv_turn_days")

        gross = _sub(rev, cogs)
        # 营业利润 = 营收 - 成本 - 销售 - 管理 - 研发 (源表 FC = EX - SUM(EY:FB))
        op_profit = None
        if rev is not None:
            op_profit = rev - sum(x for x in (cogs, selling, admin, rd) if x is not None)
        non_op = _sub(pretax, op_profit)
        net_int = _sub(int_exp, int_inc)
        fcf = _sub(ocf, capex)

        cur.execute(
            "INSERT OR REPLACE INTO periodic_financials "
            "(wind_code, period_date, period_type, market, "
            " revenue_raw, cogs_raw, gross_profit_raw, gross_margin, "
            " selling_exp_raw, admin_exp_raw, rd_exp_raw, operating_profit_raw, operating_margin, "
            " interest_expense_raw, interest_income_raw, net_interest_expense_raw, "
            " pretax_profit_raw, non_operating_income_raw, net_profit_raw, "
            " operating_cashflow_raw, capex_raw, free_cashflow_raw, basic_eps, "
            " ar_turn_days, ap_turn_days, inv_turn_days, "
            " revenue_yoy, net_profit_yoy, eps_yoy, last_update) "
            "VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?, ?,?,?, NULL,NULL,NULL, ?)",
            (code, period_iso, period_type, market,
             rev, cogs, gross, _ratio(gross, rev),
             selling, admin, rd, op_profit, _ratio(op_profit, rev),
             int_exp, int_inc, net_int,
             pretax, non_op, net_profit,
             ocf, capex, fcf, eps,
             ar, ap, inv, now),
        )
        n += 1
    return n


def _recompute_yoy(conn) -> None:
    """同比 = 本期 / 去年同报告期 - 1 (自连接, 12-31↔上一12-31, 06-30↔上一06-30)。"""
    conn.execute(
        """
        UPDATE periodic_financials AS curr
        SET revenue_yoy = CASE WHEN prev.revenue_raw IS NOT NULL AND prev.revenue_raw <> 0
                               THEN curr.revenue_raw / prev.revenue_raw - 1 END,
            net_profit_yoy = CASE WHEN prev.net_profit_raw IS NOT NULL AND prev.net_profit_raw <> 0
                               THEN curr.net_profit_raw / prev.net_profit_raw - 1 END,
            eps_yoy = CASE WHEN prev.basic_eps IS NOT NULL AND prev.basic_eps <> 0
                               THEN curr.basic_eps / prev.basic_eps - 1 END
        FROM periodic_financials AS prev
        WHERE prev.wind_code = curr.wind_code
          AND prev.period_date = date(curr.period_date, '-1 year')
        """
    )


def pull_period(wb, conn, period_iso: str, log, prev_flats=None, min_wait: float = MIN_WAIT):
    """设 B1=period_iso, wait_calc 等收敛后读两 sheet 写入。

    prev_flats: {"a": flat, "hk": flat} 上一期的数据快照, 用于防陈旧 (新一期必须 != 上一期)。
    返回 (写入行数, 本期 new_flats)。
    """
    prev_flats = prev_flats or {}
    excel_date = datetime.strptime(period_iso, "%Y-%m-%d").date()
    wb.app.calculation = "automatic"          # 信任 B1 写入自然触发重算, 绝不 app.calculate() (坑14)
    for sn in ("a", "hk"):
        wb.sheets[sn].range("B1").value = excel_date
        wb.sheets[sn].range("B1").number_format = "yyyy-mm-dd"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    new_flats = {}
    for sn, market in (("a", "A"), ("hk", "HK")):
        ok, flat = wait_calc(wb.sheets[sn], prev_flat=prev_flats.get(sn), min_wait=min_wait, log=log)
        new_flats[sn] = flat
        if not ok:
            log.warning(f"  ⚠️ {period_iso} [{sn}] 未在 {TIMEOUT}s 内收敛, 本期跳过此 sheet (不入库脏数据)")
            continue
        headers, rows = _read_sheet(wb.sheets[sn])
        total += _emit(conn, headers, rows, market, period_iso, now)
    conn.commit()
    log.info(f"  ✅ {period_iso}: 写入 {total} 行")
    return total, new_flats


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="报告期末, 如 20251231")
    p.add_argument("--wait", type=float, default=MIN_WAIT, help="写 B1 后最小等待 (s), 之后 wait_calc 轮询至收敛")
    return p.parse_args()


def main():
    args = parse_args()
    log = _setup_log()
    period_iso = _date_iso(args.date)
    log.info(f"periodic_financials 拉取  period={period_iso} min_wait={args.wait}s (wait_calc 轮询收敛)")

    if not TEMPLATE.exists():
        log.error(f"模板不存在: {TEMPLATE}")
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
        n, _ = pull_period(wb, conn, period_iso, log, min_wait=args.wait)
        _recompute_yoy(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_freshness (dataset, last_run, status, rows, notes) "
            "VALUES ('periodic_financials', ?, 'ok', ?, ?)",
            (now, n, f"period={period_iso}"),
        )
        conn.commit()
        conn.close()
        log.info(f"✅ periodic_financials {period_iso}: {n} 行")
    finally:
        if opened and wb is not None:
            try:
                wb.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
