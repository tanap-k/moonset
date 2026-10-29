"""ทดสอบ moonset แบบไม่ต้องต่อเน็ต ด้วยบริษัทสมมติ 2 แบบ (หุ้นเติบโต และหุ้นที่รายงานงบเป็น USD)

รัน: python test_offline.py
"""
import pandas as pd

import moonset


class FakeTicker:
    """จำลองหน้าตาข้อมูลของ yfinance.Ticker (แถว = รายการ, คอลัมน์ = วันสิ้นปีบัญชี เรียงใหม่ -> เก่า)"""

    def __init__(self, years, income, balance, cashflow, prices, info, fx=None, splits=None):
        cols = [pd.Timestamp(f"{y}-12-31") for y in years][::-1]
        mk = lambda d: pd.DataFrame({k: v[::-1] for k, v in d.items()}, index=cols).T
        self.income_stmt, self.balance_sheet, self.cashflow = mk(income), mk(balance), mk(cashflow)
        self._prices, self.info, self._fx = prices, info, fx
        self.fx_factory = lambda sym: FakeFx(self._fx)
        splits = splits or {}
        self.splits = pd.Series(list(splits.values()), dtype=float,
                                index=pd.DatetimeIndex([pd.Timestamp(d) for d in splits]))

    def history(self, period="10y", auto_adjust=False):
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in self._prices]).tz_localize("Asia/Bangkok")
        return pd.DataFrame({"Close": list(self._prices.values())}, index=idx)


class FakeFx:
    def __init__(self, rates):
        self.rates = rates

    def history(self, period="10y"):
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in self.rates])
        return pd.DataFrame({"Close": list(self.rates.values())}, index=idx)


def growth_co():
    years = [2021, 2022, 2023, 2024]
    rev = [1000, 1200, 1450, 1750]
    ni = [100, 125, 155, 190]
    return FakeTicker(
        years,
        income={"Total Revenue": rev, "Operating Income": [140, 172, 210, 255],
                "Net Income": ni, "Tax Provision": [25, 31, 39, 48]},
        balance={"Cash Cash Equivalents And Short Term Investments": [200, 230, 280, 340],
                 "Total Debt": [100, 100, 90, 80], "Stockholders Equity": [600, 690, 800, 935],
                 "Ordinary Shares Number": [100, 100, 100, 100]},
        cashflow={"Operating Cash Flow": [130, 160, 195, 240], "Capital Expenditure": [-40, -50, -60, -70],
                  "Cash Dividends Paid": [-30, -35, -45, -55]},
        prices={"2021-12-30": 20.0, "2022-12-30": 24.0, "2023-12-29": 30.0, "2024-12-30": 36.0,
                "2025-10-27": 40.0},
        info={"longName": "Demo Growth Co", "sector": "Technology", "currency": "THB",
              "financialCurrency": "THB"},
    )


def usd_reporter():
    """บริษัทพลังงานสมมติ งบเป็น USD ราคาเป็น THB — ต้องถูกจัดเป็นหุ้นวัฏจักรและแปลงสกุลเงิน"""
    years = [2022, 2023, 2024, 2025]
    return FakeTicker(
        years,
        income={"Total Revenue": [9.0, 8.5, 8.6, 7.6], "Operating Income": [4.5, 3.9, 3.6, 2.7],
                "Net Income": [2.0, 2.2, 2.2, 1.7], "Tax Provision": [2.3, 1.6, 1.3, 0.9]},
        balance={"Cash Cash Equivalents And Short Term Investments": [3.0, 4.4, 4.2, 2.4],
                 "Total Debt": [3.5, 3.4, 3.3, 3.0], "Stockholders Equity": [13.5, 14.4, 15.4, 15.0],
                 "Ordinary Shares Number": [3.97, 3.97, 3.97, 3.97]},
        cashflow={"Operating Cash Flow": [4.6, 4.3, 5.6, 4.2], "Capital Expenditure": [-2.6, -3.0, -3.6, -3.9],
                  "Cash Dividends Paid": [-1.0, -1.1, -1.1, -1.0]},
        prices={"2022-12-30": 176.5, "2023-12-29": 149.5, "2024-12-30": 119.0, "2025-12-30": 113.0,
                "2026-10-27": 166.5},
        info={"longName": "Demo Energy PCL", "sector": "Energy", "currency": "THB",
              "financialCurrency": "USD"},
        fx={"2022-12-30": 34.6, "2023-12-29": 34.2, "2024-12-30": 34.1, "2025-12-30": 32.5},
    )


def test_growth():
    res = moonset.analyze("DEMO.BK", ticker=growth_co())
    m, g = res["metrics"], res["growth"]
    assert abs(m.eps.iloc[-1] - 1.90) < 1e-9
    assert abs(m.fcfps.iloc[-1] - 1.70) < 1e-9
    assert abs(m.dps.iloc[-1] - 0.55) < 1e-9
    assert abs(g["eps_cagr"] - ((190 / 100) ** (1 / 3) - 1)) < 1e-9
    assert res["kind"] == "growth", res["kind"]
    assert res["score"]["total"] >= 8, res["score"]
    assert not pd.isna(res["val"]["fair_value"])
    assert abs(res["val"]["g1"] - 0.20) < 1e-9  # ถูกจำกัดที่เพดาน 20%
    moonset.print_report(res)
    return res


