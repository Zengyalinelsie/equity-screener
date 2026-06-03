# 选股数据管线 V4 —— 来龙去脉

> 文档对象：以后再回来看这个项目的自己（或新同事）  
> 最后更新：2026-06-03

> 字段下限和后续数据扩展蓝图见 [INDEX_FUTURE_DATA_BLUEPRINT.md](INDEX_FUTURE_DATA_BLUEPRINT.md)。后续不能只按“最小可跑字段”设计；物理落库表必须按更新频率组织，同时覆盖 `Index Future Valuation Table(Wind)` 已有的 FY1/FY2 一致预期、价量、市值和估值字段。

---

## ⭐ V5 干净重启（2026-06-03）—— 当前架构，先读这一节

V4 之后 codex 把模板搞乱了（年度砍成 4 年、季度堆 24 列没用的、多造 weekly/monthly、脚本/文档爆炸）。
V5 推倒重来，**严格对齐导师在用的源表 `templates/Index Future Valuation Table(Wind)_clean.xlsx`**
（按 50/300/500/1000 四指数组织，公式已验证能跑）。原则：源表怎么算，我们就怎么抄，不自创、不堆派生列。

**只有 4 类 Wind 模板（双 sheet a/hk）+ 1 个非 Wind 导入：**

| 数据 | 频率 | 模板 / 脚本 | DB 表 | 形态 | 关键 Wind 公式（含 `[1]!` 前缀，对齐源表） |
|---|---|---|---|---|---|
| 静态 | 一次 | `make_template_info` / `pull_info` | `static_info` | 一股一行 | `S_INFO_NAME` / `s_info_industry_sw_2021` / `s_ipo_listeddate` |
| 日频 | 日 | `make_template_daily` / `pull_daily` | `daily_market` | 一股一行 | `s_dq_close` / `s_val_ev` / `s_val_pe_ttm` / `s_val_pb_lf` / `s_val_dividendyield` / `s_val_evtoebitda` / `s_risk_betar24` / `s_profitnotice_changeratio` |
| **年度** | 年 | `make_template_annual` / `pull_annual` | `annual_fundamental` | **长表 (股×财年)** | EPS 实际 `s_stm07_is(...,"W30028333",...)/S_SHARE_TOTAL`；前瞻 `s_west_netprofit/S_SHARE_TOTAL`；`s_fa_dupont_roe` / `s_fa_netdebt` / `s_stm07_bs(...,"W38058048",...)` |
| **财报科目** | 年报+半年报 | `make_template_financials` / `pull_financials` / `backfill_financials` | `periodic_financials` | **长表 (股×报告期)** | 营收/成本/费用 `s_stm07_is(...)`、研发/利息 `s_stm07_is_103/104/105`、经营现金流/Capex `s_stm07_cs(...)`、EPS `S_FA_EPS_basic2` |
| 成员/权重 | 不定 | `import_membership`（**无 Wind**） | `monthly_membership` | 一股一行 | 源表 50W/300W/500W/1000W sheet 出权重 + codes_a/hk.csv 出成员标志 |

**财报科目表（periodic_financials）怎么组织**：一行 = 一只股 × 一个报告期末。`12-31` 行 = 年报，
`06-30` 行 = 半年报，所以一张长表同时给「按年 / 按半年」。模板一次只算一个报告期（B1=报告期末），
`backfill_financials.py` 对每一年的 FY+1H 一期一期回拉历史（不把好几年塞进一张大宽表，避免 macOS
Excel 一次算太多假死）。覆盖科目：营收/成本/毛利率/销售·管理·研发费用/营业利润/营业利润率/利息收支/
税前利润/营业外收入/归母净利/经营现金流/Capex/FCF/EPS（毛利率·营业利润·FCF·同比等派生在 pull 端算）。

**关键约定 / 修复（V4 踩坑的根因）：**
- Wind UDF **写裸函数名**（`=s_dq_close(...)`），与已验证的 daily 一致 —— macOS Wind.app 全局 add-in 可裸调用，**Excel 保存时自己加 `[1]!` 外部引用，模板里千万不要手写 `[1]!`**（手写会变成坏链接）。源表里看到的 `[1]!` 是保存后的形态，不是源码该写的。
- 财年/季末写成 **literal 字符串**（如 `"2025/12/31"`），**不用 `YEAR($B$1)`**（会被当日期序列号，旧坑）。
- `s_west_*` 的 `B1` as-of 必须是真 Excel 日期对象。
- 年度/季度 Excel 是宽表（一年/季一列，因 UDF 只能逐列），pull **反透视成长表**；表头从第 2 行动态读取，改年份区间无需改 pull。
- **一致预期并入 annual**（`is_estimate=1` 的前瞻年行），不再有独立 `weekly_forecast`。
- **取消月频 wset**：universe / 权重由源表 W sheets + codes 导入，少一个 macOS Excel 上易碎环节。
- EV/EBITDA、PB、股息、profit_alert 只在 daily，不在 annual（避免重复）。

