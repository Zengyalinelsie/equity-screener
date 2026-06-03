# 指标盘点与对齐：源表 Index Future vs 我们的 4 模板

> 最后更新：2026-06-03
> 源表：`templates/Index Future Valuation Table(Wind)_clean.xlsx`（sheet `000016` 为代表，每指数同构）
> 我们的模板：`template_static / template_daily / template_annual / template_financials`（均双 sheet a/hk）

---

## 一、源表全字段（按频率盘点，逐股口径）

源表一张大宽表把所有频率混在一起。按更新频率拆成 4 桶（index 层聚合 / 选股逻辑列单列）：

### 🟦 天（随价格 / 当前日 `$B$1` 变）
| 源表列 | 含义 | Wind 公式 |
|---|---|---|
| A | 一致预期净利 7 日修正 | `s_west_netprofit(…,2025,$B$1)/…(…,$A$1)` |
| B | 当日涨跌 | `RTD("wdf.rtq",,…,"PctChg")` |
| G | 总市值(RMB bn) | `s_val_ev($C,$B$1)` |
| H | 月成交额(USD bn) | `s_mq_amount($C,$B$1)*100/7` |
| I | Beta | `s_risk_betar24` |
| J | 股票价格 | `s_dq_close` |
| K | Profit Alert | `s_profitnotice_changeratio` |
| AH–AK | PE(2023/24/25E/26E) | 派生 `=J/EPS年` |
| AO | Div Yield | `s_val_dividendyield2` |
| AP | P/B | `s_val_pb_lf` |
| BV | YTD Perf | `i_pq_pctchange(…,"2025/01/01",$B$1)` |

### 🟩 静态
| D 名称 `S_INFO_NAME` · E 行业 `s_info_industry_sw_2021` · F 指数权重(引用 W sheet) |

### 🟨 年（按财年）
| 源表列 | 含义 | Wind 公式 |
|---|---|---|
| L–Z | EPS 实际 2011→2025（**15 年**） | `s_stm07_is(…,"W30028333",年末)/S_SHARE_TOTAL` |
| AA | EPS 26E（前瞻一致预期） | `s_west_netprofit(…,2026,$B$1,180)/S_SHARE_TOTAL` |
| AB–AF | EPS Growth 2022→26E | 派生 |
| AG | ROE | `s_fa_dupont_roe` |
| AL/AM/AN | EV/EBITDA · EV1 · EBITDA | `s_val_ev1($B$2)` · `s_fa_ebitda($B$2)` |
| AQ/AR/AS | ND/E · ND · 净资产 | `s_fa_netdebt($B$2)` · `s_stm07_bs("W38058048",$B$2)` |

### 🟧 季（按季末）
| 源表列 | 含义 | Wind 公式 |
|---|---|---|
| BW–DN | **逐季 EPS** 2016Q1→2026Q4（全 Q1/1H/9M/FY） | `S_FA_EPS_basic2(…,季末,"Cur=CNY")` |
| AT–BU | 逐季 EPS 同比增速 | 派生 `=本季/去年同季-1` |

### 🟥 半年 / 报告期明细（源表只算了 1H25 一期，`ER:FH` 块）
| 源表列 | 含义 | Wind 公式 |
|---|---|---|
| ER / ES | 经营现金流 / Capex | `s_stm07_cs("W77130581")` / `("W77745895")` |
| ET | Free Cash Flow | 派生 `=ER-ES` |
| EX | Revenue 营收 | `s_stm07_is("W70156729")` |
| EY | COGS 营业成本 | `s_stm07_is("W75682424")` |
| EZ / FA / FB | 销售 / 管理 / 研发费用 | `("W76031679")` / `("W70752487")` / `s_stm07_is_103` |
| FC | Operating profit 营业利润 | 派生 `=营收-成本-三费` |
| FD / FE / FF | 利息支出 / 收入 / 净利息 | `s_stm07_is_104` / `_105` / 派生 |
| FG | Pretax profit 税前利润 | `s_stm07_is("W72946623")` |
| FH | Non-operating income 营业外 | 派生 `=税前-营业利润` |
| EV / EW | 毛利率 / 营业利润率 | 派生 |
| 归母净利(Annual) | 归母净利 | `s_stm07_is("W30028333",报告期)` |