def test_usd_cyclical():
    res = moonset.analyze("DEMOE.BK", ticker=usd_reporter())
    raw = res["data"].raw
    assert res["data"].fx_note
    assert abs(raw.revenue.iloc[-1] - 7.6 * 32.5) < 1e-9          # แปลงเป็น THB แล้ว
    assert raw.shares.iloc[-1] == 3.97                               # จำนวนหุ้นไม่ถูกแปลง
    assert res["kind"] == "cyclical"
    assert res["val"]["used"] == ["กำไรเฉลี่ย × P/E ที่เหมาะสม"]
    moonset.print_report(res)
    return res


def test_split_not_restated():
    """แตกพาร์ 1:2 ในปี 2024 ที่ Yahoo ไม่ได้ปรับงบย้อนหลัง -> ต้องได้ผลเหมือนไม่แตกพาร์ (หน่วยหุ้นใหม่)"""
    base = moonset.analyze("DEMO.BK", ticker=growth_co())
    tk = growth_co()
    tk.balance_sheet.loc["Ordinary Shares Number", pd.Timestamp("2024-12-31")] = 200
    tk.splits = pd.Series([2.0], index=pd.DatetimeIndex([pd.Timestamp("2024-06-03")]))
    tk._prices = {k: v / 2 for k, v in tk._prices.items()}      # ราคาของ yfinance ปรับตามแตกพาร์แล้ว
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert res["kind"] == base["kind"] == "growth", res["kind"]
    assert not res["score"]["hard_fail"], res["score"]["flags"]
    assert abs(res["val"]["fair_value"] - base["val"]["fair_value"] / 2) < 1e-6
    assert any("แตกพาร์" in w for w in res["data"].warnings)


def test_split_already_restated():
    """Yahoo ปรับงบย้อนหลังให้แล้ว -> ห้ามปรับซ้ำ"""
    tk = growth_co()
    tk.balance_sheet.loc["Ordinary Shares Number"] = 200
    tk.splits = pd.Series([2.0], index=pd.DatetimeIndex([pd.Timestamp("2024-06-03")]))
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert (res["data"].raw.shares == 200).all()


def test_oldest_year_missing_net_income():
    """ปีเก่าสุดไม่มีกำไรสุทธิ -> ใช้ปีถัดไปคำนวณการเติบโต ไม่ใช่ตกเป็น 0%"""
    tk = growth_co()
    tk.income_stmt.loc["Net Income", pd.Timestamp("2021-12-31")] = float("nan")
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert abs(res["growth"]["eps_cagr"] - ((190 / 125) ** (1 / 2) - 1)) < 1e-9
    assert res["val"]["g1"] > 0.15
    assert any("ว่างในปี 2021" in w for w in res["data"].warnings)


def test_info_unavailable_warns():
    tk = usd_reporter()
    tk.info = {}
    res = moonset.analyze("DEMOE.BK", ticker=tk)
    w = " ".join(res["data"].warnings)
    assert "ไม่ทราบสกุลเงินของงบ" in w and "P/E ล่าสุด" in w, w


def test_negative_equity():
    tk = growth_co()
    tk.balance_sheet.loc["Stockholders Equity"] = [-80, -70, -60, -50]
    tk.balance_sheet.loc["Total Debt"] = [900, 900, 900, 900]
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert res["score"]["parts"]["ความแข็งแรง (หนี้สุทธิ/ทุน)"][0] == 0
    assert any("ติดลบ" in f for f in res["score"]["flags"])


def test_last_price_nan():
    tk = growth_co()
    tk._prices["2025-10-28"] = float("nan")
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert res["data"].price == 40.0


def test_bank_warns():
    tk = growth_co()
    tk.info = {**tk.info, "sector": "Financial Services", "industry": "Banks - Regional"}
    res = moonset.analyze("DEMO.BK", ticker=tk)
    assert any("Banks" in w for w in res["data"].warnings)


def test_shares_missing_raises():
    tk = growth_co()
    tk.balance_sheet = tk.balance_sheet.drop("Ordinary Shares Number")
    try:
        moonset.analyze("DEMO.BK", ticker=tk)
    except RuntimeError as e:
        assert "จำนวนหุ้น" in str(e)
    else:
        raise AssertionError("ควร error เมื่อไม่มีจำนวนหุ้น")


EDGE_TESTS = [test_split_not_restated, test_split_already_restated, test_oldest_year_missing_net_income,
              test_info_unavailable_warns, test_negative_equity, test_last_price_nan, test_bank_warns,
              test_shares_missing_raises]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r1 = test_growth()
    r2 = test_usd_cyclical()
    for t in EDGE_TESTS:
        t()
        print(f"✓ {t.__name__}")
    for r in (r1, r2):
        print("Excel:", moonset.save_excel(r, out_dir="output_test"))
    print("\nผ่านทุกการทดสอบ ✓")
