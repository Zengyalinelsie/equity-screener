"""静态校验 4 类 Wind 模板生成脚本，提前发现拼写/回归问题（不连 Wind）。

校验项:
    1. 4 个 make 脚本存在
    2. 文本扫描出现的 Wind 函数族，覆盖每类模板的核心函数
    3. 回归守护（V5 修过的坑）:
       - annual / financials 不得用 `YEAR(` 取年份（会被当日期序列号，旧坑）
       - 不要手写 `[1]!` 前缀（macOS Wind add-in 裸调用即可, Excel 保存自己加; 手写会变坏链接）

说明: 公式现在在 _build_headers_formulas() 内动态生成, 所以用源码文本扫描而非 literal_eval。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()

SCRIPTS = {
    "static": ROOT / "scripts" / "make_template_info.py",
    "daily": ROOT / "scripts" / "make_template_daily.py",
    "annual": ROOT / "scripts" / "make_template_annual.py",
    "financials": ROOT / "scripts" / "make_template_financials.py",
}

# 每类模板期望出现的核心 Wind 函数（小而高置信，避免误报）
REQUIRED_BY_TEMPLATE = {
    "static": {"s_info_name", "s_info_industry_sw_2021", "s_ipo_listeddate"},
    "daily": {"s_dq_close", "s_val_ev", "s_val_pe_ttm", "s_risk_betar24"},
    "annual": {"s_stm07_is", "s_share_total", "s_west_netprofit",
               "s_fa_dupont_roe", "s_fa_netdebt", "s_stm07_bs",
               "s_val_ev1", "s_fa_ebitda", "s_est_mediannetprofit"},
    "financials": {"s_stm07_is", "s_stm07_cs", "s_stm07_is_103",
                   "s_stm07_is_104", "s_stm07_is_105", "s_fa_eps_basic2",
                   "s_fa_arturndays", "s_fa_invturndays",
                   "hks_fa_arturndays", "hks_fa_invturndays"},
}
NO_YEAR_FN = {"annual", "financials"}     # 禁用 YEAR( 取年份
NO_BRACKET1 = set(SCRIPTS)                # 任何模板都不该手写 [1]!

WIND_FN = re.compile(r"\b([a-z_]*s_[a-z0-9_]+|hks_[a-z0-9_]+|wset|i_[a-z0-9_]+)\s*\(", re.I)


def _functions(text: str) -> set[str]:
    return {m.lower() for m in WIND_FN.findall(text)}


def _rendered_formulas(path) -> list[str]:
    """import make 模块, 取渲染后的公式 (动态 f-string 拼出来的函数名只有渲染后才可见)。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "_build_headers_formulas"):
        return list(mod._build_headers_formulas()[1])
    out: list[str] = []
    for attr in ("FORMULAS", "FORMULAS_A", "FORMULAS_HK", "FORMULAS_INDEX"):
        if hasattr(mod, attr):
            out += list(getattr(mod, attr))
    return out


def main() -> int:
    failed = False
    print("# Wind Template Static Validation (V5, 4 类)")
    for name, path in SCRIPTS.items():
        print(f"\n## {name}: {path.name}")
        if not path.exists():
            print(f"ERROR: MISSING ({path})")
            failed = True
            continue
        try:
            formulas = _rendered_formulas(path)
        except Exception as e:
            print(f"ERROR: 无法导入渲染公式: {e}")
            failed = True
            continue
        formula_blob = "\n".join(formulas)
        fns = _functions(formula_blob)
        print("functions: " + (", ".join(sorted(fns)) or "(none)"))

        missing = REQUIRED_BY_TEMPLATE.get(name, set()) - fns
        if missing:
            failed = True
            print("ERROR: missing core functions: " + ", ".join(sorted(missing)))

        if name in NO_BRACKET1 and "[1]!" in formula_blob:
            failed = True
            print("ERROR: 不要手写 `[1]!` 前缀（裸函数名即可，Excel 保存自己加）")

        if name in NO_YEAR_FN and re.search(r"YEAR\s*\(", formula_blob):
            failed = True
            print("ERROR: 不应使用 YEAR(...) 取年份（会被当日期序列号，旧坑）")

        if not missing:
            print("OK")

    print("\n" + ("❌ Validation failed" if failed else "✅ Validation passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
