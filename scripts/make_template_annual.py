"""template_annual.xlsx —— 双 sheet [a] / [hk], 年度财务时间序列 (DB 落库为长表)。

严格对齐源表 `Index Future Valuation Table(Wind)` 的年度块:
    - 逐年 EPS 序列 (2011→2025 实际 + 2026E/2027E 前瞻): 实际 s_stm07_is(归母净利)/S_SHARE_TOTAL; 前瞻 s_west_netprofit/S_SHARE_TOTAL
    - 逐年 ROE (s_fa_dupont_roe, 供 5 年平均 ROE)
    - 最新实际财年质量标量: 归母净利、净资产、净负债、EV1、EBITDA (EV/EBITDA、ND/E 在 pull 派生)
    - FY1 一致预期修正: 均值(s_west)/中值(s_est) × 周(-7)/月(-30)

Excel 是宽表 (一年/科目一列), pull_annual.py 反透视成长表 (一行 = 一只股 × 一个财年)。

关键约定 (踩坑沉淀, 见 docs/SCREENER_PIPELINE_V4.md):
    1. Wind UDF 写裸函数名 (=s_stm07_is(...)), 与已验证的 template_daily 一致; Excel 保存自己加 [1]!, 不要手写。
    2. 财年年末写成 literal 字符串 (如 "2025/12/31"), 不用 YEAR($B$1) (会被当日期序列号)。
    3. B1 = as-of date (给 s_west / S_SHARE_TOTAL 取口径), 必须写真 Excel 日期对象; $B$1-7 = 7 日前口径。
    4. **ODS 原样获取: 公式不做任何单位换算 (不写 1000000/100000000)**, 原值入库, 清洗放看板。
    5. EV/EBITDA、PB、股息、profit alert 的「日频口径」在 template_daily; 这里只放财年口径 EV1/EBITDA。
"""
from __future__ import annotations

from datetime import date

from _wind_xl import TEMPLATES_DIR, close_if_open, get_app, load_codes, write_sheet

OUT = TEMPLATES_DIR / "template_annual.xlsx"

DEFAULT_AS_OF_DATE = date(2026, 6, 2)
# 实际年: 回看到这些财年 (含); 前瞻年: 一致预期
ACTUAL_YEARS = list(range(2011, 2026))         # 2011..2025 实际 (对齐源表 15 年)
FORWARD_YEARS = [2026, 2027]                    # 26E / 27E 一致预期
LATEST_FISCAL_YEAR = ACTUAL_YEARS[-1]          # 质量标量锚定的最新实际财年
FY1_YEAR = FORWARD_YEARS[0]                     # 一致预期修正锚定的前瞻首年

# 源表里验证过的 Wind 指标 ID
MID_NET_PROFIT = "W30028333"   # 归母净利 (利润表)
MID_EQUITY = "W38058048"       # 归母净资产 (资产负债表)


def _build_headers_formulas() -> tuple[list[str], list[str]]:
    headers: list[str] = []
    formulas: list[str] = []

    # --- 实际年 EPS (ODS 原值, 无单位换算: 净利/股本) ---
    for y in ACTUAL_YEARS:
        headers.append(f"eps_{y}")
        formulas.append(
            f'=IFERROR(s_stm07_is({{code_ref}},"{MID_NET_PROFIT}","{y}/12/31",1)'
            f"/S_SHARE_TOTAL({{code_ref}},$B$1),\"\")"
        )

    # --- 前瞻年 EPS (一致预期) ---
    for y in FORWARD_YEARS:
        headers.append(f"eps_{y}E")
        formulas.append(
            f"=IFERROR(s_west_netprofit({{code_ref}},{y},$B$1,180)"
            f"/S_SHARE_TOTAL({{code_ref}},$B$1),\"\")"
        )

    # --- 逐年 ROE (供 5 年平均 ROE; 杜邦 ROE / 100 = 小数) ---
    for y in ACTUAL_YEARS:
        headers.append(f"roe_{y}")
        formulas.append(f'=IFERROR(s_fa_dupont_roe({{code_ref}},"{y}/12/31")/100,"")')

    # --- 最新实际财年质量标量 (锚定 LATEST_FISCAL_YEAR, ODS 原值) ---
    fy = LATEST_FISCAL_YEAR
    headers.append("net_profit_raw")
    formulas.append(f'=IFERROR(s_stm07_is({{code_ref}},"{MID_NET_PROFIT}","{fy}/12/31",1),"")')
    headers.append("equity_raw")
    formulas.append(f'=IFERROR(s_stm07_bs({{code_ref}},"{MID_EQUITY}","{fy}/12/31",1),"")')
    headers.append("net_debt_raw")
    formulas.append(f'=IFERROR(s_fa_netdebt({{code_ref}},"{fy}/12/31"),"")')
    headers.append("ev1_raw")
    formulas.append(f'=IFERROR(s_val_ev1({{code_ref}},"{fy}/12/31"),"")')
    headers.append("ebitda_raw")
    formulas.append(f'=IFERROR(s_fa_ebitda({{code_ref}},"{fy}/12/31"),"")')

    # --- FY1 一致预期净利 修正 (本期口径 vs 7日/30日前; 均值 s_west / 中值 s_est) ---
    fy1 = FY1_YEAR
    headers.append("np_avg_rev_1w")
    formulas.append(f'=IFERROR(s_west_netprofit({{code_ref}},{fy1},$B$1,180)/s_west_netprofit({{code_ref}},{fy1},$B$1-7,180)-1,"")')
    headers.append("np_avg_rev_1m")
    formulas.append(f'=IFERROR(s_west_netprofit({{code_ref}},{fy1},$B$1,180)/s_west_netprofit({{code_ref}},{fy1},$B$1-30,180)-1,"")')
    headers.append("np_med_rev_1w")
    formulas.append(f'=IFERROR(s_est_mediannetprofit({{code_ref}},{fy1},$B$1)/s_est_mediannetprofit({{code_ref}},{fy1},$B$1-7)-1,"")')
    headers.append("np_med_rev_1m")
    formulas.append(f'=IFERROR(s_est_mediannetprofit({{code_ref}},{fy1},$B$1)/s_est_mediannetprofit({{code_ref}},{fy1},$B$1-30)-1,"")')

    return headers, formulas


def main() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    codes_a = load_codes("A")
    codes_hk = load_codes("HK")
    headers, formulas = _build_headers_formulas()

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

        for sheet_name, codes in (("a", codes_a), ("hk", codes_hk)):
            write_sheet(
                wb.sheets[sheet_name],
                codes,
                headers,
                formulas,
                params={"B1": DEFAULT_AS_OF_DATE},
            )
            wb.sheets[sheet_name].range("B1").number_format = "yyyy-mm-dd"

        wb.save(str(OUT))
        print(
            f"✅ {OUT.name}  sheets=[a:{len(codes_a)}×{len(headers)} "
            f"hk:{len(codes_hk)}×{len(headers)}]  "
            f"actual={ACTUAL_YEARS[0]}..{ACTUAL_YEARS[-1]} forward={FORWARD_YEARS}"
        )
    finally:
        app.calculation = prev_calc
        wb.close()


if __name__ == "__main__":
    main()
