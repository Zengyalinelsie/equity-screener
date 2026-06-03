"""【年频】template_annual.xlsx (宽) → annual_fundamental (长表)。

把每只股的逐年 EPS 列反透视成「一行 = 一只股 × 一个财年」:
    - eps_<year>   → 实际年   (is_estimate=0)
    - eps_<year>E  → 一致预期  (is_estimate=1)
    - net_profit_raw / roe / equity_raw / net_debt_raw / ev1_raw / ebitda_raw → 挂最新实际财年行,
      并派生 nd_to_equity = net_debt/equity, ev_to_ebitda = ev1/ebitda。
    - np_rev_fy1 (FY1 一致预期 7 日修正) → 挂前瞻首年行。
    所有绝对值为 ODS 原值 (无单位换算), 清洗放看板。

表头从模板第 2 行动态读取, 因此 make_template_annual.py 改年份区间无需改本脚本。
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from _wind_xl import TIMEOUT, wait_calc

ROOT = Path(__file__).parent.parent.resolve()
TEMPLATE = ROOT / "templates" / "template_annual.xlsx"
DB = ROOT / "data" / "wind_history.db"
LOG_DIR = ROOT / "logs"


def _setup_log():
    LOG_DIR.mkdir(exist_ok=True)
    fn = LOG_DIR / f"pull_annual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(fn, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return logging.getLogger("pull_annual")


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


def _parse_eps_header(h: str):
    """'eps_2025' → (2025, 0); 'eps_2026E' → (2026, 1); 其它 → None."""
    if not isinstance(h, str) or not h.startswith("eps_"):
        return None
    tok = h[4:]
    is_est = 0
    if tok.endswith("E"):
        is_est = 1
        tok = tok[:-1]
    if not tok.isdigit():
        return None
    return int(tok), is_est


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    p.add_argument("--wait", type=float, default=5.0,
                   help="写 B1 后最小等待(s), 之后 wait_calc 轮询至收敛")
    return p.parse_args()


def main():
    args = parse_args()
    log = _setup_log()
    as_of = _date_iso(args.date)
    log.info(f"annual_fundamental 拉取  as_of={as_of} wait={args.wait}s")

    if not TEMPLATE.exists():
        log.error(f"模板不存在: {TEMPLATE}")
        sys.exit(1)

    import xlwings as xw

    apps = list(xw.apps)
    created_app = not apps
    app = apps[0] if apps else xw.App(visible=True)
    app.display_alerts = False
    log.info(f"{'新建' if created_app else '复用'} Excel pid={app.pid}")

    wb = None
    opened_wb = False
    try:
        for book in app.books:
            if Path(book.fullname).name == TEMPLATE.name:
                wb = book
                log.info("模板已打开, 复用")
                break
        if wb is None:
            wb = app.books.open(str(TEMPLATE))
            opened_wb = True
            log.info(f"打开 {TEMPLATE.name}")

        excel_date = _date_value(args.date)
        wb.app.calculation = "automatic"        # 信任 B1 写入触发重算, 不 app.calculate() (坑14)
        for sheet_name in ("a", "hk"):
            wb.sheets[sheet_name].range("B1").value = excel_date
            wb.sheets[sheet_name].range("B1").number_format = "yyyy-mm-dd"

        # wait_calc 等收敛 (占位符检测 + 稳定收敛), 而不是固定 sleep
        for sheet_name in ("a", "hk"):
            ok, _ = wait_calc(wb.sheets[sheet_name], min_wait=args.wait, log=log)
            if not ok:
                log.warning(f"⚠️ [{sheet_name}] 未在 {TIMEOUT}s 内收敛, 可能部分为空")

        def _read(ws):
            headers = ws.range("B2").expand("right").value
            if headers is None:
                return [], []
            if not isinstance(headers, list):
                headers = [headers]
            n_cols = len(headers)
            data = ws.range("A3").expand("down").value
            if data is None:
                return headers, []
            if not isinstance(data, list):
                data = [data]
            n = len(data)
            block = ws.range((3, 1), (2 + n, 1 + n_cols)).value
            if n == 1:
                block = [block]
            return headers, block

        headers_a, rows_a = _read(wb.sheets["a"])
        headers_hk, rows_hk = _read(wb.sheets["hk"])
        log.info(f"读取: A={len(rows_a)}行×{len(headers_a)}列 HK={len(rows_hk)}行×{len(headers_hk)}列")

        conn = sqlite3.connect(DB, timeout=60)   # 遇到锁等 60s 再报错 (防多终端短暂占用)
        cur = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def _emit(headers, rows, market: str) -> int:
            # 列名 → 索引 (row[0] 是 wind_code, headers 对应 row[1:])
            col = {h: i + 1 for i, h in enumerate(headers) if isinstance(h, str)}
            eps_cols = {h: _parse_eps_header(h) for h in col if _parse_eps_header(h)}
            actual_years = [yr for h, (yr, est) in eps_cols.items() if est == 0]
            latest_actual = max(actual_years) if actual_years else None
            fwd_years = [yr for h, (yr, est) in eps_cols.items() if est == 1]
            first_forward = min(fwd_years) if fwd_years else None

            codes = [str(r[0]).strip() for r in rows if r and r[0]]
            if codes:
                cur.executemany(
                    "DELETE FROM annual_fundamental WHERE wind_code = ?",
                    [(c,) for c in codes],
                )

            def g(r, name):
                return _num(r[col[name]]) if name in col else None

            count = 0
            for r in rows:
                if not r or not r[0]:
                    continue
                code = str(r[0]).strip()
                for h, (year, is_est) in eps_cols.items():
                    eps = _num(r[col[h]])
                    is_latest = (is_est == 0 and year == latest_actual)
                    is_fy1 = (is_est == 1 and year == first_forward)
                    # 逐年 ROE: 实际年从 roe_<year> 取 (供 5 年均 ROE)
                    roe = g(r, f"roe_{year}") if is_est == 0 else None
                    # 最新实际财年: 质量标量 + EV/EBITDA (ODS 原值)
                    np_raw = g(r, "net_profit_raw") if is_latest else None
                    eq = g(r, "equity_raw") if is_latest else None
                    nd = g(r, "net_debt_raw") if is_latest else None
                    ev1 = g(r, "ev1_raw") if is_latest else None
                    ebitda = g(r, "ebitda_raw") if is_latest else None
                    nde = (nd / eq) if (nd is not None and eq not in (None, 0)) else None
                    ev_eb = (ev1 / ebitda) if (ev1 is not None and ebitda not in (None, 0)) else None
                    # 前瞻首年行: 一致预期 周/月 修正 (均值 + 中值)
                    avg_1w = g(r, "np_avg_rev_1w") if is_fy1 else None
                    avg_1m = g(r, "np_avg_rev_1m") if is_fy1 else None
                    med_1w = g(r, "np_med_rev_1w") if is_fy1 else None
                    med_1m = g(r, "np_med_rev_1m") if is_fy1 else None
                    cur.execute(
                        "INSERT OR REPLACE INTO annual_fundamental "
                        "(wind_code, fiscal_year, report_date, market, eps, is_estimate, "
                        " net_profit_raw, roe, equity_raw, net_debt_raw, nd_to_equity, "
                        " ev1_raw, ebitda_raw, ev_to_ebitda, "
                        " np_avg_rev_1w, np_avg_rev_1m, np_med_rev_1w, np_med_rev_1m, last_update) "
                        "VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?, ?)",
                        (code, year, f"{year}-12-31", market, eps, is_est,
                         np_raw, roe, eq, nd, nde, ev1, ebitda, ev_eb,
                         avg_1w, avg_1m, med_1w, med_1m, now),
                    )
                    count += 1
            return count

        n_a = _emit(headers_a, rows_a, "A")
        n_hk = _emit(headers_hk, rows_hk, "HK")

        cur.execute(
            "INSERT OR REPLACE INTO pipeline_freshness (dataset, last_run, status, rows, notes) "
            "VALUES ('annual_fundamental', ?, 'ok', ?, ?)",
            (now, n_a + n_hk, f"as_of={as_of} A_rows={n_a} HK_rows={n_hk}"),
        )
        conn.commit()
        conn.close()
        log.info(f"✅ annual_fundamental {as_of}: 长表写入 A={n_a} HK={n_hk} 行")
    finally:
        if opened_wb and wb is not None:
            try:
                wb.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