**看板取数**（`app/screener_data.py::load_v4_snapshot`）：daily + static + membership + annual + periodic_financials →
宽表，按 `app/screener.py` 规则引擎期望的列名喂入派生字段：`roe_ttm`(最新实际财年 ROE)、
`nd_to_equity`、`eps_fy1_growth`(前瞻 EPS/最新实际−1)、`eps_growth`(FY2/FY1−1)、`fy1_eps`/`fy2_eps`、
`fwd_ep`、`eps_yoy_q`/`eps_yoy_acc`(最新报告期同比)、`revenue_yoy`/`gross_margin`/`operating_margin`/`fcf`。
规则引擎对缺列自动跳过，数据补齐后规则即自动激活
（= 复刻源表 FJ 列 `IF(AND(ROE>10%,PE<40,股息>1%,增速>perf,...))` 选股）。

**典型流程：**
```bash
python scripts/init_db_master_v4.py           # 建库（一次性 / 重置，会清空数据，日常勿跑）
python scripts/import_membership.py            # 成员+权重（无 Wind，源表/codes 刷新后重跑）
# 以下在 Wind 机上：生成模板 → 打开 Excel 等算完 → pull
python scripts/make_templates_all.py           # static/daily/annual/financials 四模板
python scripts/pull_info.py  --date YYYYMMDD --wait N
python scripts/pull_daily.py --date YYYYMMDD --wait N
python scripts/pull_annual.py    --date YYYYMMDD --wait N
python scripts/backfill_financials.py --start-year 2021 --end-year 2025 --wait N   # 年报+半年报回拉
streamlit run app/dashboard_screener.py
```

**⚠️ 已知风险**：源表只验证了 A 股公式（无 HK sheet）。HK 的 `s_stm07_is`/`s_fa_dupont_roe`/
`S_FA_EPS_basic2`/`s_fa_netdebt` 可能需港股前缀或返回空 → 批量生成前，先在实时 Wind 对
1 只 A（如 600519.SH）+ 1 只 HK（如 0700.HK）逐公式抽查；跑不通的字段入库 NULL，不阻塞看板。

被取代的旧脚本/模板/文档已归档到 `archive/`（weekly/monthly 链、旧 init、一次性 audit/backfill 等）。

---

> 下面是 V4 的历史记录，保留作来龙去脉参考（部分细节已被上面的 V5 取代）。

## 一、问题缘起

要做一个 A 股 + 港股选股看板，输入侧只能用本地 Excel + Wind add-in（macOS 上 Wind.app 把 `WindFunc.xla` 注册为全局 add-in，UDF 可裸调用如 `=s_dq_close(...)`，不需要 `[1]!` 前缀）。

核心约束：

- **数据从 Wind 拿，计算放 Python**（Excel 只做最薄的"公式表"）
- **不同字段更新频率不同**（永久 / 月 / 日），混在一张表里要么浪费 Wind 配额、要么数据陈旧
- **macOS Excel + Wind 很脆弱**：长任务、大 workbook、autorecover 都会触发 OSERROR

## 二、版本演化（踩坑记）

### V1（已废弃）
单一巨型模板 `template_25sheets.xlsx`，25 sheet 一锅端。问题：
- 一次重算十几分钟，Excel 经常假死
- 部分字段日频部分季频，混着拉浪费
- 字段加一个就要改整张表

### V2（已废弃）—— `stock_master` 单表
所有字段塞一张 sqlite 表。问题：
- 日频字段（close）和季频字段（roe）同一行 → 每天 update 时季频被覆盖成 NULL
- 字段语义混乱

### V3（短暂存在）—— 按频率拆 6 模板 + A股/HK 各一份
- ✅ 按频率切表正确
- ❌ A 股 / HK 各做一份模板和表（`stock_static` + `stock_static_hk`、`stock_daily` + `stock_daily_hk`），文件爆炸 12 个，看板查询要 union
- ❌ `index_constituents.industry` 跟 `stock_static.sw_l1` 字段重复
- ❌ 模板里既有逐行 UDF 又有 wset 数组公式，混乱

