"""中央列字典 —— 一处定义中文名/格式/口径, 全看板的表格与图表统一从这里取。

治本: 数据库英文列名(roe_ttm / eps_fy1_growth / ar_turn_days …)不再裸露给用户。
用法:
    disp = humanize_df(df, cols)              # 单位换算(元→亿)后的展示用 DataFrame
    st.dataframe(disp[cols], column_config=build_column_config(cols))
    label_of("roe_ttm")  -> "ROE"
"""
from __future__ import annotations

import streamlit as st

YI = 1e8  # 元 → 亿

# col: (中文label, kind, help)
# kind: text / pct / yi_raw(元→亿) / yi(已是亿) / mult(倍) / price / days / score / int
COLUMN_META: dict[str, tuple[str, str, str]] = {
    # 身份
    "sw_l1": ("行业", "text", "申万一级行业"),
    "sw_l2": ("子行业", "text", "申万二级行业"),
    "wind_code": ("代码", "text", "Wind 代码"),
    "name": ("名称", "text", ""),
    "market": ("市场", "text", "A 股 / 港股"),
    "entity_type": ("类型", "text", ""),
    "trade_date": ("日期", "text", "快照交易日"),
    "close": ("股价", "price", "最新收盘价"),
    # 市值 / 流动性 / 风险
    "mkt_cap_cny": ("总市值", "yi", "人民币(亿)"),
    "amount_1m": ("月成交额", "yi", "近一月成交额(亿)"),
    "beta_24m": ("Beta", "mult", "24 月 Beta"),
    "profit_alert": ("业绩预告", "pct", "业绩预告变动幅度"),
    "ytd_return": ("YTD涨幅", "pct", "年初至今股价涨跌"),
    # 估值
    "pe_ttm": ("PE", "mult", "市盈率 TTM"),
    "sector_pe": ("行业PE", "mult", "所在行业中位 PE"),
    "pb_lf": ("PB", "mult", "市净率"),
    "ev_ebitda": ("EV/EBITDA", "mult", ""),
    "div_yield": ("股息率", "pct", ""),
    # 年度 / 一致预期
    "roe_ttm": ("ROE", "pct", "最新财年杜邦 ROE"),
    "roe_5y_avg": ("5年均ROE", "pct", "近 5 个财年 ROE 均值"),
    "nd_to_equity": ("净负债率", "pct", "净负债 / 净资产, <0 为净现金"),
    "fy1_eps": ("预期EPS(今年)", "price", "FY1 一致预期 EPS"),
    "fy2_eps": ("预期EPS(明年)", "price", "FY2 一致预期 EPS"),
    "eps_fy1_growth": ("当年EPS增速", "pct", "FY1 预期 EPS / 最新实际 EPS - 1"),
    "eps_growth": ("次年EPS增速", "pct", "FY2 / FY1 - 1"),
    "fwd_ep": ("前瞻E/P", "pct", "FY1 EPS / 股价"),
    "np_avg_rev_1w": ("均值预期·周修正", "pct", "FY1 一致预期(均值)净利 7 日变动"),
    "np_avg_rev_1m": ("均值预期·月修正", "pct", "FY1 一致预期(均值)净利 30 日变动"),
    "np_med_rev_1w": ("中值预期·周修正", "pct", "FY1 一致预期(中值)净利 7 日变动"),
    "np_med_rev_1m": ("中值预期·月修正", "pct", "FY1 一致预期(中值)净利 30 日变动"),
    # 经营 (财报)
    "revenue": ("营收", "yi_raw", "最新年报营业收入(亿)"),
    "gross_profit": ("毛利", "yi_raw", "营收 - 营业成本(亿)"),
    "operating_profit": ("营业利润", "yi_raw", "(亿)"),
    "pretax_profit": ("税前利润", "yi_raw", "(亿)"),
    "net_profit_fy": ("归母净利", "yi_raw", "最新年报(亿)"),
    "gross_margin": ("毛利率", "pct", ""),
    "operating_margin": ("营业利润率", "pct", ""),
    "net_margin": ("净利率", "pct", ""),
    "eps_yoy_q": ("单季EPS同比", "pct", "最新报告期 EPS 同比"),
    "eps_yoy_acc": ("累计EPS同比", "pct", "累计 EPS 同比"),
    "revenue_yoy": ("营收同比", "pct", "最新报告期营收同比"),
    "net_profit_yoy": ("净利同比", "pct", ""),
    "rev_yoy_fy": ("营收同比(年)", "pct", "年报营收同比"),
    "op_yoy_fy": ("营业利润同比(年)", "pct", ""),
    "np_yoy_fy": ("净利同比(年)", "pct", ""),
    "rev_cagr3": ("营收3年CAGR", "pct", "近 3 年营收复合增速"),
    "op_cagr3": ("营业利润3年CAGR", "pct", ""),
    "pretax_cagr3": ("税前3年CAGR", "pct", ""),
    "np_cagr3": ("净利3年CAGR", "pct", "近 3 年净利复合增速"),
    "ar_turn_days": ("应收周转", "days", "应收账款周转天数(越低越好)"),
    "inv_turn_days": ("存货周转", "days", "存货周转天数(越低越好)"),
    "fcf": ("自由现金流", "yi_raw", "经营现金流 - Capex(亿)"),
    # 复合分
    "score_composite": ("复合分", "score", "行业内 4 维度加权分位(0-100)"),
    "score_quality": ("质量分", "score", "ROE/利润率"),
    "score_growth": ("成长分", "score", "EPS 增速/CAGR"),
    "score_valuation": ("估值分", "score", "PE/PB/EV-EBITDA, 越高越便宜"),
    "score_cash": ("现金分", "score", "FCF/股息"),
    "sector_rank": ("行业排名", "int", "行业内复合分名次"),
    "pass_all": ("入选", "text", "三块规则全过"),
}