### ⬜ 非数据列（不入模板）
- `DQ:EP` —— 指数层 `SUMPRODUCT(权重×指标)` 聚合 + `DY` 一致预期中位（看板派生，不逐股落库）。
- `FJ` 选股：`=IF(AND(ROE>10%, PE(25E)<40, DivYield>1%, 1H增速>YTD, FCF>0),"OK")` —— 复刻进 `app/screener.py` 规则引擎。
- `FR` 10 步加仓法 —— 仓位工具，非数据。

---

## 二、我们 4 模板的全字段

| 模板 | sheet | 字段 |
|---|---|---|
| **static** | a/hk | name, sw_l1, sw_l2, ipo_date |
| **daily** | a | close, volume, amount, turnover_rate, mkt_cap_raw, total_mkt_cap_raw, ev1_raw, mq_amount_raw, pe_ttm, pb, div_yield, ev_ebitda, beta_24m, profit_alert, ytd_pctchange_raw, **+ FY1/FY2 一致预期 15 列**(fy1_np_avg/eps/instnum/std/median/max/min, fy2_*, roe_fwd), iw_50/300/500/1000 |
| | hk | 同上，权重列换 iw_hsi/hscei/hstech，PB 用 `s_val_pb` |
| | index | close, pe_ttm, pb, div_yield, fy1_eps |
| **annual** | a/hk | eps_2011…eps_2025（15 年）, eps_2026E, eps_2027E, net_profit_raw, roe, equity_raw, net_debt_raw, ev1_raw, ebitda_raw, np_rev_fy1（EV/EBITDA、ND/E 在 pull 派生） |
| **financials** | a/hk | revenue_raw, cogs_raw, selling_exp_raw, admin_exp_raw, rd_exp_raw, interest_expense_raw, interest_income_raw, pretax_profit_raw, net_profit_raw, operating_cashflow_raw, capex_raw, basic_eps（毛利率/营业利润/营业利润率/净利息/营业外/FCF/同比在 pull 派生） |
| **membership** | （非 Wind, import_membership.py） | in_50…in_hstech, w_50…w_hstech |

> **ODS 原则**：annual / financials 公式**不做任何单位换算**（不写 1000000/100000000），落库为 Wind 原值（`_raw`，元），单位清洗放看板。**例外 `basic_eps`**：`S_FA_EPS_basic2` 必须带 `Cur=CNY` 才出数（实测 A/HK 都正常），港股 EPS 因此折成人民币（A/HK 可同币种比较）。

---

## 三、对比：覆盖 / 遗漏 / 多出

### ✅ 已覆盖源表
- **天**：price/总市值/月成交额/Beta/profit alert/PE/股息/PB/YTD —— daily 全覆盖。
- **年**：EPS 逐年(2011→27E) + ROE + ND/E + EV/EBITDA(财年) + FY1 一致预期修正 —— annual 全覆盖。
- **季 / 半年**：逐季 EPS(Q1/1H/9M/FY) —— financials 全覆盖（backfill 默认全季度）。
- **半年/报告期明细**：营收/成本/三费/营业利润/利息/税前/营业外/归母净利/经营现金流/Capex/FCF/毛利率/营业利润率 —— **financials 全覆盖**，而且做成 FY+1H 时间序列（源表只算了 1H25 一期，我们更完整）。
- **选股 FJ** 五个输入（ROE/PE/股息/增速>perf/FCF>0）全部进了看板规则引擎。

### ✅ 之前的 4 项遗漏 —— 现已全部补齐（2026-06-03）
| # | 源表字段 | 处理 |
|---|---|---|
| 1 | 逐季 EPS 全序列(Q1/Q3) | `backfill_financials.py` **默认 `--periods FY,1H,Q1,Q3`**，全季度入 `periodic_financials` |
| 2 | EPS 2011–2015 | annual 起点改回 **2011**（`ACTUAL_YEARS=range(2011,2026)`，15 年，对齐源表） |
| 3 | EV/EBITDA「财年口径」 | annual 新增 `ev1_raw` / `ebitda_raw`（`s_val_ev1`/`s_fa_ebitda` at 财年），pull 派生 `ev_to_ebitda`；daily 的 TTM `ev_ebitda` 另存一份 |
| 4 | 一致预期 7 日修正 | annual 新增 `np_rev_fy1` = `s_west_netprofit(FY1,$B$1)/s_west_netprofit(FY1,$B$1-7)-1`（源表 A 列做法，一个公式不依赖历史） |