**触发重构的用户反馈**：
> "我靠 你弄出一大堆表格 你能有组织有系统的帮我组织和减少这些模板吗"
> "industry 跟 sw_l1/sw_l2 不是一样的吗 为什么还要分两个表 行业天天变吗？"
> "A 股/HK 都放一个 excel 里 用两个 sub sheet 区分"

### V4（当前）—— 4 张合并表 + 双 sheet 模板
最终决议：
1. **一个表 = 一个 xlsx**，xlsx 内 `a` / `hk` 两个 sub sheet
2. **数据库也合并**，加 `market` 列区分 'A' / 'HK'
3. **按频率切 4 张表**（永久信息 / 月度成员 / 日频快照 / 成分股长表）
4. **industry 字段删除**，行业唯一权威 = `stock_info.sw_l1 / sw_l2`
5. **季频财务暂不做**，等选股逻辑需要再加

## 三、最终架构

### 4 张主线频率表（`data/wind_history.db`）

| 表 | 主键 | 频率 | 关键字段 | 数据源 |
|---|---|---|---|---|
| `static_info` | wind_code | 静态/月季 | name, sw_l1, sw_l2, ipo_date | template_static UDF |
| `monthly_membership` | (as_of_date, wind_code) | 月 | in_*, w_* | template_monthly wset |
| `daily_market` | (trade_date, entity_type, wind_code) | 日 | close, volume, amount, turnover_rate, mkt_cap_yi, pe_ttm, pb, div_yield, fy1_eps, ev_ebitda, beta_24m, profit_alert | template_daily UDF |
| `weekly_forecast` | (as_of_date, wind_code) | 周 | FY1/FY2 NP 均值/高低值/EPS/机构数/分歧, roe_fwd | template_weekly UDF |

旧 `stock_info` / `stock_membership` / `stock_daily` / `index_constituents` 现在是兼容 view。`pipeline_freshness` 表记录每个 dataset 的最近一次运行状态。

### P0/P1 Excel 模板（`templates/`）

每个模板有 `a` 和 `hk` 两个 sheet，B1 单元格放日期参数，第 2 行表头，第 3 行起数据。

| 模板 | a sheet | hk sheet | 公式类型 |
|---|---|---|---|
| `template_monthly.xlsx` | 1850 行 × 5 列 | 220 行 × 5 列 | wset 数组公式（4+3 段），入 `monthly_membership` |
| `template_static.xlsx` | 1800 × 4 | 108 × 4 | 逐行 UDF（`S_INFO_NAME` / `s_info_industry_sw_2021` / `s_ipo_listeddate`） |
| `template_daily.xlsx` | 1800 × 11 | 108 × 11 + index 33 × 5 | 逐行 UDF（股票价量估值、Beta、Profit Alert + 指数/行业指数估值温度），入 `daily_market` |
| `template_weekly.xlsx` | A/HK 股票池 × 15 | A/HK 股票池 × 15 | FY1/FY2 一致预期，入 `weekly_forecast` |

### 4 条采集脚本 + 1 helper（`scripts/`）

| 文件 | 用途 |
|---|---|
| `_wind_xl.py` | xlwings 共享工具（`get_app` / `load_codes` / `write_sheet`） |
| `init_db_master_v4.py` | 部署频率表 schema + 兼容 view |
| `make_template_index_const.py` | 生成 monthly 模板（依赖 wset） |
| `make_template_info.py` | 生成 static 模板（依赖 codes csv） |
| `make_template_daily.py` | 生成 daily 模板（依赖 codes csv） |
| `make_template_weekly.py` | 生成 weekly 模板（依赖 codes csv） |
| `pull_index_const.py` | 读模板 → 写 monthly_membership + codes_a/hk.csv |
| `pull_info.py` | 读模板 → 写 static_info |
| `pull_daily.py` | 读模板 → 写 daily_market（当日） |
| `pull_weekly.py` | 读模板 → 写 weekly_forecast（周频） |

### 配置（`config/`）

- `codes_a.csv` / `codes_hk.csv` —— 由 `pull_index_const` 重写，给 info/daily 模板生成器读

## 四、典型操作流程

