"""选股看板数据适配层。

把按更新频率组织的基础表拼成 screener.py 期望的一行一股宽表。这里不直接计算选股规则，
只负责数据 join、指数池过滤和少量由日频行情可以可靠派生的特征。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "wind_history.db"

INDEX_OPTIONS = {
    "000016.SH": "上证 50",
    "000300.SH": "沪深 300",
    "000905.SH": "中证 500",
    "000852.SH": "中证 1000",
    "HSI.HI": "恒生指数",
    "HSCEI.HI": "恒生中国企业",
    "HSTECH.HI": "恒生科技",
}

INDEX_FLAG_MAP = {
    "000016.SH": "in_50",
    "000300.SH": "in_300",
    "000905.SH": "in_500",
    "000852.SH": "in_1000",
    "HSI.HI": "in_hsi",
    "HSCEI.HI": "in_hscei",
    "HSTECH.HI": "in_hstech",
}

INDEX_WEIGHT_EXPR = {
    "000016.SH": "COALESCE(d.iw_50, m.w_50)",
    "000300.SH": "COALESCE(d.iw_300, m.w_300)",
    "000905.SH": "COALESCE(d.iw_500, m.w_500)",
    "000852.SH": "COALESCE(d.iw_1000, m.w_1000)",
    "HSI.HI": "COALESCE(d.iw_hsi, m.w_hsi)",
    "HSCEI.HI": "COALESCE(d.iw_hscei, m.w_hscei)",
    "HSTECH.HI": "COALESCE(d.iw_hstech, m.w_hstech)",
}

INDEX_DAILY_NAMES = {
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000852.SH": "中证1000",
    "000905.SH": "中证500",
    "801010.SI": "农林牧渔",
    "801030.SI": "基础化工",
    "801040.SI": "钢铁",
    "801050.SI": "有色金属",
    "801080.SI": "电子",
    "801110.SI": "家用电器",
    "801150.SI": "医药生物",
    "801160.SI": "公用事业",
    "801170.SI": "交通运输",
    "801180.SI": "房地产",
    "801200.SI": "商贸零售",
    "801780.SI": "银行",
    "HSCEI.HI": "恒生中国企业",
    "HSCI.HI": "恒生综合指数",
    "HSCNCI.HI": "恒生中国内地企业",
    "HSI.HI": "恒生指数",
    "HSTECH.HI": "恒生科技",
    "HSCI10.HI": "恒生综合能源业",
    "HSCI20.HI": "恒生综合原材料业",
    "HSCICD.HI": "恒生综合非必需性消费业",
    "HSCIFD.HI": "恒生综合必需性消费业",
    "HSCIHC.HI": "恒生综合医疗保健业",
    "HSCIIN.HI": "恒生综合工业",
    "HSCIIT.HI": "恒生综合资讯科技业",
    "HSCIMT.HI": "恒生综合综合企业",
    "HSCIOG.HI": "恒生综合地产建筑业",
    "HSCIRE.HI": "恒生综合金融业",
    "HSCITL.HI": "恒生综合电讯业",
    "HSCIUT.HI": "恒生综合公用事业",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _placeholders(values: Iterable[str]) -> str:
    return ",".join("?" for _ in values)


def _normalise_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_cols = [
        "close", "amount", "amount_1m", "amount_1m_wind", "mkt_cap_cny", "ev_mn", "ev1_mn", "pe_ttm", "pb_lf",
        "ev_ebitda", "div_yield", "ytd_return", "volume", "turnover_rate",
        "beta_24m", "profit_alert",
        "w_50", "w_300", "w_500", "w_1000", "w_hsi", "w_hscei", "w_hstech",
        # annual_fundamental 派生
        "roe_ttm", "roe_5y_avg", "nd_to_equity", "eps_actual_latest", "fy1_eps", "fy2_eps",
        "fwd_ep", "eps_fy1_growth", "eps_growth",
        "np_avg_rev_1w", "np_avg_rev_1m", "np_med_rev_1w", "np_med_rev_1m",
        # periodic_financials 派生
        "eps_yoy_q", "eps_yoy_acc", "net_profit_yoy", "revenue_yoy",
        "gross_margin", "operating_margin", "net_margin", "fcf",
        "revenue", "gross_profit", "operating_profit", "pretax_profit", "net_profit_fy",
        "ar_turn_days", "inv_turn_days",
        "rev_yoy_fy", "op_yoy_fy", "pretax_yoy_fy", "np_yoy_fy",
        "rev_cagr3", "op_cagr3", "pretax_cagr3", "np_cagr3",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in ["close", "amount", "mkt_cap_cny", "pe_ttm", "pb_lf", "ev_ebitda"]:
        if col in out.columns:
            out.loc[out[col] == 0, col] = np.nan
    return out


def load_v4_snapshot(
    db_path: Path | str = DB_PATH,
    trade_date: str | None = None,
    universe_indexes: tuple[str, ...] = (),
    markets: tuple[str, ...] = (),
) -> pd.DataFrame:
    """读取最新股票快照。

    返回列尽量对齐 app/screener.py 的输入：wind_code/name/sw_l1/mkt_cap_cny/
    amount_1m/pe_ttm/pb_lf/ev_ebitda/div_yield/ytd_return 等。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        required = [
            "daily_market",
            "static_info",
            "monthly_membership",
        ]
        if any(not _table_exists(conn, table) for table in required):
            return pd.DataFrame()
        # annual_fundamental / periodic_financials 为可选 (首次 annual/financials pull 前可能为空),
        # 用 LEFT JOIN 容忍缺失。

        if trade_date is None:
            row = conn.execute(
                "SELECT MAX(trade_date) FROM daily_market WHERE entity_type = 'stock'"
            ).fetchone()
            trade_date = row[0] if row else None
        if not trade_date:
            return pd.DataFrame()

        where = ["d.trade_date = ?", "d.entity_type = 'stock'"]
        where_params: list[object] = [trade_date]

        markets = tuple(m for m in markets if m in {"A", "HK"})
        if markets:
            where.append(f"d.market IN ({_placeholders(markets)})")
            where_params.extend(markets)

        weight_exprs = [INDEX_WEIGHT_EXPR[idx] for idx in universe_indexes if idx in INDEX_WEIGHT_EXPR]
        if weight_exprs:
            where.append("(" + " OR ".join(f"COALESCE({expr}, 0) > 0" for expr in weight_exprs) + ")")

        where_sql = "WHERE " + " AND ".join(where)

        sql = f"""
        WITH amount_1m AS (
            SELECT wind_code, SUM(COALESCE(amount, 0)) / 10000.0 AS amount_1m
                        FROM daily_market
                        WHERE entity_type = 'stock'
                            AND trade_date <= ? AND trade_date >= date(?, '-45 day')
            GROUP BY wind_code
        ),
        year_start AS (
            SELECT d0.wind_code, d0.close AS year_start_close
                        FROM daily_market d0
            JOIN (
                SELECT wind_code, MIN(trade_date) AS first_date
                                FROM daily_market
                                WHERE entity_type = 'stock'
                                    AND trade_date >= substr(?, 1, 4) || '-01-01'
                  AND trade_date <= ?
                GROUP BY wind_code
            ) y ON y.wind_code = d0.wind_code AND y.first_date = d0.trade_date
        ),
                latest_membership AS (
                        SELECT m.*
                        FROM monthly_membership m
            JOIN (
                                SELECT wind_code, MAX(as_of_date) AS as_of_date
                                FROM monthly_membership
                                WHERE as_of_date <= ?
                                GROUP BY wind_code
            ) latest
                            ON latest.wind_code = m.wind_code
                         AND latest.as_of_date = m.as_of_date
        ),
                        latest_actual AS (
                            -- 最新实际财年 (is_estimate=0): ROE / ND-E / 最新实际 EPS
                            SELECT a.wind_code, a.eps AS eps_actual_latest,
                                   a.roe, a.nd_to_equity
                            FROM annual_fundamental a
                            JOIN (
                                SELECT wind_code, MAX(fiscal_year) AS fy
                                FROM annual_fundamental WHERE is_estimate = 0
                                GROUP BY wind_code
                            ) t ON t.wind_code = a.wind_code AND t.fy = a.fiscal_year
                            WHERE a.is_estimate = 0
                        ),
                        roe5 AS (
                            -- 近 5 个实际财年平均 ROE
                            SELECT wind_code, AVG(roe) AS roe_5y_avg
                            FROM (
                                SELECT wind_code, roe,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY wind_code ORDER BY fiscal_year DESC
                                       ) AS rn
                                FROM annual_fundamental
                                WHERE is_estimate = 0 AND roe IS NOT NULL
                            ) z WHERE rn <= 5 GROUP BY wind_code
                        ),
                        fwd AS (
                            -- 前瞻一致预期 (is_estimate=1): FY1/FY2 EPS + FY1 周/月修正
                            SELECT wind_code,
                                   MAX(CASE WHEN rn = 1 THEN eps END) AS fy1_eps,
                                   MAX(CASE WHEN rn = 2 THEN eps END) AS fy2_eps,
                                   MAX(CASE WHEN rn = 1 THEN np_avg_rev_1w END) AS np_avg_rev_1w,
                                   MAX(CASE WHEN rn = 1 THEN np_avg_rev_1m END) AS np_avg_rev_1m,
                                   MAX(CASE WHEN rn = 1 THEN np_med_rev_1w END) AS np_med_rev_1w,
                                   MAX(CASE WHEN rn = 1 THEN np_med_rev_1m END) AS np_med_rev_1m
                            FROM (
                                SELECT wind_code, eps, np_avg_rev_1w, np_avg_rev_1m,
                                       np_med_rev_1w, np_med_rev_1m,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY wind_code ORDER BY fiscal_year
                                       ) AS rn
                                FROM annual_fundamental WHERE is_estimate = 1
                            ) z GROUP BY wind_code
                        ),
                        latest_fin AS (
                            -- 最新报告期 (任意期): 同比 / 毛利率 / FCF
                            SELECT p.wind_code, p.eps_yoy, p.net_profit_yoy, p.revenue_yoy,
                                   p.gross_margin, p.operating_margin, p.free_cashflow_raw
                            FROM periodic_financials p
                            JOIN (
                                SELECT wind_code, MAX(period_date) AS pd
                                FROM periodic_financials GROUP BY wind_code
                            ) t ON t.wind_code = p.wind_code AND t.pd = p.period_date
                        ),
                        latest_fy AS (
                            -- 最新年报 (FY): 经营绝对值 + 净利率 + 周转天数 (供行业 Top N / 天数排序)
                            SELECT p.wind_code,
                                   p.revenue_raw, p.gross_profit_raw, p.operating_profit_raw,
                                   p.pretax_profit_raw, p.net_profit_raw,
                                   p.ar_turn_days, p.inv_turn_days,
                                   CASE WHEN p.revenue_raw IS NOT NULL AND p.revenue_raw <> 0
                                        THEN p.net_profit_raw / p.revenue_raw END AS net_margin
                            FROM periodic_financials p
                            JOIN (
                                SELECT wind_code, MAX(period_date) AS pd
                                FROM periodic_financials WHERE period_type = 'FY'
                                GROUP BY wind_code
                            ) t ON t.wind_code = p.wind_code AND t.pd = p.period_date
                        )
        SELECT
            d.trade_date,
            d.market,
            d.wind_code,
            COALESCE(i.name, d.wind_code) AS name,
            i.board,
            COALESCE(i.sw_l1, '未分类') AS sw_l1,
            COALESCE(i.sw_l2, i.sw_l1, '未分类') AS sw_l2,
            i.ipo_date,
            d.close,
            d.volume,
            d.amount,
            d.turnover_rate,
            d.amount_1m_wind,
            COALESCE(d.amount_1m_wind / 1e8, a.amount_1m / 1e4) AS amount_1m,
            d.mkt_cap_yi / 1e8 AS mkt_cap_cny,
            d.ev_mn,
            d.ev1_mn,
            d.pe_ttm,
            d.pb AS pb_lf,
            d.div_yield,
            d.ev_ebitda,
            d.beta_24m,
            d.profit_alert,
            CASE
                WHEN y.year_start_close IS NOT NULL AND y.year_start_close > 0 AND d.close IS NOT NULL
                THEN d.close / y.year_start_close - 1
                ELSE NULL
            END AS ytd_return,
            CASE WHEN d.iw_50 IS NOT NULL AND d.iw_50 > 0 THEN 1 ELSE COALESCE(m.in_50, 0) END AS in_50,
            CASE WHEN d.iw_300 IS NOT NULL AND d.iw_300 > 0 THEN 1 ELSE COALESCE(m.in_300, 0) END AS in_300,
            CASE WHEN d.iw_500 IS NOT NULL AND d.iw_500 > 0 THEN 1 ELSE COALESCE(m.in_500, 0) END AS in_500,
            CASE WHEN d.iw_1000 IS NOT NULL AND d.iw_1000 > 0 THEN 1 ELSE COALESCE(m.in_1000, 0) END AS in_1000,
            CASE WHEN d.iw_hsi IS NOT NULL AND d.iw_hsi > 0 THEN 1 ELSE COALESCE(m.in_hsi, 0) END AS in_hsi,
            CASE WHEN d.iw_hscei IS NOT NULL AND d.iw_hscei > 0 THEN 1 ELSE COALESCE(m.in_hscei, 0) END AS in_hscei,
            CASE WHEN d.iw_hstech IS NOT NULL AND d.iw_hstech > 0 THEN 1 ELSE COALESCE(m.in_hstech, 0) END AS in_hstech,
            COALESCE(d.iw_50, m.w_50) AS w_50,
            COALESCE(d.iw_300, m.w_300) AS w_300,
            COALESCE(d.iw_500, m.w_500) AS w_500,
            COALESCE(d.iw_1000, m.w_1000) AS w_1000,
            COALESCE(d.iw_hsi, m.w_hsi) AS w_hsi,
            COALESCE(d.iw_hscei, m.w_hscei) AS w_hscei,
            COALESCE(d.iw_hstech, m.w_hstech) AS w_hstech,
            la.roe AS roe_ttm,
            roe5.roe_5y_avg,
            la.nd_to_equity,
            la.eps_actual_latest,
            fwd.fy1_eps,
            fwd.fy2_eps,
            fwd.np_avg_rev_1w,
            fwd.np_avg_rev_1m,
            fwd.np_med_rev_1w,
            fwd.np_med_rev_1m,
            lf.eps_yoy AS eps_yoy_q,
            lf.eps_yoy AS eps_yoy_acc,
            lf.net_profit_yoy,
            lf.revenue_yoy,
            lf.gross_margin,
            lf.operating_margin,
            lf.free_cashflow_raw AS fcf,
            fy.revenue_raw AS revenue,
            fy.gross_profit_raw AS gross_profit,
            fy.operating_profit_raw AS operating_profit,
            fy.pretax_profit_raw AS pretax_profit,
            fy.net_profit_raw AS net_profit_fy,
            fy.net_margin,
            fy.ar_turn_days,
            fy.inv_turn_days,
            CASE
                WHEN d.close IS NOT NULL AND d.close > 0 AND fwd.fy1_eps IS NOT NULL
                THEN fwd.fy1_eps / d.close
                ELSE NULL
            END AS fwd_ep,
            CASE
                WHEN la.eps_actual_latest IS NOT NULL AND la.eps_actual_latest > 0
                     AND fwd.fy1_eps IS NOT NULL
                THEN fwd.fy1_eps / la.eps_actual_latest - 1
                ELSE NULL
            END AS eps_fy1_growth,
            CASE
                WHEN fwd.fy1_eps IS NOT NULL AND fwd.fy1_eps > 0 AND fwd.fy2_eps IS NOT NULL
                THEN fwd.fy2_eps / fwd.fy1_eps - 1
                ELSE NULL
            END AS eps_growth,
            TRIM(
                (CASE WHEN COALESCE(d.iw_50, m.w_50, 0) > 0 THEN '000016.SH,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_300, m.w_300, 0) > 0 THEN '000300.SH,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_500, m.w_500, 0) > 0 THEN '000905.SH,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_1000, m.w_1000, 0) > 0 THEN '000852.SH,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_hsi, m.w_hsi, 0) > 0 THEN 'HSI.HI,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_hscei, m.w_hscei, 0) > 0 THEN 'HSCEI.HI,' ELSE '' END) ||
                (CASE WHEN COALESCE(d.iw_hstech, m.w_hstech, 0) > 0 THEN 'HSTECH.HI,' ELSE '' END),
                ','
            ) AS index_codes
        FROM daily_market d
        LEFT JOIN static_info i ON i.wind_code = d.wind_code
        LEFT JOIN latest_membership m ON m.wind_code = d.wind_code
        LEFT JOIN latest_actual la ON la.wind_code = d.wind_code
        LEFT JOIN roe5 ON roe5.wind_code = d.wind_code
        LEFT JOIN fwd ON fwd.wind_code = d.wind_code
        LEFT JOIN latest_fin lf ON lf.wind_code = d.wind_code
        LEFT JOIN latest_fy fy ON fy.wind_code = d.wind_code
        LEFT JOIN amount_1m a ON a.wind_code = d.wind_code
        LEFT JOIN year_start y ON y.wind_code = d.wind_code
        {where_sql}
        ORDER BY d.market, d.mkt_cap_yi DESC, d.wind_code
        """
        params: list[object] = [
            trade_date,
            trade_date,
            trade_date,
            trade_date,
            trade_date,
        ]
        params.extend(where_params)
        df = pd.read_sql(sql, conn, params=params)
        if not df.empty:
            df = _enrich_annual_growth(df, conn)
    finally:
        conn.close()

    if df.empty:
        return df
    return _normalise_numeric(df)