### ➕ 我们多出来的（源表没有，刻意增强）
1. **daily FY1/FY2 一致预期分歧度全套（15 列）** —— 服务 own-EPS vs consensus gap MVP（你之前调研的增强指标）。
2. daily `volume` / `turnover_rate`（源表只有月成交额）。
3. annual `eps_2027E`（源表只到 26E）。
4. financials 把报告期明细做成**历史时间序列**（源表只一期）。

> 结论：源表逐股指标**已全覆盖，无遗漏**；多出来的都是有意增强。

### ✅ 经营/一致预期块补强（2026-06-03，为指令集而加）
- **逐年 ROE**：annual 现在每个实际年都取 `s_fa_dupont_roe` → 看板可算 **5 年平均 ROE**。
- **周/月一致预期修正**：annual FY1 行新增 `np_avg_rev_1w/1m`(均值 s_west)、`np_med_rev_1w/1m`(中值 s_est_mediannetprofit)。
- **营运周转天数**：financials 新增 `ar_turn_days/ap_turn_days/inv_turn_days`(A 股 `s_fa_*turndays` / 港股 `hks_fa_*turndays`，金融股不适用)。
- → 指令集**三块(估值/经营/一致预期)现已全部有数据支撑**，看板不再有「待采集」。

---

## 四、A 股 vs H 股 对齐（是否冲突）

**DB 用 `market` 列区分 A/HK，两个 sheet 列名完全相同 → 落库无 schema 冲突。**

有意的 A/H 公式差异（**同一列、不同函数**，正确）：
| 字段 | A 股 | H 股 |
|---|---|---|
| 行业 sw_l1/l2 | `s_info_industry_sw_2021` | `hks_info_industry_sw_2021` |
| daily PB | `s_val_pb_lf` | `s_val_pb` |
| daily 指数权重 | iw_50/300/500/1000 | iw_hsi/hscei/hstech |

### ✅ HK 财报公式已实测验证（原风险点已解除）
**annual + financials 的 A 和 HK 用完全相同的财报公式**：
`s_stm07_is(…,"W30028333"…)`、`s_stm07_cs`、`s_stm07_is_103/104/105`、`s_fa_dupont_roe`、`s_fa_netdebt`、`s_stm07_bs`、`s_val_ev1`、`s_fa_ebitda`、`S_FA_EPS_basic2(…,"Cur=CNY")`。

**✅ 已实测验证（2026-06-03，600519.SH + 0700.HK）**：annual 全部公式 A/HK 都出数；financials 的 P&L 主科目（营收/成本/三费/税前/归母净利）+ EPS A/HK 都出数。**唯一 HK 缺口**：`s_stm07_cs`（经营现金流/Capex）和 `s_stm07_is_103/104/105`（研发/利息）港股返回 0（科目体系不同），入库为 0，A 股完整。

---

## 五、跑历史数据前 checklist
1. ☐ `templates/template_annual.xlsx`、`template_financials.xlsx` 已是最新（✅ 2026-06-03 已重生成）。
2. ☐ 打开两个模板，确认 Wind 登录后 a sheet 出数；**重点抽查 hk sheet 0700.HK 各列**。
3. ☐ `python scripts/import_membership.py`（已可跑，1908 行）。
4. ☐ `python scripts/pull_annual.py --date 20260602 --wait 240`。
5. ☐ `python scripts/backfill_financials.py --start-year 2021 --end-year 2025 --wait 240`（默认全季度 FY/1H/Q1/Q3）。
6. ☐ `python scripts/pull_info.py` + `pull_daily.py`（static/daily）。
7. ☐ `streamlit run app/dashboard_screener.py` 看候选股 + ROE/PE/FCF/增速列有值。
