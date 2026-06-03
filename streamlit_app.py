"""Streamlit Cloud 入口 —— 部署时「Main file path」填本文件 (streamlit_app.py)。

实际看板在 app/dashboard_screener.py; 这里只把 app/ 加入路径后执行它。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app"))

import dashboard_screener  # noqa: E402,F401  (导入即运行看板)
