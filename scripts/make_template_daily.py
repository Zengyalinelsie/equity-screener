"""template_daily.xlsx —— 三 sheet [a] / [hk] / [index], 日频市场快照.

[a] sheet 字段:
    close, volume, amount, turnover_rate, mkt_cap_raw, total_mkt_cap_raw, ev1_raw,
    mq_amount_raw, pe_ttm, pb, div_yield, ev_ebitda, beta_24m, profit_alert, ytd_pctchange_raw,
    fy1_np_avg, fy1_eps, fy1_instnum, fy1_np_std, fy1_np_median, fy1_np_max, fy1_np_min,
    fy2_np_avg, fy2_eps, fy2_instnum, fy2_np_std, fy2_np_median, fy2_np_max, fy2_np_min,
    roe_fwd,
    iw_50, iw_300, iw_500, iw_1000

[hk] sheet 字段:
    close, volume, amount, turnover_rate, mkt_cap_raw, total_mkt_cap_raw, ev1_raw,
    mq_amount_raw, pe_ttm, pb, div_yield, ev_ebitda, beta_24m, profit_alert, ytd_pctchange_raw,
    fy1_np_avg, fy1_eps, fy1_instnum, fy1_np_std, fy1_np_median, fy1_np_max, fy1_np_min,
    fy2_np_avg, fy2_eps, fy2_instnum, fy2_np_std, fy2_np_median, fy2_np_max, fy2_np_min,
    roe_fwd,
    iw_hsi, iw_hscei, iw_hstech

[index] sheet 字段:
        close, pe_ttm, pb, div_yield, fy1_eps

注意: 目标产物 Index Future 使用 PB 市净率，已验证公式是 s_val_pb。
      港股不再用 s_val_pb_new（实测 #VALUE!）。
    股票收盘价沿用旧 stock/panel 模板的 s_dq_close(..., 3)。
    金额字段不在模板内做单位/币种转换，ODS 原样接收 Wind 返回值。
        指数成分权重必须日频更新：A 股只采 A 股指数权重，港股只采港股指数权重。
        monthly_membership 只作为代码池/兜底，不再作为每日权重主源。
        一致预期类指标并入 daily，每个交易日刷新；不再等 weekly 模板。
"""
from __future__ import annotations

from datetime import date

from _wind_xl import TEMPLATES_DIR, get_app, close_if_open, load_codes, write_sheet

OUT = TEMPLATES_DIR / "template_daily.xlsx"
DEFAULT_AS_OF_DATE = date(2026, 6, 2)

INDEX_DAILY_CODES = [
    ("000016.SH", "上证50"),
    ("000300.SH", "沪深300"),
    ("000852.SH", "中证1000"),
    ("000905.SH", "中证500"),
    ("801010.SI", "农林牧渔"),
    ("801030.SI", "基础化工"),
    ("801040.SI", "钢铁"),
    ("801050.SI", "有色金属"),
    ("801080.SI", "电子"),
    ("801110.SI", "家用电器"),
    ("801150.SI", "医药生物"),
    ("801160.SI", "公用事业"),
    ("801170.SI", "交通运输"),
    ("801180.SI", "房地产"),
    ("801200.SI", "商贸零售"),
    ("801780.SI", "银行"),
    ("HSCEI.HI", "恒生中国企业"),
    ("HSCI.HI", "恒生综合指数"),
    ("HSCNCI.HI", "恒生中国内地企业"),
    ("HSI.HI", "恒生指数"),
    ("HSTECH.HI", "恒生科技"),
    ("HSCI10.HI", "恒生综合能源业"),
    ("HSCI20.HI", "恒生综合原材料业"),
    ("HSCICD.HI", "恒生综合非必需性消费业"),
    ("HSCIFD.HI", "恒生综合必需性消费业"),
    ("HSCIHC.HI", "恒生综合医疗保健业"),
    ("HSCIIN.HI", "恒生综合工业"),
    ("HSCIIT.HI", "恒生综合资讯科技业"),
    ("HSCIMT.HI", "恒生综合综合企业"),
    ("HSCIOG.HI", "恒生综合地产建筑业"),
    ("HSCIRE.HI", "恒生综合金融业"),
    ("HSCITL.HI", "恒生综合电讯业"),
    ("HSCIUT.HI", "恒生综合公用事业"),
]

