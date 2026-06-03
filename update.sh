#!/usr/bin/env bash
# 本地日更(Mac + Wind)。拉日频快照 + 一致预期 → 更新 data/wind_history.db
# 用法:  ./update.sh            # 用今天
#        ./update.sh 20260602   # 指定日期
#        PY=/path/to/python ./update.sh   # 指定解释器
set -e
cd "$(dirname "$0")"
DATE=${1:-$(date +%Y%m%d)}
PY=${PY:-python}

echo "📈 日更 $DATE —— 确保: ① Wind 已登录 ② Excel 没在跑别的脚本 ③ 看板/DB 工具已关"
"$PY" scripts/pull_daily.py  --date "$DATE"     # 价量/估值/Beta/profit alert 快照
"$PY" scripts/pull_annual.py --date "$DATE"     # 一致预期 EPS + 周/月修正(会动)

echo ""
echo "✅ data/wind_history.db 已更新。推送后 Streamlit Cloud 会自动重新部署:"
echo "   git add data/wind_history.db && git commit -m \"data $DATE\" && git push"
