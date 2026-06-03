"""基本面量化选股看板 —— 按导师「基本面量化指令集」三块(估值 / 经营 / 一致预期)。

启动: streamlit run app/dashboard_screener.py
逻辑: 硬筛(三块规则 AND) + 复合分排序(行业内分位, 4 维度) 并存。
所有列的中文名/格式/口径集中在 app/column_meta.py。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from column_meta import RULE_LABELS, build_column_config, humanize_df, label_of  # noqa: E402
from screener import (  # noqa: E402
    AnalystRules, ConsensusRules, OperationalRules, RedLines,
    ScreenerConfig, Weights4Dim, Wind5Rules, run_screener,
)
from screener_data import (  # noqa: E402
    INDEX_OPTIONS, load_v4_index_snapshot, load_v4_snapshot,
)
from theme import PALETTE, PLOTLY_LAYOUT  # noqa: E402

st.set_page_config(page_title="基本面量化选股", layout="wide",
                   initial_sidebar_state="expanded", page_icon="🎯")

# ---- 专业淡雅主题 (白底 + 粉蓝点缀) ----
st.markdown(f"""
<style>
html, body, [class*="css"] {{ font-family:"PingFang SC",Helvetica,Arial,sans-serif; }}
.block-container {{ padding-top:1.6rem; max-width:1400px; }}
[data-testid="stMetric"] {{
    background:#FFFFFF; border:1px solid #ECECEC; border-radius:12px;
    padding:14px 18px; box-shadow:0 1px 4px rgba(0,0,0,.05);
}}
[data-testid="stMetricLabel"] {{ color:#7A7A7A; font-weight:500; }}
section[data-testid="stSidebar"] {{ background:#FAFBFC; }}
section[data-testid="stSidebar"] .stCheckbox {{ margin-bottom:-8px; }}
.stTabs [data-baseweb="tab-list"] {{ gap:6px; }}
.stTabs [data-baseweb="tab"] {{ background:#F2F4F7; border-radius:8px 8px 0 0; padding:8px 18px; }}
.stTabs [aria-selected="true"] {{ background:{PALETTE['down']} !important; font-weight:600; }}
.chip {{ display:inline-block; background:#EEF2F7; color:#33506e; border-radius:14px;
         padding:3px 11px; margin:2px 4px 2px 0; font-size:12.5px; }}
h3 {{ letter-spacing:.3px; }}
</style>
""", unsafe_allow_html=True)

DB_PATH = Path(__file__).parent.parent / "data" / "wind_history.db"
MARKET_OPTIONS = {"A": "A 股", "HK": "港股"}


@st.cache_data(ttl=300)
def load_snapshot(universe_indexes=(), markets=()):
    df = load_v4_snapshot(DB_PATH, universe_indexes=universe_indexes, markets=markets)
    return (df, "db") if not df.empty else (df, "empty")


@st.cache_data(ttl=300)
def load_index_snapshot(trade_date=None, markets=()):
    return load_v4_index_snapshot(DB_PATH, trade_date=trade_date, markets=markets)


# =============================================================
# 预设(写入 session_state, 各控件用 key 读取)
# =============================================================
# 估值块默认开的核心几条 + 经营块 5 年均 ROE
_CORE_ON = dict(on_g=True, on_roe=True, on_pe=True, on_div=True, on_q=True,
                on_acc=True, on_ytd=True, on_roe5=True)
_THRESH = dict(top_n=2, g_pct=20, roe_pct=8, div_pct=0, q_pct=5, acc_pct=20,
               rev_n=2, op_n=5, gm_n=3, om_n=3, ar_p=25, inv_p=25,
               roe5_pct=8, rcagr_pct=10, ncagr_pct=10)
_ALL_OFF = dict(on_topn=False, on_nde1=False, on_rev=False, on_op=False, on_gm=False,
                on_om=False, on_ar=False, on_inv=False, on_rcagr=False, on_ncagr=False,
                on_nde2=False, on_a1w=False, on_a1m=False, on_m1w=False, on_m1m=False,
                on_accfwd=False)
PRESETS = {
    "均衡(默认)": {**_THRESH, **_ALL_OFF, **_CORE_ON},
    "指令集严格": {**_THRESH, **{k: True for k in _CORE_ON},
               **dict(on_topn=True, on_rev=True, on_gm=True, on_om=True, on_ar=True,
                      on_inv=True, on_roe5=True, on_a1m=True, on_accfwd=True,
                      on_nde1=False, on_op=False, on_rcagr=False, on_ncagr=False,
                      on_nde2=False, on_a1w=False, on_m1w=False, on_m1m=False)},
    "宽松": {**_THRESH, **_ALL_OFF,
           **dict(on_roe=True, on_pe=True, on_roe5=True, on_g=False, on_div=False,
                  on_q=False, on_acc=False, on_ytd=False)},
}


def _apply_preset():
    for k, v in PRESETS[st.session_state.preset].items():
        st.session_state[k] = v


def _seed():
    if "preset" not in st.session_state:
        st.session_state.preset = "均衡(默认)"
        for k, v in PRESETS["均衡(默认)"].items():
            st.session_state[k] = v


# =============================================================
# 侧栏
# =============================================================
def render_sidebar() -> tuple[ScreenerConfig, dict]:
    _seed()
    sb = st.sidebar
    sb.markdown("## 🎛️ 选股条件")
    sb.selectbox("🎚️ 预设方案", list(PRESETS), key="preset", on_change=_apply_preset,
                 help="一键套用一组条件; 之后可在下面微调")

    sb.markdown("##### 股票池")
    markets = sb.multiselect("市场", list(MARKET_OPTIONS), default=list(MARKET_OPTIONS),
                             format_func=lambda c: MARKET_OPTIONS[c])
    indexes = sb.multiselect("指数 (空=全部)", list(INDEX_OPTIONS), default=[],
                             format_func=lambda c: f"{c} {INDEX_OPTIONS[c]}")
    mode = sb.radio("选股模式", ["硬筛 + 复合分排序", "只硬筛", "只复合分排序"], index=0)
    mkt_cap_min = sb.number_input("总市值下限 (亿)", value=50, step=10)
    amount_min = sb.number_input("月成交额下限 (亿)", value=0, step=5)

    with sb.expander("① 估值 Valuation", expanded=True):
        st.caption("行业相对 + 估值/盈利质量")
        on_topn = st.checkbox("行业内市值 Top N", key="on_topn")
        top_n = st.number_input("　Top N", 1, 20, key="top_n", disabled=not on_topn)
        on_g = st.checkbox("当年 EPS 增速 ≥", key="on_g")
        g = st.slider("　%", -20, 100, key="g_pct", disabled=not on_g) / 100
        on_roe = st.checkbox("ROE ≥", key="on_roe")
        roe = st.slider("　% ", 0, 30, key="roe_pct", disabled=not on_roe) / 100
        on_pe = st.checkbox("PE < 行业中位", key="on_pe")
        on_div = st.checkbox("股息率 ≥", key="on_div")
        div = st.slider("　%  ", 0, 10, key="div_pct", disabled=not on_div) / 100
        on_q = st.checkbox("最新季 EPS 增速 ≥", key="on_q")
        eq = st.slider("　%   ", -20, 50, key="q_pct", disabled=not on_q) / 100
        on_acc = st.checkbox("累计 EPS 增速 ≥", key="on_acc")
        eacc = st.slider("　%    ", -20, 60, key="acc_pct", disabled=not on_acc) / 100
        on_ytd = st.checkbox("YTD 涨幅 < 累计 EPS 增速", key="on_ytd")
        on_nde1 = st.checkbox("净负债率 < 0 (净现金)", key="on_nde1")

    with sb.expander("② 经营 Operational", expanded=False):
        st.caption("行业内排名")
        on_rev = st.checkbox("营收 行业 Top N", key="on_rev")
        rev_n = st.number_input("　Top N ", 1, 20, key="rev_n", disabled=not on_rev)
        on_op = st.checkbox("营业利润 行业 Top N", key="on_op")
        op_n = st.number_input("　Top N  ", 1, 20, key="op_n", disabled=not on_op)
        on_gm = st.checkbox("毛利率 行业 Top N", key="on_gm")
        gm_n = st.number_input("　Top N   ", 1, 20, key="gm_n", disabled=not on_gm)
        on_om = st.checkbox("营业利润率 行业 Top N", key="on_om")
        om_n = st.number_input("　Top N    ", 1, 20, key="om_n", disabled=not on_om)
        on_ar = st.checkbox("应收周转天数 行业最低 X%", key="on_ar")
        ar_p = st.slider("　%     ", 5, 50, key="ar_p", disabled=not on_ar)
        on_inv = st.checkbox("存货周转天数 行业最低 X%", key="on_inv")
        inv_p = st.slider("　%      ", 5, 50, key="inv_p", disabled=not on_inv)
        st.caption("绝对阈值")
        on_roe5 = st.checkbox("5 年平均 ROE ≥", key="on_roe5")
        roe5 = st.slider("　%       ", 0, 30, key="roe5_pct", disabled=not on_roe5) / 100
        on_rcagr = st.checkbox("营收 3 年 CAGR ≥", key="on_rcagr")
        rcagr = st.slider("　%        ", -10, 50, key="rcagr_pct", disabled=not on_rcagr) / 100
        on_ncagr = st.checkbox("净利 3 年 CAGR ≥", key="on_ncagr")
        ncagr = st.slider("　%         ", -10, 50, key="ncagr_pct", disabled=not on_ncagr) / 100
        on_nde2 = st.checkbox("ND/E < 0", key="on_nde2")

    with sb.expander("③ 一致预期 TP", expanded=False):
        st.caption("券商一致预期净利修正方向")
        on_a1w = st.checkbox("均值净利 周修正 向上", key="on_a1w")
        on_a1m = st.checkbox("均值净利 月修正 向上", key="on_a1m")
        on_m1w = st.checkbox("中值净利 周修正 向上", key="on_m1w")
        on_m1m = st.checkbox("中值净利 月修正 向上", key="on_m1m")
        on_accfwd = st.checkbox("累计 EPS 增速 > 预期净利增速", key="on_accfwd")

    with sb.expander("④ 复合分权重 / 红线", expanded=False):
        wq = st.slider("质量权重", 0.0, 1.0, 0.30, 0.05)
        wg = st.slider("成长权重", 0.0, 1.0, 0.25, 0.05)
        wv = st.slider("估值权重", 0.0, 1.0, 0.25, 0.05)
        wc = st.slider("现金权重", 0.0, 1.0, 0.20, 0.05)
        rl_mkt = st.checkbox(f"红线: 市值 ≥ {mkt_cap_min} 亿", value=True)
        rl_alert = st.checkbox("红线: 业绩预告 > -30%", value=True)

    cfg = ScreenerConfig(
        analyst=AnalystRules(
            sector_top_n=int(top_n) if on_topn else None,
            eps_fy1_growth_min=g if on_g else None,
            roe_ttm_min=roe if on_roe else None,
            pe_vs_sector=on_pe,
            div_yield_min=div if on_div else None,
            nd_to_equity_max=0.0 if on_nde1 else None,
            eps_yoy_q_min=eq if on_q else None,
            eps_yoy_acc_min=eacc if on_acc else None,
            ytd_lt_eps_acc=on_ytd,
        ),
        operational=OperationalRules(
            rev_top_n=int(rev_n) if on_rev else None,
            op_profit_top_n=int(op_n) if on_op else None,
            gross_margin_top_n=int(gm_n) if on_gm else None,
            op_margin_top_n=int(om_n) if on_om else None,
            ar_days_lowest_pct=ar_p if on_ar else None,
            inv_days_lowest_pct=inv_p if on_inv else None,
            roe_5y_min=roe5 if on_roe5 else None,
            rev_cagr3_min=rcagr if on_rcagr else None,
            np_cagr3_min=ncagr if on_ncagr else None,
            nd_to_equity_max=0.0 if on_nde2 else None,
        ),
        consensus=ConsensusRules(avg_rev_1w_up=on_a1w, avg_rev_1m_up=on_a1m,
                                 med_rev_1w_up=on_m1w, med_rev_1m_up=on_m1m, acc_gt_fwd=on_accfwd),
        wind5=Wind5Rules(),
        weights=Weights4Dim(quality=wq, growth=wg, valuation=wv, cash=wc),
        red_lines=RedLines(min_mkt_cap_cny=mkt_cap_min if rl_mkt else None,
                           max_goodwill_to_equity=None,
                           profit_alert_floor=-0.30 if rl_alert else None),
    )
    # 条件回显文案
    chips = []
    if on_g: chips.append(f"EPS增速≥{int(g*100)}%")
    if on_roe: chips.append(f"ROE≥{int(roe*100)}%")
    if on_pe: chips.append("PE<行业")
    if on_div: chips.append(f"股息≥{int(div*100)}%")
    if on_q: chips.append(f"季增速≥{int(eq*100)}%")
    if on_acc: chips.append(f"累计增速≥{int(eacc*100)}%")
    if on_ytd: chips.append("YTD<增速")
    if on_topn: chips.append(f"市值Top{int(top_n)}")
    if on_roe5: chips.append(f"5年ROE≥{int(roe5*100)}%")
    if on_rev: chips.append(f"营收Top{int(rev_n)}")
    if on_gm: chips.append(f"毛利率Top{int(gm_n)}")
    if on_om: chips.append(f"营业利润率Top{int(om_n)}")
    if on_ar: chips.append(f"应收最低{int(ar_p)}%")
    if on_inv: chips.append(f"存货最低{int(inv_p)}%")
    if on_a1m: chips.append("均值月修正↑")
    if on_accfwd: chips.append("累计>预期")
    extra = {"markets": tuple(markets), "indexes": tuple(indexes),
             "amount_min": amount_min, "mode": mode, "chips": chips}
    return cfg, extra


# =============================================================
# 展示
# =============================================================
CORE_COLS = ["score_composite", "sw_l1", "name", "wind_code", "mkt_cap_cny",
             "pe_ttm", "roe_ttm", "eps_fy1_growth", "eps_yoy_acc", "div_yield"]
EXTRA_COLS = ["sector_pe", "pb_lf", "roe_5y_avg", "gross_margin", "operating_margin",
              "net_margin", "rev_cagr3", "np_cagr3", "ar_turn_days", "inv_turn_days",
              "nd_to_equity", "fcf", "ytd_return", "sector_rank"]


def show_table(d: pd.DataFrame, full: bool, height=460, key=None, selectable=False):
    cols = CORE_COLS + (EXTRA_COLS if full else [])
    cols = [c for c in cols if c in d.columns]
    disp = humanize_df(d, cols)
    kw = {}
    if selectable:
        kw = dict(on_select="rerun", selection_mode="single-row")
    return st.dataframe(disp[cols], width="stretch", height=height, hide_index=True,
                        column_config=build_column_config(cols), key=key, **kw)


def radar_vs_sector(row, pool):
    dims = ["score_quality", "score_growth", "score_valuation", "score_cash"]
    labels = [label_of(d) for d in dims]
    sec = pool[pool["sw_l1"] == row["sw_l1"]]
    me = [float(row.get(d, 0) or 0) for d in dims]
    med = [float(sec[d].median() or 0) for d in dims]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=med + [med[0]], theta=labels + [labels[0]],
                                  name="行业中位", line_color=PALETTE["neutral"], opacity=0.6))
    fig.add_trace(go.Scatterpolar(r=me + [me[0]], theta=labels + [labels[0]], fill="toself",
                                  name=row["name"], line_color=PALETTE["price"]))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], visible=True)),
                      height=340, margin=dict(l=40, r=40, t=30, b=30),
                      legend=dict(orientation="h", y=-0.1))
    return fig


# =============================================================
# 主流程
# =============================================================
cfg, extra = render_sidebar()
with st.spinner("筛选中…"):
    df_raw, source = load_snapshot(universe_indexes=extra["indexes"], markets=extra["markets"])
    if not df_raw.empty and extra["amount_min"] and "amount_1m" in df_raw.columns:
        df_raw = df_raw[df_raw["amount_1m"].fillna(0) >= extra["amount_min"]]

if df_raw.empty:
    st.warning("⚠️ 还没有真实数据。请先跑采集脚本(见 docs/SCREENER_PIPELINE_V4.md)。")
    st.stop()

trade_date = df_raw["trade_date"].iloc[0] if "trade_date" in df_raw.columns else None
df = run_screener(df_raw, cfg)
pool = df[df["red_line_pass"]].copy()
hard = pool[pool["pass_all"]] if "pass_all" in pool.columns else pool.iloc[0:0]

# ---- 顶部 ----
st.markdown("### 🎯 基本面量化选股")
st.caption("按导师「基本面量化指令集」：估值 / 经营 / 一致预期 三块。左侧选预设或逐条调，右侧实时出候选。")
k = st.columns(5)
k[0].metric("股票池", f"{len(pool)}")
k[1].metric("硬筛通过", f"{len(hard)}", f"{len(hard)/max(len(pool),1)*100:.0f}%")
k[2].metric("覆盖行业", pool["sw_l1"].nunique() if "sw_l1" in pool else 0)
k[3].metric("复合分中位", f"{pool['score_composite'].median():.0f}" if len(pool) else "—")
k[4].metric("数据日期", trade_date or "—")
if extra["chips"]:
    st.markdown("生效条件　" + "".join(f"<span class='chip'>{c}</span>" for c in extra["chips"]),
                unsafe_allow_html=True)
st.divider()

tab1, tab2, tab3, tab4 = st.tabs(["🎯 选股结果", "🔬 规则漏斗", "📊 复合分", "📈 指数温度"])

with tab1:
    full = st.toggle("显示全部指标", value=False, help="默认只看核心 10 列")
    mode = extra["mode"]

    if mode != "只复合分排序":
        st.subheader(f"硬筛通过 · {len(hard)} 只")
        if len(hard):
            ranked = hard.sort_values("score_composite", ascending=False)
            sel = show_table(ranked, full, height=440, key="cand", selectable=True)
            st.download_button("⬇️ 导出 CSV", ranked.to_csv(index=False).encode("utf-8-sig"),
                               "screener_picks.csv", "text/csv")
            # ---- 个股下钻 ----
            rows = sel.selection.rows if sel and hasattr(sel, "selection") else []
            if rows:
                r = ranked.iloc[rows[0]]
                st.markdown(f"#### 🔍 {r['name']} ({r['wind_code']}) · {r['sw_l1']}")
                c1, c2 = st.columns([1, 1.4])
                with c1:
                    st.plotly_chart(radar_vs_sector(r, pool), width="stretch")
                with c2:
                    metrics = ["pe_ttm", "roe_ttm", "roe_5y_avg", "eps_fy1_growth",
                               "gross_margin", "net_margin", "rev_cagr3", "div_yield"]
                    sec = pool[pool["sw_l1"] == r["sw_l1"]]
                    comp = pd.DataFrame({
                        "指标": [label_of(m) for m in metrics],
                        "该股": [r.get(m) for m in metrics],
                        "行业中位": [sec[m].median() for m in metrics],
                    })
                    pctish = {"roe_ttm", "roe_5y_avg", "eps_fy1_growth", "gross_margin",
                              "net_margin", "rev_cagr3", "div_yield"}
                    for col in ("该股", "行业中位"):
                        comp[col] = [f"{v*100:.1f}%" if metrics[i] in pctish and pd.notna(v)
                                     else (f"{v:.1f}" if pd.notna(v) else "—")
                                     for i, v in enumerate(comp[col])]
                    st.dataframe(comp, width="stretch", height=320, hide_index=True)
            else:
                st.caption("👆 点表格左侧选中一只股，看它的 4 维雷达图 + 对比行业中位。")
        else:
            st.info("硬筛 0 只全过。下面是「最接近通过」的 10 只 + 各自卡在哪条 —— 据此放松条件。")
            rule_cols = [c for c in df.columns if c.startswith(("r_", "o_", "c_"))]
            if rule_cols:
                miss = pool.copy()
                miss["未过条数"] = (~miss[rule_cols].astype(bool)).sum(axis=1)
                near = miss.nsmallest(10, "未过条数")
                near["卡在"] = near.apply(
                    lambda x: "、".join(label_of(c) if not str(c).startswith(("r_", "o_", "c_")) else c
                                       for c in rule_cols if not x[c])[:60] or "—", axis=1)
                st.dataframe(near[["name", "wind_code", "sw_l1", "未过条数", "卡在"]],
                             width="stretch", hide_index=True)

    if mode != "只硬筛":
        st.subheader("复合分排行榜 · Top 50")
        show_table(pool.sort_values("score_composite", ascending=False).head(50), full, height=440)

with tab2:
    st.subheader("各条规则通过率")
    st.caption("通过率越低 = 卡得越严，优先放松这些。")
    rule_cols = [c for c in df.columns if c.startswith(("r_", "o_", "c_"))]
    if rule_cols:
        funnel = pd.DataFrame({
            "规则": [RULE_LABELS.get(c, c) for c in rule_cols],
            "块": ["估值" if c.startswith("r_") else "经营" if c.startswith("o_") else "一致预期" for c in rule_cols],
            "通过率": [round(df[c].mean() * 100, 1) for c in rule_cols],
        }).sort_values("通过率")
        fig = px.bar(funnel, x="通过率", y="规则", color="块", orientation="h", text="通过率",
                     color_discrete_map={"估值": PALETTE["price"], "经营": PALETTE["forecast"], "一致预期": PALETTE["up"]},
                     height=max(320, 28 * len(funnel)))
        fig.update_layout(**PLOTLY_LAYOUT)
        fig.update_xaxes(range=[0, 112])
        fig.update_traces(texttemplate="%{text}%", textposition="outside",
                          textfont=dict(color="#444", size=12), cliponaxis=False)
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("当前未勾选任何规则。")

with tab3:
    st.subheader("估值 × 质量 (右上 = 又便宜又好)")
    plot_df = pool.dropna(subset=["score_valuation", "score_quality"])
    if len(plot_df):
        fig = px.scatter(plot_df, x="score_valuation", y="score_quality",
                         size=plot_df["mkt_cap_cny"].clip(lower=10), color="sw_l1",
                         hover_name="name",
                         hover_data={"wind_code": True, "pe_ttm": ":.1f", "roe_ttm": ":.1%",
                                     "score_composite": ":.0f", "sw_l1": False},
                         labels={"score_valuation": "估值分(越高越便宜)", "score_quality": "质量分", "sw_l1": "行业"},
                         height=480)
        fig.add_hline(y=50, line_dash="dot", opacity=0.4)
        fig.add_vline(x=50, line_dash="dot", opacity=0.4)
        fig.update_layout(**{kk: vv for kk, vv in PLOTLY_LAYOUT.items() if kk != "legend"})
        st.plotly_chart(fig, width="stretch")
    if "sw_l1" in pool.columns and len(pool):
        st.subheader("行业 × 维度 均分")
        heat = pool.groupby("sw_l1")[["score_quality", "score_growth", "score_valuation", "score_cash"]].mean().round(0)
        heat.columns = [label_of(c) for c in heat.columns]
        if not heat.empty:
            fig = px.imshow(heat.T, text_auto=True, aspect="auto", color_continuous_scale="RdBu_r",
                            labels={"x": "行业", "y": "维度", "color": "均分"})
            fig.update_layout(height=320, margin=dict(l=70, r=30, t=20, b=90))
            st.plotly_chart(fig, width="stretch")

with tab4:
    st.subheader("指数 / 行业指数 估值温度")
    idx = load_index_snapshot(trade_date=trade_date, markets=extra["markets"])
    if idx.empty:
        st.info("等待 daily 模板的 index sheet 入库。")
    else:
        icols = [c for c in ["market", "entity_type", "wind_code", "name", "close",
                             "pe_ttm", "pb_lf", "div_yield", "ytd_return"] if c in idx.columns]
        st.dataframe(humanize_df(idx, icols)[icols], width="stretch", height=500,
                     hide_index=True, column_config=build_column_config(icols))
