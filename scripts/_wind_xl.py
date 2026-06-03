"""共享 xlwings 工具 —— Wind 模板生成/拉取脚本复用。"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import xlwings as xw


# ============ Wind 异步取数收敛 (照搬 collect_universe_daily 的双保险, 见 DATA_PIPELINE_PITFALLS 坑4/5/14) ============
MIN_WAIT = 5.0          # 写 B1 后最小等待 (Wind 启动 fetch 本身要 3-5s)
POLL = 1.5              # 轮询间隔
STABLE_NEEDED = 2       # 连续 N 次一致才算收敛
TIMEOUT = 600           # 单期最大等 10 分钟
PLACEHOLDERS = ("fetch", "提取", "请求", "loading", "计算中", "正在")


def read_grid(ws):
    """读数据区 B3:末列末行 的二维值 (不含 A 列代码)。"""
    a = ws.range("A3").expand("down").value
    if a is None:
        return []
    if not isinstance(a, list):
        a = [a]
    n = len(a)
    hdr = ws.range("B2").expand("right").value
    ncol = len(hdr) if isinstance(hdr, list) else (1 if hdr is not None else 0)
    if ncol == 0:
        return []
    g = ws.range((3, 2), (2 + n, 1 + ncol)).value
    if n == 1:
        g = [g]
    return [r if isinstance(r, list) else [r] for r in g]


def _has_data(grid) -> bool:
    if not grid:
        return False
    non_null = sum(1 for row in grid for v in row if v is not None)
    return non_null > len(grid) * 2


def _is_fetching(grid) -> bool:
    for row in grid:
        for v in row:
            if isinstance(v, str) and any(p in v.lower() for p in PLACEHOLDERS):
                return True
    return False


def _flat(grid):
    return tuple(tuple("" if v is None else v for v in row) for row in grid)


def wait_calc(ws, prev_flat=None, min_wait: float = MIN_WAIT, log=None):
    """写 B1 后等收敛: 不主动 calculate (坑14 会崩 Excel), 只 sleep+轮询。

    返回 (converged: bool, flat)。
    - 占位符检测: 出现 fetch/正在… → 继续等
    - 防陈旧: 读数 == 上一期 flat → 还没换, 继续等
    - 稳定: 连续 STABLE_NEEDED 次一致且有数据 → 收敛
    """
    time.sleep(min_wait)
    prev = None
    stable = 0
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            cur = read_grid(ws)
        except Exception:
            time.sleep(POLL)
            continue
        if not cur or _is_fetching(cur):
            stable = 0
            prev = None
            time.sleep(POLL)
            continue
        flat = _flat(cur)
        if prev_flat is not None and flat == prev_flat:   # 与上一期完全一样 = 还没换
            stable = 0
            prev = None
            time.sleep(POLL)
            continue
        if prev is not None and flat == prev and _has_data(cur):
            stable += 1
            if stable >= STABLE_NEEDED:
                return True, flat
        else:
            stable = 0
        prev = flat
        time.sleep(POLL)
    return False, prev



ROOT = Path(__file__).parent.parent.resolve()
TEMPLATES_DIR = ROOT / "templates"
CONFIG_DIR = ROOT / "config"
CODES_A = CONFIG_DIR / "codes_a.csv"
CODES_HK = CONFIG_DIR / "codes_hk.csv"

_STUB_A = [("600519.SH", "贵州茅台"), ("000001.SZ", "平安银行")]
_STUB_HK = [("00700.HK", "腾讯控股"), ("00005.HK", "汇丰控股")]


def get_app() -> xw.App:
    apps = list(xw.apps)
    if apps:
        app = apps[0]
        print(f"复用 Excel pid={app.pid}")
    else:
        app = xw.App(visible=True)
        print(f"新建 Excel pid={app.pid}")
    app.display_alerts = False
    return app


def load_codes(market: str, stub_if_missing: bool = True) -> list[tuple[str, str]]:
    """读 codes_a.csv / codes_hk.csv → [(wind_code, name), ...]."""
    path = CODES_A if market == "A" else CODES_HK
    stub = _STUB_A if market == "A" else _STUB_HK
    if not path.exists():
        if stub_if_missing:
            print(f"⚠️  {path.name} 不存在, 用 stub")
            return stub
        raise FileNotFoundError(path)
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("wind_code") or "").strip()
            name = (row.get("name") or "").strip()
            if code:
                out.append((code, name))
    if not out and stub_if_missing:
        return stub
    print(f"📋 {path.name}: {len(out)} codes")
    return out


def close_if_open(app: xw.App, name: str) -> None:
    for b in list(app.books):
        try:
            if Path(b.fullname).name == name:
                print(f"   关闭旧 {name}")
                b.close()
        except Exception:
            pass


def write_sheet(ws, codes: list[tuple[str, str]], headers: list[str], formulas: list[str],
                params: dict[str, object] | None = None) -> None:
    """单 sheet 通用写入: A=wind_code, B+=UDF 公式列.

    headers: 数据列表头(不含 wind_code), 长度 = N
    formulas: 模板公式, 占位符 {code_ref}/{row}, 长度 = N (跟 headers 对齐)
    params: {"B1": date(...), ...} → 写在 row 1；带 YEAR(...) 的 Wind 公式必须用 Excel 日期对象
    """
    if params:
        for cell, val in params.items():
            ws.range(cell).value = val
    ws.range("A2").value = "wind_code"
    for ci, h in enumerate(headers, start=2):
        ws.range((2, ci)).value = h
    if not codes:
        return
    # 批量写代码列
    n_rows = len(codes)
    ws.range((3, 1), (2 + n_rows, 1)).value = [[c] for c, _ in codes]
    # 逐列批量写公式
    for fi, fmla in enumerate(formulas):
        ci = 2 + fi
        col = [[fmla.format(code_ref=f"$A{ri}", row=ri)] for ri in range(3, 3 + n_rows)]
        ws.range((3, ci), (2 + n_rows, ci)).formula = col
