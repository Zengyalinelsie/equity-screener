"""Streamlit Cloud 入口 —— 部署时「Main file path」填本文件 (streamlit_app.py)。

实际看板在 app/dashboard_screener.py; 这里每次 Streamlit rerun 都执行该脚本。
"""
import runpy
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent / "app"
sys.path.insert(0, str(APP_DIR))

runpy.run_path(str(APP_DIR / "dashboard_screener.py"), run_name="__main__")