### 月度刷新（成分股 + 静态）
```bash
.venv/bin/python scripts/make_template_index_const.py       # 重建 monthly 模板
# 打开 templates/template_monthly.xlsx, 等 Wind 算完 (~30s)
.venv/bin/python scripts/pull_index_const.py --date 20260602 --wait 0
# 副产品: codes_a.csv 和 codes_hk.csv 已更新, monthly_membership 已写入

.venv/bin/python scripts/make_template_info.py              # 用新 codes 重建
# 打开 templates/template_static.xlsx, 等 Wind 算完
.venv/bin/python scripts/pull_info.py --date 20260602 --wait 0
```

### 日度刷新
```bash
.venv/bin/python scripts/make_template_daily.py             # 第一次或 codes 变了
# 平时只改 B1 日期即可, 模板复用
.venv/bin/python scripts/pull_daily.py --date 20260602 --wait 240

.venv/bin/python scripts/make_template_weekly.py            # 第一次或 codes 变了
# 打开 templates/template_weekly.xlsx, 等 Wind 算完
.venv/bin/python scripts/pull_weekly.py --date 20260602 --wait 240
```

`Index Future` 主线不使用 `s_fa_revenue`、`s_fa_profit`、`s_fa_eps` 实际财务公式。当前 Wind 环境这组函数返回 `#NAME?`，所以不要把 quarterly actuals 放入日常模板；净利润和 EPS 继续用 `weekly_forecast` 的 `s_west_netprofit` / `s_west_eps`。

完整公式审计见 [INDEX_FUTURE_WIND_DATA_FORMULA_AUDIT.md](INDEX_FUTURE_WIND_DATA_FORMULA_AUDIT.md)。
完整字段分层见 [INDEX_FUTURE_FULL_FIELD_COVERAGE.md](INDEX_FUTURE_FULL_FIELD_COVERAGE.md)。

### Excel 到 DB 是怎么走的

当前不是一个 Excel 大表直接入库，而是四个按频率拆开的模板分别入库，最后由 `app/screener_data.py` 拼成看板宽表：

| Excel 模板 | 手工/自动等待 Wind 算完后 | puller | 写入 DB 表 |
|---|---|---|---|
| `template_monthly.xlsx` | wset 溢出指数成分和权重 | `pull_index_const.py` | `monthly_membership`，同时更新 `codes_a.csv` / `codes_hk.csv` |
| `template_static.xlsx` | 每只股票一行公司信息 | `pull_info.py` | `static_info` |
| `template_daily.xlsx` | 股票一行价量估值；指数/行业指数一行估值温度 | `pull_daily.py` | `daily_market` |
| `template_weekly.xlsx` | 每只股票一行 FY1/FY2 一致预期 | `pull_weekly.py` | `weekly_forecast` |

看板不直接读 Excel。看板只读 SQLite：`daily_market + static_info + monthly_membership + weekly_forecast`，再派生 `fwd_ep`、`eps_growth`、`fy1_disagree` 等字段。

`--wait 0`：用户已经手工打开 Excel 让它算完，puller 直接读  
`--wait N`：puller 自己 sleep N 秒等公式计算  

## 五、关键经验（踩过的坑）

### 1. xlwings 而不是 openpyxl
openpyxl 写出的 xlsx 在 macOS Excel 打开会丢 Wind add-in 关联元数据 → 重新打开后 UDF 全部 `#NAME?` → 拉数失败。**所有 Wind 模板必须用 xlwings 让 Excel 自己 SaveAs**。

### 2. `app.calculation = "manual"` 写公式
1000+ 行批量写 UDF 时，每写一格都触发全 wb 重算 → 卡死。写之前设 manual，写完再恢复。

### 2.1 `s_west_*` 日期参数必须是真日期
旧 `template_v2.xlsx` 的一致预期公式用 `$D$1=TODAY()`，旧 `template_universe_daily.xlsx` 用 `2026-05-25` 这种可识别日期。不要把 `B1` 写成裸数字 `20260602` 再调用 `YEAR($B$1)`；Excel 会把它当日期序列号，导致 `s_west_netprofit`、`s_west_eps`、`s_west_instnum_np` 等返回 `#VALUE!`。当前 `make_template_daily.py`、`make_template_weekly.py` 和对应 puller 都会把 `B1` 写成真实 Excel 日期。

### 3. 复用 Excel 进程，谨慎关闭
- `apps[0] if xw.apps else xw.App(visible=True)` —— 复用已开的 Excel
- 只 `wb.close()` 自己 open 的 book，**绝不 `app.quit()`**
- visible=True，让用户能看进度