def _enrich_annual_growth(df: pd.DataFrame, conn: sqlite3.Connection) -> pd.DataFrame:
    """从 periodic_financials 的年报(FY)行算年度同比 + 3 年 CAGR(营收/营业利润/税前/净利)。

    新增列: rev_yoy_fy / op_yoy_fy / pretax_yoy_fy / np_yoy_fy
            rev_cagr3 / op_cagr3 / pretax_cagr3 / np_cagr3
    """
    if not _table_exists(conn, "periodic_financials"):
        return df
    fy = pd.read_sql(
        "SELECT wind_code, CAST(substr(period_date,1,4) AS INT) AS yr, "
        "       revenue_raw, operating_profit_raw, pretax_profit_raw, net_profit_raw "
        "FROM periodic_financials WHERE period_type='FY'",
        conn,
    )
    if fy.empty:
        return df

    metrics = {
        "revenue_raw": ("rev_yoy_fy", "rev_cagr3"),
        "operating_profit_raw": ("op_yoy_fy", "op_cagr3"),
        "pretax_profit_raw": ("pretax_yoy_fy", "pretax_cagr3"),
        "net_profit_raw": ("np_yoy_fy", "np_cagr3"),
    }
    out = {}
    for code, g in fy.groupby("wind_code"):
        g = g.sort_values("yr")
        years = g["yr"].tolist()
        rec = {}
        for col, (yoy_name, cagr_name) in metrics.items():
            s = dict(zip(years, pd.to_numeric(g[col], errors="coerce")))
            ly = max(years)
            cur = s.get(ly)
            prev = s.get(ly - 1)
            base3 = s.get(ly - 3)
            rec[yoy_name] = (cur / prev - 1) if (cur is not None and prev not in (None, 0)
                                                 and pd.notna(cur) and pd.notna(prev)) else None
            # 3 年 CAGR: 需同号且基期为正才有意义
            if (cur is not None and base3 not in (None, 0) and pd.notna(cur) and pd.notna(base3)
                    and base3 > 0 and cur > 0):
                rec[cagr_name] = (cur / base3) ** (1 / 3) - 1
            else:
                rec[cagr_name] = None
        out[code] = rec
    growth = pd.DataFrame.from_dict(out, orient="index")
    growth.index.name = "wind_code"
    return df.merge(growth.reset_index(), on="wind_code", how="left")


