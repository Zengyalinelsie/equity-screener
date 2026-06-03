# Streamlit 部署踩坑记录

## 刷新后页面白屏，只剩右上角 Deploy

### 现象

- Streamlit Cloud 或本地 `streamlit run streamlit_app.py` 第一次打开正常。
- 浏览器刷新后页面变成空白，只剩 Streamlit 前端壳的 `Deploy` 按钮。
- `/_stcore/health` 仍返回 `ok`。
- 服务端日志没有 Python traceback。

### 根因

`streamlit_app.py` 曾经只做了一次普通 import：

```python
sys.path.insert(0, str(Path(__file__).parent / "app"))
import dashboard_screener
```

第一次打开时，Python 会导入并执行 `dashboard_screener.py` 的顶层 Streamlit 代码，所以页面正常。

刷新页面时，Streamlit 会在同一个 Python 进程里重新执行 `streamlit_app.py`。但 `dashboard_screener` 已经在 `sys.modules` import 缓存里，第二次 `import dashboard_screener` 不会重新执行模块顶层代码。结果本次 rerun 没有产生任何 Streamlit 元素，浏览器只剩空白前端壳。

### 修复

入口文件必须确保每次 Streamlit rerun 都执行真实页面脚本。当前写法：

```python
import runpy
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent / "app"
sys.path.insert(0, str(APP_DIR))

runpy.run_path(str(APP_DIR / "dashboard_screener.py"), run_name="__main__")
```

这样每次刷新都会重新执行 `app/dashboard_screener.py`，不会被 import 缓存吞掉。

### 验证方法

用 Streamlit testing 连续跑两次入口文件：

```bash
python3 - <<'PY'
from streamlit.testing.v1 import AppTest

for i in range(2):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30)
    app.run()
    print(
        "run", i + 1,
        "exceptions", len(app.exception),
        "markdown", len(app.markdown),
        "dataframes", len(app.dataframe),
        "tabs", len(app.tabs),
    )
PY
```

正确结果应当是两次都有页面元素。例如：

```text
run 1 exceptions 0 markdown 5 dataframes 3 tabs 4
run 2 exceptions 0 markdown 5 dataframes 3 tabs 4
```

错误写法下，第二次会接近：

```text
run 2 exceptions 0 markdown 0 dataframes 0 tabs 0
```

### 排查顺序

1. 访问 `/_stcore/health`。如果是 `ok`，说明服务进程还活着。
2. 看服务端日志。没有 traceback 时，不要只盯 Python 异常。
3. 做一个最小 Streamlit 页测试。如果最小页刷新正常，问题在正式入口或正式页面代码。
4. 用 `AppTest` 连续跑两次入口文件。第二次没有元素时，优先检查是否用了 `import some_page` 作为入口。

### 规则

- 不要用普通 `import dashboard_xxx` 作为 Streamlit Cloud 入口的唯一执行方式。
- 如果页面代码放在子目录脚本里，入口用 `runpy.run_path(...)` 或把页面重构为显式 `main()` 并在入口中调用。
- 如果重构成 `main()`，不要依赖模块 import 副作用来渲染页面。
