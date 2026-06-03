# 基本面量化选股看板 (Equity Screener)

按导师「基本面量化指令集」三块(**估值 / 经营 / 一致预期**)做 A 股 + 港股选股:**硬筛(规则全过)+ 复合分排序(行业内分位)**。数据从 Wind 取,看板用 Streamlit。

## 架构(为什么这么分)

> **Streamlit Cloud 跑不了 Wind**(Wind 是 macOS Excel 插件)。所以拉数在本地、展示在云端:

```
 ┌─ 本地 Mac + Excel + Wind ─┐         ┌─ GitHub ─┐      ┌─ Streamlit Cloud ─┐
 │ scripts/pull_*.py 读模板  │  push   │ 代码 +    │ auto │ streamlit_app.py   │
 │   → data/wind_history.db  │ ──────▶ │ 精简 db   │ ───▶ │ 只读 db, 出看板     │
 └───────────────────────────┘         └──────────┘ 部署  └────────────────────┘
```

## 文件结构
```
equity-screener/
├── streamlit_app.py        # ☁️ Cloud 入口(部署时 Main file 填这个)
├── .streamlit/config.toml  # 主题(专业淡雅)
├── requirements.txt        # 云端依赖(streamlit/pandas/plotly/numpy)
├── requirements-data.txt   # 本地拉数依赖(xlwings/openpyxl)
├── update.sh               # 本地日更脚本
├── app/                    # 看板代码
│   ├── dashboard_screener.py  # 主界面(侧栏三块 + 选股结果/漏斗/复合分/指数)
│   ├── screener.py            # 规则引擎(硬筛 + 复合分, 纯函数)
│   ├── screener_data.py       # 数据层: db → 宽表
│   ├── column_meta.py         # 中央列字典(中文名/格式/口径)
│   └── theme.py               # 配色
├── data/wind_history.db    # 📦 精简 db(5 张表), 云端看板读它 —— 要提交
├── templates/              # Wind 取数模板(本地拉数用)
│   ├── template_static.xlsx / template_daily.xlsx
│   ├── template_annual.xlsx / template_financials.xlsx
│   └── Index Future Valuation Table(Wind)_clean.xlsx  # 源选股表(成员/权重)
├── scripts/                # 本地拉数管线
├── config/codes_a.csv / codes_hk.csv   # 股票池 + 成员标志
└── docs/                   # 管线说明 / 字段盘点
```

## 数据更新频率(关键)

| 表 | 频率 | 命令 | 说明 |
|---|---|---|---|
| **daily_market** | **每天** | `python scripts/pull_daily.py --date YYYYMMDD` | 价量/PE/PB/股息/Beta/profit alert。**唯一真·日更** |
| **annual_fundamental** | 每天/每周 | `python scripts/pull_annual.py --date YYYYMMDD` | 一致预期 EPS + 周/月修正**天天会动**;EPS 实绩/ROE 年度不变 |
| **periodic_financials** | 财报季 | `python scripts/backfill_financials.py --start-year 2026 --end-year 2026 --periods Q1` | 出新财报时补最新一期 |
| static_info | 几月一次 | `python scripts/pull_info.py --date YYYYMMDD` | 行业偶尔调 |
| monthly_membership | 半年一次 | `python scripts/import_membership.py`(无需 Wind) | 指数成分调整时 |

**每天就两步**(已封装进 `update.sh`):
```bash
./update.sh                       # = pull_daily + pull_annual, 写 data/wind_history.db
git add data/wind_history.db && git commit -m "data $(date +%F)" && git push   # Cloud 自动重部署
```

> ⚠️ 月成交额是「**本月累计**」:月初(如每月头几天)拉数时它偏小,别在那几天开「月成交额下限」过滤,否则会误杀。需要按流动性筛就月中/月底再拉。

## 本地首次配置
```bash
pip install -r requirements.txt -r requirements-data.txt
# 确保 Excel + Wind 已装且登录; codes/templates 已在仓库内
```
拉数前提与踩坑见 `docs/SCREENER_PIPELINE_V4.md`(wait_calc 收敛、裸函数名、ODS 原值等)。

## 部署到 Streamlit Cloud
1. 把本文件夹 push 成一个 GitHub 仓库(含 `data/wind_history.db`)。
2. share.streamlit.io → New app → 选该仓库 → **Main file path 填 `streamlit_app.py`**。
3. Deploy。之后每次 `git push` 新的 db,Cloud 自动重新部署。

> db ~30MB,每天提交会让 git 历史变大;在意的话后续可上 [git-lfs](https://git-lfs.com/) 或定期 squash。

## 本地预览
```bash
streamlit run streamlit_app.py        # 或 streamlit run app/dashboard_screener.py
```