def load_v4_index_snapshot(
    db_path: Path | str = DB_PATH,
    trade_date: str | None = None,
    entity_types: tuple[str, ...] = ("index", "industry"),
    markets: tuple[str, ...] = (),
) -> pd.DataFrame:
    """读取指数/行业指数日频温度表。

    来源是 `daily_market` 中 `entity_type in ('index', 'industry')` 的数据，
    对齐旧 `template_universe_daily.xlsx` 的 close/PE/PB/股息率/FY1 EPS。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "daily_market"):
            return pd.DataFrame()

        entity_types = tuple(t for t in entity_types if t in {"index", "industry"})
        if not entity_types:
            return pd.DataFrame()

        entity_placeholders = _placeholders(entity_types)
        if trade_date is None:
            row = conn.execute(
                f"SELECT MAX(trade_date) FROM daily_market WHERE entity_type IN ({entity_placeholders})",
                entity_types,
            ).fetchone()
            trade_date = row[0] if row else None
        if not trade_date:
            return pd.DataFrame()

        where = [f"d.trade_date = ?", f"d.entity_type IN ({entity_placeholders})"]
        where_params: list[object] = [trade_date, *entity_types]

        markets = tuple(m for m in markets if m in {"A", "HK"})
        if markets:
            where.append(f"d.market IN ({_placeholders(markets)})")
            where_params.extend(markets)

        fy1_eps_expr = "d.fy1_eps" if _column_exists(conn, "daily_market", "fy1_eps") else "NULL"
        sql = f"""
        WITH year_start AS (
            SELECT d0.entity_type, d0.wind_code, d0.close AS year_start_close
            FROM daily_market d0
            JOIN (
                SELECT entity_type, wind_code, MIN(trade_date) AS first_date
                FROM daily_market
                WHERE entity_type IN ({entity_placeholders})
                  AND trade_date >= substr(?, 1, 4) || '-01-01'
                  AND trade_date <= ?
                GROUP BY entity_type, wind_code
            ) y ON y.entity_type = d0.entity_type
               AND y.wind_code = d0.wind_code
               AND y.first_date = d0.trade_date
        )
        SELECT
            d.trade_date,
            d.market,
            d.entity_type,
            d.wind_code,
            d.close,
            d.pe_ttm,
            d.pb AS pb_lf,
            d.div_yield,
            {fy1_eps_expr} AS fy1_eps,
            CASE
                WHEN y.year_start_close IS NOT NULL AND y.year_start_close > 0 AND d.close IS NOT NULL
                THEN d.close / y.year_start_close - 1
                ELSE NULL
            END AS ytd_return
        FROM daily_market d
        LEFT JOIN year_start y
          ON y.entity_type = d.entity_type AND y.wind_code = d.wind_code
        WHERE {' AND '.join(where)}
        ORDER BY d.market, d.entity_type, d.wind_code
        """
        params: list[object] = [*entity_types, trade_date, trade_date, *where_params]
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return df
    df["name"] = df["wind_code"].map(INDEX_DAILY_NAMES).fillna(df["wind_code"])
    cols = [
        "trade_date", "market", "entity_type", "wind_code", "name",
        "close", "pe_ttm", "pb_lf", "div_yield", "fy1_eps", "ytd_return",
    ]
    return _normalise_numeric(df[cols])


def available_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    """返回存在且至少有一个非空数值的列。"""
    out = []
    for col in columns:
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any():
            out.append(col)
    return out