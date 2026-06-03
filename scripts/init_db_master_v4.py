"""Frequency-first schema for the A/HK screener pipeline.

设计决议:
    1. 一个更新频率 = 一个 Wind 模板 = 一个主落库表。
    2. 严格对齐源表 `Index Future Valuation Table(Wind)` 的 4 个频率块:
        - static_info          静态 (名称/行业/上市)          template_static
        - daily_market         日频 (价量/估值/Beta/profit alert) template_daily
        - annual_fundamental   年度 (逐年 EPS 序列 + 前瞻一致预期 + ROE/ND-E)  template_annual
        - periodic_financials  财报科目 (年报FY + 半年报1H 的利润表/现金流全科目)  template_financials
        - monthly_membership   指数成员/权重 (非 Wind, 由源表 W sheets 导入)
    3. annual / quarterly 在库里是「长表/时间序列」: 一行 = 一只股 × 一个年/季。
    4. stock_info / stock_membership / stock_daily / index_constituents 仅作为兼容 view。
    5. 不再有 weekly_forecast (一致预期已并入 annual_fundamental 的前瞻年行)。

⚠️ 本脚本是「建库/重置」: 完整重建 6 张主表与兼容 view。日常数据刷新走 pull_* / import_*,
不要重复运行本脚本 (会清空已采集数据)。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DB = ROOT / "data" / "wind_history.db"

SCHEMA = """
-- ============ 清理旧表 (纯表名, 不会与 view 冲突) ============
DROP TABLE IF EXISTS stock_master;
DROP TABLE IF EXISTS zone_freshness;
DROP TABLE IF EXISTS stock_static;
DROP TABLE IF EXISTS stock_static_hk;
DROP TABLE IF EXISTS stock_daily_hk;
DROP TABLE IF EXISTS index_constituents_hk;
DROP TABLE IF EXISTS stock_monthly;
DROP TABLE IF EXISTS stock_quarterly;
DROP TABLE IF EXISTS stock_weekly_consensus;
DROP TABLE IF EXISTS stock_event;
-- init 是「建库/重置」语义: 完整重建 6 张主表 + 兼容 view, 保证与本文件 schema 一致。
-- 日常刷新走 pull_* / import_*, 不要重跑本脚本。
DROP TABLE IF EXISTS static_info;
DROP TABLE IF EXISTS monthly_membership;
DROP TABLE IF EXISTS daily_market;
DROP TABLE IF EXISTS weekly_forecast;
DROP TABLE IF EXISTS quarterly_financial;
DROP TABLE IF EXISTS annual_fundamental;
DROP TABLE IF EXISTS quarterly_fundamental;
DROP TABLE IF EXISTS periodic_financials;
-- 注: stock_info / stock_membership / stock_daily / index_constituents / v_* 这些
--     既可能是历史「表」也可能是「view」, 在 main() 里按真实类型 drop, 不放这里。

-- ============ Frequency-first base tables ============

CREATE TABLE IF NOT EXISTS static_info (
    wind_code   TEXT PRIMARY KEY,
    market      TEXT NOT NULL,            -- 'A' / 'HK'
    name        TEXT,
    board       TEXT,                     -- 兼容保留；当前采集写 NULL
    sw_l1       TEXT,
    sw_l2       TEXT,
    gics_l1     TEXT,
    ipo_date    TEXT,
    -- 兼容 v7/v8 老模块字段名
    industry_l1 TEXT,
    industry_l2 TEXT,
    list_date   TEXT,
    last_update TEXT
);
CREATE INDEX IF NOT EXISTS idx_static_market ON static_info(market);
CREATE INDEX IF NOT EXISTS idx_static_sw_l1  ON static_info(sw_l1);

CREATE TABLE IF NOT EXISTS monthly_membership (
    as_of_date  TEXT NOT NULL,
    wind_code   TEXT NOT NULL,
    market      TEXT NOT NULL,
    in_50       INTEGER DEFAULT 0,
    in_300      INTEGER DEFAULT 0,
    in_500      INTEGER DEFAULT 0,
    in_1000     INTEGER DEFAULT 0,
    in_hsi      INTEGER DEFAULT 0,
    in_hscei    INTEGER DEFAULT 0,
    in_hstech   INTEGER DEFAULT 0,
    w_50        REAL,
    w_300       REAL,
    w_500       REAL,
    w_1000      REAL,
    w_hsi       REAL,
    w_hscei     REAL,
    w_hstech    REAL,
    last_update TEXT,
    PRIMARY KEY (as_of_date, wind_code)
);
CREATE INDEX IF NOT EXISTS idx_monthly_code   ON monthly_membership(wind_code);
CREATE INDEX IF NOT EXISTS idx_monthly_market ON monthly_membership(market);