### 4. Excel autorecover 污染
Excel 异常重启会 auto-recover 上次未保存的 sheet 内容。曾经发生：HK 模板里被恢复了 A 股的 wset 输出。**症状：HK 模板第一列出现 A 股代码**。  
**修复**：清表 + 删 csv + 重建模板 + 重新 pull。

### 5. PB 字段按目标产物取舍
目标产物 `Index Future` 需要的是 PB 市净率，不需要 `board`。仓库历史里验证通过的 PB 公式是 `s_val_pb`；`s_val_pb_new` 在当前 Wind 个人版实测返回 `#VALUE!`，不要再用。

### 5.1 EV/EBITDA 小样本
`s_val_evtoebitda` 已用 600519.SH 和 0700.HK 在 2026-06-02 抽查，均返回数值。该字段保留在 `daily_market.ev_ebitda`，但不是旧 `Index Future` 字段下限；如果个别股票返回空，入库为 NULL，不阻塞看板。

### 6. SW 行业 UDF 港股要加前缀
A 股：`s_info_industry_sw_2021`  
港股：`hks_info_industry_sw_2021`

### 7. fish + python heredoc 会卡死
不要在 fish 里写 `python - <<'PY' ... PY`，会进入 broken 交互态。临时脚本就建文件 + run。

### 8. wset 是数组公式，不能逐行
`template_index_const.xlsx` 里 `sec_name / weight` 列没有逐行公式是正常的—— wset 一个公式从 B3 一次性溢出整个矩阵。这不是 bug。

### 9. OSERROR -609 "Connection is invalid"
通常是 Excel 被系统杀掉（内存吃紧 / 长时间没响应被 watchdog）。修复：关掉无关 workbook、重启 Excel、再拉。

## 六、未做事项（V4 之后）

- ✅ `app/screener.py`：3 套规则 + 行业中位 PE 偏离 + 复合分已可跑；缺失字段会自动跳过对应规则，避免季报/一致预期未采集时误杀全池
- ✅ `app/screener_data.py`：V4 四表 → screener 宽表适配层已补齐，读 `stock_daily + stock_info + stock_membership + index_constituents`
- ✅ `app/dashboard_screener.py`：已从旧 `stock_master` 切到 V4 四表，并支持 A / HK / 多指数 union 过滤
- ✅ 最小特征层：从 `stock_daily` 派生 `amount_1m` 和 `ytd_return`，映射 `mkt_cap_yi → mkt_cap_cny`、`pb → pb_lf`
- ❌ `stock_quarterly`（季报财务因子：营收/净利/ROE/资产负债率）—— 下一阶段再加
- ❌ `stock_forecast_w`（FY1/FY2 EPS、一致预期修正、覆盖券商数）—— 下一阶段再加
- ❌ launchd 定时任务：daily 17:30 / monthly 1st

### 当前选股能力边界

P0/P1 修完后，真实数据路径是：

```text
template_index_const.xlsx → pull_index_const.py → index_constituents / stock_membership / codes_*.csv
template_info.xlsx        → pull_info.py        → stock_info
template_daily.xlsx       → pull_daily.py       → daily_market
daily_market + static_info + monthly_membership + weekly_forecast → app/screener_data.py → app/dashboard_screener.py
```

当前可以稳定做：市场 / 指数成员池过滤、市值、月成交额、PE/PB/EVEBITDA/股息率、行业相对 PE、估值/现金维度复合分、YTD 派生展示。

当前还不能做完整基本面复合选股：`roe_ttm`、`eps_yoy_q`、`eps_yoy_acc`、`eps_fy1_growth`、`fcf` 等仍依赖未来的季频财务和一致预期表。规则引擎现在会在这些字段全空时自动跳过对应规则。

## 七、字段更新频率一览（决定要不要新增表）

| 桶 | 频率 | 字段 | 当前去向 |
|---|---|---|---|
| 永久 | 一次 | name, ipo_date | stock_info |
| 季度变 | 季 | sw_l1, sw_l2, gics_* | stock_info |
| 月度变 | 月 | 指数成员标签, 权重快照 | stock_membership / index_constituents |
| 季度财务 | 季 | revenue, np, roe, gross_margin, debt_ratio, eps | **未实现** |
| 日变 | 日 | close, amount, mkt_cap, pe, pb, divy, ev, weight | stock_daily |
| 事件 | 不定 | 分红, 停牌, ST | 未实现 |
