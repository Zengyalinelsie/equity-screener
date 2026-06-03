"""选股池核心引擎 —— 纯函数，不依赖数据库/Wind。

设计原则:
    - 输入：一张"快照宽表" DataFrame（一行一只股，列见 INPUT_SCHEMA）
    - 输出：原表 + 一系列规则通过列 + 4 维度分 + 复合分
    - 3 套规则并行：analyst_13（她那套） / wind_5（原表升级版） / my_4dim（复合分）
    - 不修改输入；缺数据视为"不通过"（保守）

INPUT_SCHEMA（输入 DataFrame 必备列；可缺，缺则对应规则跳过/视为 False）:
    wind_code, name, sw_l1, mkt_cap_cny, amount_1m, beta_24m,
    pe_ttm, pe_25e, pb_lf, ev_ebitda, div_yield, ytd_return,
    roe_ttm, eps_yoy_q, eps_yoy_acc, nd_to_equity, fcf, goodwill_to_equity,
    eps_fy1_growth, eps_revision_1m, profit_alert
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

import numpy as np
import pandas as pd

# =============================================================
# 默认配置
# =============================================================

@dataclass
class AnalystRules:
    """她那 13 条规则的默认值（与本仓库讨论一致）。"""
    sector_top_n: int | None = 2                  # 行业内市值 Top N（None=不启用）
    eps_fy1_growth_min: float | None = 0.20       # 当年 EPS 增速 > 20%
    roe_ttm_min: float | None = 0.08              # ROE TTM > 8%
    pe_vs_sector: bool = True                     # PE < 行业中位 PE
    div_yield_min: float | None = 0.0             # 股息率 > 0%
    nd_to_equity_max: float | None = None         # ND/E < 0%（默认关闭！）
    eps_yoy_q_min: float | None = 0.05            # 最新季 EPS 同比 > 5%
    eps_yoy_acc_min: float | None = 0.20          # 累计 EPS 同比 > 20%
    ytd_lt_eps_acc: bool = True                   # YTD 涨幅 < 累计 EPS 增速（反透支）


@dataclass
class Wind5Rules:
    """原 Wind 表那个 IF(AND(...)) 公式的"升级版"（FCF 替换 Capex）。"""
    roe_min: float | None = 0.10                  # ROE > 10%
    pe_max: float | None = 40                     # PE < 40
    div_yield_min: float | None = 0.01            # 股息率 > 1%
    bs_gt_bv: bool = True                         # 累计 EPS 增速 > YTD 涨幅
    fcf_positive: bool = True                     # FCF > 0（原表 ES>0 是 Capex 非空，无意义）


@dataclass
class OperationalRules:
    """经营 comp（指令集第 2 块，行业内排名 + 绝对阈值）。"""
    rev_top_n: int | None = None              # 营收 行业 Top N（指令集 Top2）
    op_profit_top_n: int | None = None        # 营业利润 行业 Top N（Top5）
    gross_margin_top_n: int | None = None     # 毛利率 行业 Top N（top3）
    op_margin_top_n: int | None = None        # 营业利润率 行业 Top N（top3）
    ar_days_lowest_pct: float | None = None   # 应收天数 行业最低 X%（25）
    inv_days_lowest_pct: float | None = None  # 存货天数 行业最低 X%（25）
    roe_5y_min: float | None = 0.08           # 5 年平均 ROE > 8%
    rev_cagr3_min: float | None = None        # 营收 3 年 CAGR ≥
    np_cagr3_min: float | None = None         # 净利 3 年 CAGR ≥
    nd_to_equity_max: float | None = None     # ND/E < 0（默认关）


@dataclass
class ConsensusRules:
    """一致预期 TP（指令集第 3 块，修正向上）。"""
    avg_rev_1w_up: bool = False               # 一致预期均值净利 周修正 > 0
    avg_rev_1m_up: bool = False               # 月修正 > 0
    med_rev_1w_up: bool = False               # 中值 周修正 > 0
    med_rev_1m_up: bool = False               # 月修正 > 0
    acc_gt_fwd: bool = False                  # 累计 EPS 增速 > 预期净利增速


@dataclass
class Weights4Dim:
    """4 维度复合分权重（默认 0.30/0.25/0.25/0.20）。"""
    quality: float = 0.30
    growth: float = 0.25
    valuation: float = 0.25
    cash: float = 0.20


@dataclass
class RedLines:
    """一票否决（任一触发直接出局）。"""
    min_mkt_cap_cny: float | None = 50            # 总市值 >= 50 亿
    max_goodwill_to_equity: float | None = 0.50   # 商誉/净资产 < 50%
    profit_alert_floor: float | None = -0.30      # 业绩预告变动 > -30%
    require_positive_eps_acc: bool = False        # 累计净利润 > 0（默认关）

    def all_disabled(self) -> bool:
        return all(v is None or v is False for v in asdict(self).values())


@dataclass
class ScreenerConfig:
    analyst: AnalystRules = field(default_factory=AnalystRules)
    operational: OperationalRules = field(default_factory=OperationalRules)
    consensus: ConsensusRules = field(default_factory=ConsensusRules)
    wind5: Wind5Rules = field(default_factory=Wind5Rules)
    weights: Weights4Dim = field(default_factory=Weights4Dim)
    red_lines: RedLines = field(default_factory=RedLines)
    sector_pe_method: Literal["median", "weighted"] = "median"
    universe: str | None = None    # 可选：'000300.SH' 等，由外部过滤后再喂进来


# =============================================================
# 工具：行业中位 PE
# =============================================================

def compute_sector_pe(
    df: pd.DataFrame,
    method: Literal["median", "weighted"] = "median",
    pe_col: str = "pe_ttm",
    sector_col: str = "sw_l1",
    weight_col: str = "mkt_cap_cny",
    winsor: tuple[float, float] = (0.05, 0.95),
) -> pd.Series:
    """每个 sw_l1 行业的代表性 PE。剔除 <=0 和 winsor 极值，保护中位数/均值。

    返回: index=sw_l1, value=sector_pe。
    """
    if pe_col not in df.columns or sector_col not in df.columns:
        return pd.Series(dtype=float)

    work = df[[sector_col, pe_col, weight_col]].copy() if weight_col in df.columns \
        else df[[sector_col, pe_col]].copy()
    work[pe_col] = pd.to_numeric(work[pe_col], errors="coerce")
    work = work[work[pe_col] > 0].dropna(subset=[sector_col, pe_col])

    def _one_sector(g: pd.DataFrame) -> float:
        s = g[pe_col]
        if len(s) >= 4:
            lo, hi = s.quantile(winsor[0]), s.quantile(winsor[1])
            s = s[(s >= lo) & (s <= hi)]
        if s.empty:
            return np.nan
        if method == "weighted" and weight_col in g.columns:
            w = pd.to_numeric(g.loc[s.index, weight_col], errors="coerce").fillna(0)
            return float((s * w).sum() / w.sum()) if w.sum() > 0 else float(s.median())
        return float(s.median())

    value_cols = [pe_col] + ([weight_col] if weight_col in work.columns else [])
    return work.groupby(sector_col, dropna=True)[value_cols].apply(_one_sector).rename("sector_pe")


# =============================================================
# 工具：行业内 Top N（按市值）
# =============================================================

def mark_sector_top_n(
    df: pd.DataFrame,
    n: int = 2,
    sector_col: str = "sw_l1",
    mkt_cap_col: str = "mkt_cap_cny",
) -> pd.Series:
    """返回布尔 Series（与 df 索引对齐），True = 在所在行业市值前 N 名内。"""
    if sector_col not in df.columns or mkt_cap_col not in df.columns:
        return pd.Series(False, index=df.index)
    mk = pd.to_numeric(df[mkt_cap_col], errors="coerce")
    rank = mk.groupby(df[sector_col]).rank(method="dense", ascending=False)
    return (rank <= n).fillna(False)


def mark_sector_lowest_pct(
    df: pd.DataFrame,
    pct: float,
    value_col: str,
    sector_col: str = "sw_l1",
) -> pd.Series:
    """行业内最低 pct%（如 25 = 最低四分之一）。NaN 视为不通过。"""
    if sector_col not in df.columns or value_col not in df.columns:
        return pd.Series(False, index=df.index)
    v = pd.to_numeric(df[value_col], errors="coerce")
    rk = v.groupby(df[sector_col]).rank(pct=True, ascending=True, na_option="keep")
    return (rk <= pct / 100.0).fillna(False)


def apply_operational_rules(df: pd.DataFrame, cfg: OperationalRules) -> pd.DataFrame:
    """经营 comp（指令集第 2 块）。行业内 Top N / 最低 X% + 绝对阈值。"""
    out = df.copy()
    flags: dict[str, pd.Series] = {}

    def _topn(col, n, name):
        if n is not None and col in out.columns and pd.to_numeric(out[col], errors="coerce").notna().any():
            flags[name] = mark_sector_top_n(out, n=n, mkt_cap_col=col)

    def _lowest(col, pct, name):
        if pct is not None and col in out.columns and pd.to_numeric(out[col], errors="coerce").notna().any():
            flags[name] = mark_sector_lowest_pct(out, pct=pct, value_col=col)

    def _ge(col, thr, name):
        if thr is not None and col in out.columns:
            v = pd.to_numeric(out[col], errors="coerce")
            if v.notna().any():
                flags[name] = (v >= thr).fillna(False)

    def _le(col, thr, name):
        if thr is not None and col in out.columns:
            v = pd.to_numeric(out[col], errors="coerce")
            if v.notna().any():
                flags[name] = (v <= thr).fillna(False)

    _topn("revenue", cfg.rev_top_n, "o_rev_top")
    _topn("operating_profit", cfg.op_profit_top_n, "o_op_profit_top")
    _topn("gross_margin", cfg.gross_margin_top_n, "o_gross_margin_top")
    _topn("operating_margin", cfg.op_margin_top_n, "o_op_margin_top")
    _lowest("ar_turn_days", cfg.ar_days_lowest_pct, "o_ar_days_low")
    _lowest("inv_turn_days", cfg.inv_days_lowest_pct, "o_inv_days_low")
    _ge("roe_5y_avg", cfg.roe_5y_min, "o_roe_5y")
    _ge("rev_cagr3", cfg.rev_cagr3_min, "o_rev_cagr3")
    _ge("np_cagr3", cfg.np_cagr3_min, "o_np_cagr3")
    _le("nd_to_equity", cfg.nd_to_equity_max, "o_nd_to_equity")

    for k, v in flags.items():
        out[k] = v
    out["pass_operational"] = (
        pd.concat(flags.values(), axis=1).all(axis=1) if flags else True
    )
    return out


def apply_consensus_rules(df: pd.DataFrame, cfg: ConsensusRules) -> pd.DataFrame:
    """一致预期 TP（指令集第 3 块）。修正向上 / 累计实绩 > 预期。"""
    out = df.copy()
    flags: dict[str, pd.Series] = {}

    def _up(col, on, name):
        if on and col in out.columns:
            v = pd.to_numeric(out[col], errors="coerce")
            if v.notna().any():
                flags[name] = (v > 0).fillna(False)

    _up("np_avg_rev_1w", cfg.avg_rev_1w_up, "c_avg_1w")
    _up("np_avg_rev_1m", cfg.avg_rev_1m_up, "c_avg_1m")
    _up("np_med_rev_1w", cfg.med_rev_1w_up, "c_med_1w")
    _up("np_med_rev_1m", cfg.med_rev_1m_up, "c_med_1m")

    if cfg.acc_gt_fwd and "eps_yoy_acc" in out.columns and "eps_fy1_growth" in out.columns:
        acc = pd.to_numeric(out["eps_yoy_acc"], errors="coerce")
        fwd = pd.to_numeric(out["eps_fy1_growth"], errors="coerce")
        if acc.notna().any() and fwd.notna().any():
            flags["c_acc_gt_fwd"] = (acc > fwd).fillna(False)

    for k, v in flags.items():
        out[k] = v
    out["pass_consensus"] = (
        pd.concat(flags.values(), axis=1).all(axis=1) if flags else True
    )
    return out


# =============================================================
# 规则集 1：analyst_13（她那套）
# =============================================================

def apply_analyst_rules(df: pd.DataFrame, cfg: AnalystRules,
                        sector_pe: pd.Series | None = None) -> pd.DataFrame:
    """逐条评估 13 条规则，返回 df + r_xxx 各布尔列 + pass_analyst（全 True）。"""
    out = df.copy()
    flags: dict[str, pd.Series] = {}

    def _ge(col: str, thr: float | None) -> pd.Series | None:
        if thr is None or col not in out.columns:
            return None
        vals = pd.to_numeric(out[col], errors="coerce")
        if not vals.notna().any():
            return None
        return vals >= thr

    def _le(col: str, thr: float | None) -> pd.Series | None:
        if thr is None or col not in out.columns:
            return None
        vals = pd.to_numeric(out[col], errors="coerce")
        if not vals.notna().any():
            return None
        return vals <= thr

    # 1 行业 Top N（不参与 pass 投票，单独标列，让用户决定是否当 filter）
    if cfg.sector_top_n is not None:
        out["r_sector_top_n"] = mark_sector_top_n(out, n=cfg.sector_top_n)

    # 2 当年 EPS 增速 > 20%
    f = _ge("eps_fy1_growth", cfg.eps_fy1_growth_min)
    if f is not None: flags["r_eps_fy1_growth"] = f.fillna(False)

    # 3 ROE > 8%
    f = _ge("roe_ttm", cfg.roe_ttm_min)
    if f is not None: flags["r_roe_ttm"] = f.fillna(False)

    # 4 PE < 行业中位 PE
    if cfg.pe_vs_sector and "pe_ttm" in out.columns and "sw_l1" in out.columns:
        if sector_pe is None:
            sector_pe = compute_sector_pe(out)
        my_sec_pe = out["sw_l1"].map(sector_pe)
        pe = pd.to_numeric(out["pe_ttm"], errors="coerce")
        if pe.notna().any() and my_sec_pe.notna().any():
            flags["r_pe_lt_sector"] = ((pe > 0) & (pe < my_sec_pe)).fillna(False)
            out["sector_pe"] = my_sec_pe

    # 5 股息率 > 0
    f = _ge("div_yield", cfg.div_yield_min)
    if f is not None: flags["r_div_yield"] = f.fillna(False)

    # 6 ND/E < 0（默认关闭）
    f = _le("nd_to_equity", cfg.nd_to_equity_max)
    if f is not None: flags["r_nd_to_equity"] = f.fillna(False)

    # 7 最新季 EPS 同比 > 5%
    f = _ge("eps_yoy_q", cfg.eps_yoy_q_min)
    if f is not None: flags["r_eps_yoy_q"] = f.fillna(False)

    # 8 累计 EPS 同比 > 20%
    f = _ge("eps_yoy_acc", cfg.eps_yoy_acc_min)
    if f is not None: flags["r_eps_yoy_acc"] = f.fillna(False)

    # 9 YTD 涨幅 < 累计 EPS 增速
    if cfg.ytd_lt_eps_acc and "ytd_return" in out.columns and "eps_yoy_acc" in out.columns:
        ytd = pd.to_numeric(out["ytd_return"], errors="coerce")
        acc = pd.to_numeric(out["eps_yoy_acc"], errors="coerce")
        if ytd.notna().any() and acc.notna().any():
            flags["r_ytd_lt_eps_acc"] = (ytd < acc).fillna(False)
            out["ytd_minus_eps_acc"] = ytd - acc      # 派生展示列（越负越"被低估"）

    for k, v in flags.items():
        out[k] = v

    # 综合 pass：所有已启用规则全 True（行业 Top N 不计入 pass）
    if flags:
        pass_all = pd.concat(flags.values(), axis=1).all(axis=1)
        out["pass_analyst"] = pass_all
    else:
        out["pass_analyst"] = False

    return out


# =============================================================
# 规则集 2：wind_5（原 Wind 公式升级版）
# =============================================================

def apply_wind5_rules(df: pd.DataFrame, cfg: Wind5Rules) -> pd.DataFrame:
    """原 Wind 表 IF(AND(ROE>10%, PE<40, DivY>1%, BS>BV, ES>0)) 的升级实现。
    ES>0 (Capex 非空) 没意义，替换为 FCF>0。
    """
    out = df.copy()
    flags = {}

    def _num(col):
        if col not in out.columns:
            return None
        vals = pd.to_numeric(out[col], errors="coerce")
        return vals if vals.notna().any() else None

    roe = _num("roe_ttm")
    if cfg.roe_min is not None and roe is not None:
        flags["w_roe"] = (roe >= cfg.roe_min).fillna(False)

    pe = _num("pe_ttm")
    if cfg.pe_max is not None and pe is not None:
        flags["w_pe"] = ((pe > 0) & (pe < cfg.pe_max)).fillna(False)

    dy = _num("div_yield")
    if cfg.div_yield_min is not None and dy is not None:
        flags["w_div_yield"] = (dy >= cfg.div_yield_min).fillna(False)

    if cfg.bs_gt_bv:
        ytd = _num("ytd_return"); acc = _num("eps_yoy_acc")
        if ytd is not None and acc is not None:
            flags["w_bs_gt_bv"] = (acc > ytd).fillna(False)

    if cfg.fcf_positive:
        fcf = _num("fcf")
        if fcf is not None:
            flags["w_fcf_positive"] = (fcf > 0).fillna(False)

    for k, v in flags.items():
        out[k] = v

    out["pass_wind5"] = pd.concat(flags.values(), axis=1).all(axis=1) if flags else False
    return out


# =============================================================
# 规则集 3：my_4dim 复合分（行业内分位）
# =============================================================

_QUALITY_COLS = ["roe_ttm", "roe_5y_avg", "net_margin", "operating_margin"]   # 质量
_GROWTH_COLS  = ["eps_fy1_growth", "eps_yoy_acc", "rev_cagr3", "np_cagr3"]    # 成长(一致预期+实绩+CAGR)
_VAL_COLS_INV = ["pe_ttm", "pb_lf", "ev_ebitda"]        # 越小越好 → 反向
_CASH_COLS    = ["fcf", "div_yield"]                    # 越大越好；ND/E 越低越好但单位敏感先不加


def _percentile_within_sector(s: pd.Series, sector: pd.Series, higher_better: bool) -> pd.Series:
    """行业内分位 0-100。NaN 不参与排名，赋 NaN。"""
    s = pd.to_numeric(s, errors="coerce")
    rk = s.groupby(sector).rank(pct=True, na_option="keep")
    score = rk * 100
    if not higher_better:
        score = 100 - score
    return score


def score_4dim(df: pd.DataFrame, weights: Weights4Dim) -> pd.DataFrame:
    """对每只股票打 4 维分 + 复合分。所有分数都是"行业内 0-100 分位"。"""
    out = df.copy()
    if "sw_l1" not in out.columns:
        out["sw_l1"] = "未分类"
    sec = out["sw_l1"]

    def _avg_of(cols, higher_better):
        present = [c for c in cols if c in out.columns]
        if not present:
            return pd.Series(np.nan, index=out.index)
        parts = [_percentile_within_sector(out[c], sec, higher_better) for c in present]
        return pd.concat(parts, axis=1).mean(axis=1, skipna=True)

    out["score_quality"]   = _avg_of(_QUALITY_COLS,  higher_better=True)
    out["score_growth"]    = _avg_of(_GROWTH_COLS,   higher_better=True)
    out["score_valuation"] = _avg_of(_VAL_COLS_INV,  higher_better=False)
    out["score_cash"]      = _avg_of(_CASH_COLS,     higher_better=True)

    w = weights
    out["score_composite"] = (
        out["score_quality"].fillna(50)   * w.quality +
        out["score_growth"].fillna(50)    * w.growth +
        out["score_valuation"].fillna(50) * w.valuation +
        out["score_cash"].fillna(50)      * w.cash
    )
    # 行业内复合分排名（1 最好）
    out["sector_rank"] = (
        out.groupby("sw_l1")["score_composite"]
           .rank(method="dense", ascending=False).astype("Int64")
    )
    return out


# =============================================================
# 红线一票否决
# =============================================================

def apply_red_lines(df: pd.DataFrame, cfg: RedLines) -> pd.Series:
    """返回 Series（True = 通过所有红线）。"""
    keep = pd.Series(True, index=df.index)
    if cfg.all_disabled():
        return keep

    def _num(col):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    if cfg.min_mkt_cap_cny is not None:
        mk = _num("mkt_cap_cny")
        if mk is not None:
            keep &= (mk >= cfg.min_mkt_cap_cny).fillna(False)

    if cfg.max_goodwill_to_equity is not None:
        g = _num("goodwill_to_equity")
        if g is not None:
            keep &= (g <= cfg.max_goodwill_to_equity).fillna(True)   # 缺数据放过

    if cfg.profit_alert_floor is not None:
        pa = _num("profit_alert")
        if pa is not None:
            keep &= (pa >= cfg.profit_alert_floor).fillna(True)

    if cfg.require_positive_eps_acc:
        e = _num("eps_yoy_acc")
        if e is not None:
            keep &= (e > -9999).fillna(True)        # placeholder：当列存在就保留所有非空

    return keep


# =============================================================
# 一键跑全套
# =============================================================

def run_screener(df: pd.DataFrame, cfg: ScreenerConfig | None = None) -> pd.DataFrame:
    """跑 3 套规则 + 红线，返回宽表。
    新列包括：
        - r_*  (analyst 13 各条)
        - pass_analyst
        - w_*  (wind5 各条)
        - pass_wind5
        - score_quality / growth / valuation / cash / composite
        - sector_rank
        - sector_pe
        - red_line_pass
    """
    cfg = cfg or ScreenerConfig()
    sector_pe = compute_sector_pe(df, method=cfg.sector_pe_method)
    out = apply_analyst_rules(df, cfg.analyst, sector_pe=sector_pe)
    out = apply_operational_rules(out, cfg.operational)
    out = apply_consensus_rules(out, cfg.consensus)
    out = apply_wind5_rules(out, cfg.wind5)
    out = score_4dim(out, cfg.weights)
    out["red_line_pass"] = apply_red_lines(out, cfg.red_lines)
    # 硬筛: 三块(估值/经营/一致预期)全过 + 红线
    out["pass_all"] = (
        out["pass_analyst"].fillna(False)
        & out["pass_operational"].fillna(False)
        & out["pass_consensus"].fillna(False)
        & out["red_line_pass"].fillna(False)
    )
    return out