CREATE TABLE IF NOT EXISTS daily_market (
    trade_date          TEXT NOT NULL,
    entity_type         TEXT NOT NULL DEFAULT 'stock', -- stock / index / industry
    wind_code           TEXT NOT NULL,
    market              TEXT NOT NULL,
    close               REAL,
    volume              REAL,
    amount              REAL,
    turnover_rate       REAL,
    mkt_cap_yi          REAL,
    ev_mn               REAL,
    ev1_mn              REAL,
    amount_1m_wind      REAL,
    mkt_freeshares_yi   REAL,
    pe_ttm              REAL,
    pb                  REAL,
    div_yield           REAL,
    fy1_eps             REAL,
    ev_ebitda           REAL,
    beta_24m            REAL,
    profit_alert        REAL,
    ytd_return          REAL,
    iw_50               REAL,
    iw_300              REAL,
    iw_500              REAL,
    iw_1000             REAL,
    iw_hsi              REAL,
    iw_hscei            REAL,
    iw_hstech           REAL,
    last_update         TEXT,
    PRIMARY KEY (trade_date, entity_type, wind_code)
);
CREATE INDEX IF NOT EXISTS idx_daily_market_date ON daily_market(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_market_type ON daily_market(entity_type, market);
CREATE INDEX IF NOT EXISTS idx_daily_market_code ON daily_market(wind_code);

CREATE TABLE IF NOT EXISTS annual_fundamental (
    wind_code           TEXT NOT NULL,
    fiscal_year         INTEGER NOT NULL,     -- 财年 (e.g. 2025)
    report_date         TEXT,                 -- 财年年末 yyyy-mm-dd
    market              TEXT NOT NULL,        -- 'A' / 'HK'
    eps                 REAL,                 -- 每股收益 (实际或一致预期; 净利/股本, 无量纲)
    is_estimate         INTEGER DEFAULT 0,    -- 0=实际(s_stm07_is) 1=一致预期(s_west)
    -- 以下为 Wind 原值 (ODS, 未做单位换算; 清洗放看板)
    net_profit_raw      REAL,                 -- 归母净利 (元, 最近实际财年)
    roe                 REAL,                 -- 杜邦 ROE (小数, 每个实际财年都填 → 看板算 5 年均)
    equity_raw          REAL,                 -- 净资产 (元)
    net_debt_raw        REAL,                 -- 净负债 (元)
    nd_to_equity        REAL,                 -- 净负债率 (派生比值)
    ev1_raw             REAL,                 -- EV1 (元, 财年口径)
    ebitda_raw          REAL,                 -- EBITDA (元, 财年口径)
    ev_to_ebitda        REAL,                 -- EV/EBITDA (派生比值)
    np_avg_rev_1w       REAL,                 -- FY1 一致预期均值净利 周修正 (挂前瞻首年行)
    np_avg_rev_1m       REAL,                 -- FY1 一致预期均值净利 月修正
    np_med_rev_1w       REAL,                 -- FY1 一致预期中值净利 周修正
    np_med_rev_1m       REAL,                 -- FY1 一致预期中值净利 月修正
    last_update         TEXT,
    PRIMARY KEY (wind_code, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_annual_code ON annual_fundamental(wind_code);
CREATE INDEX IF NOT EXISTS idx_annual_year ON annual_fundamental(fiscal_year);

CREATE TABLE IF NOT EXISTS periodic_financials (
    wind_code                   TEXT NOT NULL,
    period_date                 TEXT NOT NULL,   -- 报告期末 yyyy-mm-dd
    period_type                 TEXT,            -- FY(年报12-31) / 1H(半年报06-30) / Q1 / Q3
    market                      TEXT NOT NULL,
    -- 利润表 (累计至报告期末, Wind 原值 元, 未换算)
    revenue_raw                 REAL,
    cogs_raw                    REAL,
    gross_profit_raw            REAL,
    gross_margin                REAL,            -- 派生比值
    selling_exp_raw             REAL,
    admin_exp_raw               REAL,
    rd_exp_raw                  REAL,
    operating_profit_raw        REAL,
    operating_margin            REAL,            -- 派生比值
    interest_expense_raw        REAL,
    interest_income_raw         REAL,
    net_interest_expense_raw    REAL,
    pretax_profit_raw           REAL,
    non_operating_income_raw    REAL,
    net_profit_raw              REAL,            -- 归母净利
    -- 现金流 (元)
    operating_cashflow_raw      REAL,
    capex_raw                   REAL,
    free_cashflow_raw           REAL,
    -- 每股 (无量纲)
    basic_eps                   REAL,
    -- 营运周转天数 (天; A 股 s_fa_*turndays / 港股 hks_fa_*turndays, 金融股不适用)
    ar_turn_days                REAL,            -- 应收账款周转天数
    ap_turn_days                REAL,            -- 应付账款周转天数
    inv_turn_days               REAL,            -- 存货周转天数
    -- 同比 (vs 去年同报告期, 派生比值)
    revenue_yoy                 REAL,
    net_profit_yoy              REAL,
    eps_yoy                     REAL,
    last_update                 TEXT,
    PRIMARY KEY (wind_code, period_date)
);
CREATE INDEX IF NOT EXISTS idx_periodic_code ON periodic_financials(wind_code);
CREATE INDEX IF NOT EXISTS idx_periodic_type ON periodic_financials(period_type);

-- 5. pipeline_freshness —— 各任务最近一次运行状态
CREATE TABLE IF NOT EXISTS pipeline_freshness (
    dataset     TEXT PRIMARY KEY,         -- static_info / monthly_membership / daily_market / annual_fundamental / periodic_financials
    last_run    TEXT,                     -- ISO datetime
    status      TEXT,                     -- 'ok' / 'fail' / 'partial'
    rows        INTEGER,
    notes       TEXT
);

-- ============ Compatibility views for old V4 names ============

CREATE VIEW stock_info AS
SELECT wind_code, market, name, board, sw_l1, sw_l2, ipo_date, last_update
FROM static_info;

CREATE VIEW stock_membership AS
SELECT m.wind_code, m.market,
       m.in_50, m.in_300, m.in_500, m.in_1000,
       m.in_hsi, m.in_hscei, m.in_hstech,
       m.last_update
FROM monthly_membership m
JOIN (
    SELECT wind_code, MAX(as_of_date) AS as_of_date
    FROM monthly_membership
    GROUP BY wind_code
) latest ON latest.wind_code = m.wind_code AND latest.as_of_date = m.as_of_date;

CREATE VIEW stock_daily AS
SELECT d.wind_code, d.trade_date, d.market,
    d.close, d.amount, d.amount_1m_wind, d.mkt_cap_yi, d.ev_mn, d.ev1_mn,
    d.pe_ttm, d.pb, d.div_yield, d.fy1_eps,
    d.ev_ebitda, d.beta_24m, d.profit_alert, d.ytd_return,
       COALESCE(d.iw_50, m.w_50) AS w_50,
       COALESCE(d.iw_300, m.w_300) AS w_300,
       COALESCE(d.iw_500, m.w_500) AS w_500,
       COALESCE(d.iw_1000, m.w_1000) AS w_1000,
       COALESCE(d.iw_hsi, m.w_hsi) AS w_hsi,
       COALESCE(d.iw_hscei, m.w_hscei) AS w_hscei,
       COALESCE(d.iw_hstech, m.w_hstech) AS w_hstech
FROM daily_market d
LEFT JOIN monthly_membership m
  ON m.wind_code = d.wind_code
 AND m.as_of_date = (
    SELECT MAX(mm.as_of_date)
    FROM monthly_membership mm
    WHERE mm.wind_code = d.wind_code AND mm.as_of_date <= d.trade_date
 )
WHERE d.entity_type = 'stock';

CREATE VIEW index_constituents AS
SELECT as_of_date AS effective_date, market, '000016.SH' AS index_code, wind_code, NULL AS sec_name, w_50 AS weight
FROM monthly_membership WHERE COALESCE(in_50, 0) = 1
UNION ALL
SELECT as_of_date, market, '000300.SH', wind_code, NULL, w_300
FROM monthly_membership WHERE COALESCE(in_300, 0) = 1
UNION ALL
SELECT as_of_date, market, '000905.SH', wind_code, NULL, w_500
FROM monthly_membership WHERE COALESCE(in_500, 0) = 1
UNION ALL
SELECT as_of_date, market, '000852.SH', wind_code, NULL, w_1000
FROM monthly_membership WHERE COALESCE(in_1000, 0) = 1
UNION ALL
SELECT as_of_date, market, 'HSI.HI', wind_code, NULL, w_hsi
FROM monthly_membership WHERE COALESCE(in_hsi, 0) = 1
UNION ALL
SELECT as_of_date, market, 'HSCEI.HI', wind_code, NULL, w_hscei
FROM monthly_membership WHERE COALESCE(in_hscei, 0) = 1
UNION ALL
SELECT as_of_date, market, 'HSTECH.HI', wind_code, NULL, w_hstech
FROM monthly_membership WHERE COALESCE(in_hstech, 0) = 1;
"""


def _drop_ambiguous(conn: sqlite3.Connection) -> None:
    """这些名字历史上可能是表也可能是 view, 按 sqlite_master 的真实类型 drop。"""
    names = [
        "stock_info", "stock_membership", "stock_daily", "index_constituents",
        "v_stock_snapshot", "v_index_dashboard",
    ]
    for name in names:
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name=? AND type IN ('table','view')",
            (name,),
        ).fetchone()
        if row:
            conn.execute(f"DROP {row[0].upper()} IF EXISTS {name}")


def main():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    _drop_ambiguous(conn)
    conn.executescript(SCHEMA)
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"✅ schema v4 deployed at {DB}")
    print(f"   tables ({len(tables)}): {', '.join(tables)}")

    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
        print(f"     - {t:30s}  rows={n}")
    conn.close()


if __name__ == "__main__":
    main()
