"""template_financials.xlsx —— 双 sheet [a] / [hk], 单个报告期的利润表 + 现金流全科目。

对齐源表 `Index Future Valuation Table(Wind)` 的财报科目块 (ER:FH)。一次只算一个报告期
(B1 = 报告期末), 由 backfill_financials.py 对每一年的【年报 12-31 + 半年报 06-30】一期一期回拉,
攒进 periodic_financials 长表。这样不用把好几年塞进一张大宽表 (macOS Excel 一次算太多会假死)。

只取 Wind 原值 (ODS, 无单位换算), 同比/毛利率/营业利润/FCF 等派生放 pull_financials.py。
周转天数(应收/应付/存货)A 股用 s_fa_*turndays、港股用 hks_fa_*turndays, 故 FORMULAS 拆 A/HK 两份。

约定 (踩坑沉淀):
    1. Wind UDF 写裸函数名, 与已验证的 template_daily 一致 (macOS Wind add-in 可裸调用,
       Excel 保存时自己加 [1]! 外部引用 —— 不要手写 [1]!)。
    2. 报告期末用 TEXT($B$1,"yyyy/mm/dd") 传给 s_stm07_* (源表是字符串日期); EPS 用 $B$1 日期对象。
    3. B1 必须写真 Excel 日期对象。S_FA_EPS_basic2 必须带 "Cur=CNY" 才出数 (实测 A/HK 都正常, 港股 EPS 折成人民币)。
"""
from __future__ import annotations

from datetime import date

from _wind_xl import TEMPLATES_DIR, close_if_open, get_app, load_codes, write_sheet

OUT = TEMPLATES_DIR / "template_financials.xlsx"
DEFAULT_PERIOD = date(2025, 12, 31)   # 默认一个年报期; pull/backfill 会改 B1

_D = 'TEXT($B$1,"yyyy/mm/dd")'        # s_stm07_* 用字符串日期

# (表头, 公式) —— 只放 Wind 原值科目 (ODS, 无单位换算), 派生在 pull 端算
HEADERS = [
    "revenue_raw", "cogs_raw",
    "selling_exp_raw", "admin_exp_raw", "rd_exp_raw",
    "interest_expense_raw", "interest_income_raw",
    "pretax_profit_raw", "net_profit_raw",
    "operating_cashflow_raw", "capex_raw",
    "basic_eps",
    "ar_turn_days", "ap_turn_days", "inv_turn_days",   # 周转天数 (A/HK 函数前缀不同)
]

# 前 12 列 A/HK 相同
_BASE = [
    f'=IFERROR(s_stm07_is({{code_ref}},"W70156729",{_D},1),"")',   # 营收
    f'=IFERROR(s_stm07_is({{code_ref}},"W75682424",{_D},1),"")',   # 营业成本
    f'=IFERROR(s_stm07_is({{code_ref}},"W76031679",{_D},1),"")',   # 销售费用
    f'=IFERROR(s_stm07_is({{code_ref}},"W70752487",{_D},1),"")',   # 管理费用
    f'=IFERROR(s_stm07_is_103({{code_ref}},{_D},1),"")',           # 研发费用
    f'=IFERROR(s_stm07_is_104({{code_ref}},{_D},1),"")',           # 利息支出
    f'=IFERROR(s_stm07_is_105({{code_ref}},{_D},1),"")',           # 利息收入
    f'=IFERROR(s_stm07_is({{code_ref}},"W72946623",{_D},1),"")',   # 税前利润
    f'=IFERROR(s_stm07_is({{code_ref}},"W30028333",{_D},1),"")',   # 归母净利
    f'=IFERROR(s_stm07_cs({{code_ref}},"W77130581",{_D},1),"")',   # 经营现金流
    f'=IFERROR(s_stm07_cs({{code_ref}},"W77745895",{_D},1),"")',   # Capex
    '=IFERROR(S_FA_EPS_basic2({code_ref},$B$1,"Cur=CNY"),"")',     # basic EPS (必须带 Cur 才出数, CNY 折算 A/HK 同币种)
]
# 周转天数: A 股 s_fa_*turndays (但应付是 fa_apturndays, 无 s_ 前缀!) / 港股 hks_fa_*turndays
_TURN_A = [
    f'=IFERROR(s_fa_arturndays({{code_ref}},{_D}),"")',    # 应收账款周转天数
    f'=IFERROR(fa_apturndays({{code_ref}},{_D}),"")',      # 应付账款周转天数 (A 股实测无 s_ 前缀)
    f'=IFERROR(s_fa_invturndays({{code_ref}},{_D}),"")',   # 存货周转天数
]
_TURN_HK = [
    f'=IFERROR(hks_fa_arturndays({{code_ref}},{_D}),"")',
    f'=IFERROR(hks_fa_apturndays({{code_ref}},{_D}),"")',
    f'=IFERROR(hks_fa_invturndays({{code_ref}},{_D}),"")',
]
FORMULAS_A = _BASE + _TURN_A
FORMULAS_HK = _BASE + _TURN_HK


def main() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    codes_a = load_codes("A")
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

        for sheet_name, codes, formulas in (("a", codes_a, FORMULAS_A), ("hk", codes_hk, FORMULAS_HK)):
            write_sheet(wb.sheets[sheet_name], codes, HEADERS, formulas,
                        params={"B1": DEFAULT_PERIOD})
            wb.sheets[sheet_name].range("B1").number_format = "yyyy-mm-dd"

        wb.save(str(OUT))
        print(
            f"✅ {OUT.name}  sheets=[a:{len(codes_a)}×{len(HEADERS)} "
            f"hk:{len(codes_hk)}×{len(HEADERS)}]  period={DEFAULT_PERIOD} (单报告期, backfill 改 B1)"
        )
    finally:
        app.calculation = prev_calc
        wb.close()


if __name__ == "__main__":
    main()