_YI_RAW = {c for c, (_, k, _) in COLUMN_META.items() if k == "yi_raw"}

# 规则布尔列 → 中文名(漏斗图用)
RULE_LABELS = {
    "r_eps_fy1_growth": "当年EPS增速", "r_roe_ttm": "ROE", "r_pe_lt_sector": "PE<行业",
    "r_div_yield": "股息率", "r_nd_to_equity": "ND/E<0", "r_eps_yoy_q": "季EPS增速",
    "r_eps_yoy_acc": "累计EPS增速", "r_ytd_lt_eps_acc": "YTD<增速", "r_sector_top_n": "市值TopN",
    "o_rev_top": "营收TopN", "o_op_profit_top": "营业利润TopN", "o_gross_margin_top": "毛利率TopN",
    "o_op_margin_top": "营业利润率TopN", "o_ar_days_low": "应收天数低", "o_inv_days_low": "存货天数低",
    "o_roe_5y": "5年均ROE", "o_rev_cagr3": "营收CAGR", "o_np_cagr3": "净利CAGR",
    "o_nd_to_equity": "ND/E<0(经营)",
    "c_avg_1w": "均值周修正", "c_avg_1m": "均值月修正", "c_med_1w": "中值周修正",
    "c_med_1m": "中值月修正", "c_acc_gt_fwd": "累计>预期",
}


def label_of(col: str) -> str:
    return COLUMN_META.get(col, (col, "", ""))[0]


def humanize_df(df, cols=None):
    """返回展示用副本: 元→亿 的列除以 1e8(其余不动; pct 保留小数, 由 column_config 显示为 %)。"""
    out = df.copy()
    target = (set(cols) & _YI_RAW) if cols else _YI_RAW
    for c in target:
        if c in out.columns:
            out[c] = out[c] / YI
    return out


def build_column_config(cols) -> dict:
    """按列字典生成 st.column_config(中文 label + help + 正确 format)。"""
    cfg = {}
    for c in cols:
        meta = COLUMN_META.get(c)
        if not meta:
            continue
        label, kind, help_ = meta
        h = help_ or None
        if kind == "text":
            cfg[c] = st.column_config.TextColumn(label, help=h)
        elif kind == "pct":
            cfg[c] = st.column_config.NumberColumn(label, help=h, format="percent")
        elif kind in ("yi_raw", "yi"):
            cfg[c] = st.column_config.NumberColumn(f"{label}(亿)", help=h, format="%.1f")
        elif kind == "mult":
            cfg[c] = st.column_config.NumberColumn(label, help=h, format="%.1f")
        elif kind == "price":
            cfg[c] = st.column_config.NumberColumn(label, help=h, format="%.2f")
        elif kind == "days":
            cfg[c] = st.column_config.NumberColumn(label, help=h, format="%.0f 天")
        elif kind == "score":
            cfg[c] = st.column_config.ProgressColumn(label, help=h, min_value=0, max_value=100, format="%.0f")
        elif kind == "int":
            cfg[c] = st.column_config.NumberColumn(label, help=h, format="%d")
    return cfg