HEADERS_A = [
    "close", "volume", "amount", "turnover_rate", "mkt_cap_raw",
    "total_mkt_cap_raw", "ev1_raw", "mq_amount_raw",
    "pe_ttm", "pb", "div_yield", "ev_ebitda", "beta_24m", "profit_alert", "ytd_pctchange_raw",
    "fy1_np_avg", "fy1_eps", "fy1_instnum", "fy1_np_std", "fy1_np_median", "fy1_np_max", "fy1_np_min",
    "fy2_np_avg", "fy2_eps", "fy2_instnum", "fy2_np_std", "fy2_np_median", "fy2_np_max", "fy2_np_min",
    "roe_fwd",
    "iw_50", "iw_300", "iw_500", "iw_1000",
]
FORMULAS_A = [
    "=s_dq_close({code_ref},$B$1,3)",
    "=s_dq_volume({code_ref},$B$1)",
    "=s_dq_amount({code_ref},$B$1)",
    "=s_dq_turn({code_ref},$B$1)",
    "=s_val_mv({code_ref},$B$1)",
    "=s_val_ev({code_ref},$B$1)",
    "=s_val_ev1({code_ref},$B$1)",
    "=IFERROR(s_mq_amount({code_ref},$B$1),\"\")",
    "=s_val_pe_ttm({code_ref},$B$1)",
    "=s_val_pb_lf({code_ref},$B$1)",
    "=s_val_dividendyield2({code_ref},$B$1)",
    "=s_val_evtoebitda({code_ref},$B$1)",
    "=s_risk_betar24({code_ref},$B$1)",
    "=s_profitnotice_changeratio({code_ref},$B$1)",
    "=IFERROR(i_pq_pctchange({code_ref},TEXT(DATE(YEAR($B$1),1,1),\"yyyy-mm-dd\"),$B$1),\"\")",
    "=s_west_netprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_eps({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_instnum_np({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_stdnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_mediannetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_maxnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_minnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_netprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_eps({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_instnum_np({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_stdnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_mediannetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_maxnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_minnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_avgroe({code_ref},YEAR($B$1),$B$1,180)",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"000016.SH\"),\"\")",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"000300.SH\"),\"\")",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"000905.SH\"),\"\")",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"000852.SH\"),\"\")",
]

HEADERS_HK = [
    "close", "volume", "amount", "turnover_rate", "mkt_cap_raw",
    "total_mkt_cap_raw", "ev1_raw", "mq_amount_raw",
    "pe_ttm", "pb", "div_yield", "ev_ebitda", "beta_24m", "profit_alert", "ytd_pctchange_raw",
    "fy1_np_avg", "fy1_eps", "fy1_instnum", "fy1_np_std", "fy1_np_median", "fy1_np_max", "fy1_np_min",
    "fy2_np_avg", "fy2_eps", "fy2_instnum", "fy2_np_std", "fy2_np_median", "fy2_np_max", "fy2_np_min",
    "roe_fwd",
    "iw_hsi", "iw_hscei", "iw_hstech",
]
FORMULAS_HK = [
    "=s_dq_close({code_ref},$B$1,3)",
    "=s_dq_volume({code_ref},$B$1)",
    "=s_dq_amount({code_ref},$B$1)",
    "=s_dq_turn({code_ref},$B$1)",
    "=s_val_mv({code_ref},$B$1)",
    "=s_val_ev({code_ref},$B$1)",
    "=s_val_ev1({code_ref},$B$1)",
    "=IFERROR(s_mq_amount({code_ref},$B$1),\"\")",
    "=s_val_pe_ttm({code_ref},$B$1)",
    "=s_val_pb({code_ref},$B$1)",
    "=s_val_dividendyield2({code_ref},$B$1)",
    "=s_val_evtoebitda({code_ref},$B$1)",
    "=s_risk_betar24({code_ref},$B$1)",
    "=s_profitnotice_changeratio({code_ref},$B$1)",
    "=IFERROR(i_pq_pctchange({code_ref},TEXT(DATE(YEAR($B$1),1,1),\"yyyy-mm-dd\"),$B$1),\"\")",
    "=s_west_netprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_eps({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_instnum_np({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_stdnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_mediannetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_maxnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_minnetprofit({code_ref},YEAR($B$1),$B$1,180)",
    "=s_west_netprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_eps({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_instnum_np({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_stdnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_mediannetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_maxnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_minnetprofit({code_ref},YEAR($B$1)+1,$B$1,180)",
    "=s_west_avgroe({code_ref},YEAR($B$1),$B$1,180)",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"HSI.HI\"),\"\")",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"HSCEI.HI\"),\"\")",
    "=IFERROR(s_info_indexweight({code_ref},$B$1,\"HSTECH.HI\"),\"\")",
]

HEADERS_INDEX = ["close", "pe_ttm", "pb", "div_yield", "fy1_eps"]
FORMULAS_INDEX = [
    "=s_dq_close({code_ref},$B$1)",
    "=s_val_pe_ttm({code_ref},$B$1)",
    "=s_val_pb_lf({code_ref},$B$1)",
    "=s_val_dividendyield2({code_ref},$B$1)",
    "=s_west_eps({code_ref},YEAR($B$1),$B$1,180)",
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
        wb.sheets.add("index", after=wb.sheets["hk"])

        write_sheet(wb.sheets["a"],  codes_a,  HEADERS_A,  FORMULAS_A,
                    params={"B1": DEFAULT_AS_OF_DATE})
        write_sheet(wb.sheets["hk"], codes_hk, HEADERS_HK, FORMULAS_HK,
                    params={"B1": DEFAULT_AS_OF_DATE})
        write_sheet(wb.sheets["index"], INDEX_DAILY_CODES, HEADERS_INDEX, FORMULAS_INDEX,
                    params={"B1": DEFAULT_AS_OF_DATE})
        for sheet_name in ("a", "hk", "index"):
            wb.sheets[sheet_name].range("B1").number_format = "yyyy-mm-dd"

        wb.save(str(OUT))
        print(
            f"✅ {OUT.name}  sheets=[a:{len(codes_a)}×{len(HEADERS_A)}  "
            f"hk:{len(codes_hk)}×{len(HEADERS_HK)}  "
            f"index:{len(INDEX_DAILY_CODES)}×{len(HEADERS_INDEX)}]  saved"
        )
    finally:
        app.calculation = prev_calc
        wb.close()


if __name__ == "__main__":
    main()
