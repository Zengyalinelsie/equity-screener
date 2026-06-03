"""template_static.xlsx —— 双 sheet [a] / [hk], 公司基础信息 (永久 + 季度变).

字段:
    [a] sheet: name, sw_l1, sw_l2, ipo_date
    [hk] sheet: name, sw_l1, sw_l2, ipo_date

说明: 目标产物 Index Future 不使用上市板/board；Wind 个人版里
`s_info_listboard` 也会返回 #NAME?，所以模板不再采这个字段。

UDF 全是裸函数 (Wind add-in 已全局注册).
"""
from __future__ import annotations

from pathlib import Path

from _wind_xl import TEMPLATES_DIR, get_app, close_if_open, load_codes, write_sheet

OUT = TEMPLATES_DIR / "template_static.xlsx"

HEADERS_A = ["name", "sw_l1", "sw_l2", "ipo_date"]
FORMULAS_A = [
    "=S_INFO_NAME({code_ref})",
    "=s_info_industry_sw_2021({code_ref},$B$1,1)",
    "=s_info_industry_sw_2021({code_ref},$B$1,2)",
    "=s_ipo_listeddate({code_ref})",
]

HEADERS_HK = ["name", "sw_l1", "sw_l2", "ipo_date"]
FORMULAS_HK = [
    "=S_INFO_NAME({code_ref})",
    "=hks_info_industry_sw_2021({code_ref},$B$1,1)",
    "=hks_info_industry_sw_2021({code_ref},$B$1,2)",
    "=s_ipo_listeddate({code_ref})",
]


def main():
    TEMPLATES_DIR.mkdir(exist_ok=True)
    codes_a  = load_codes("A")
    codes_hk = load_codes("HK")

    app = get_app()
    close_if_open(app, OUT.name)
    if OUT.exists():
        OUT.unlink()

    wb = app.books.add()
    prev_calc = app.calculation
    try:
        app.calculation = "manual"
        while len(wb.sheets) > 1:
            wb.sheets[-1].delete()
        wb.sheets[0].name = "a"
        wb.sheets.add("hk", after=wb.sheets[0])

        write_sheet(wb.sheets["a"],  codes_a,  HEADERS_A,  FORMULAS_A,
                    params={"B1": "20260602"})
        write_sheet(wb.sheets["hk"], codes_hk, HEADERS_HK, FORMULAS_HK,
                    params={"B1": "20260602"})

        wb.save(str(OUT))
        print(f"✅ {OUT.name}  sheets=[a:{len(codes_a)}×{len(HEADERS_A)}  hk:{len(codes_hk)}×{len(HEADERS_HK)}]  saved")
    finally:
        app.calculation = prev_calc
        wb.close()


if __name__ == "__main__":
    main()
