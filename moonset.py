"""
moonset — ประเมินหุ้นรายตัว: ดึงงบ 12 ค่า -> ตัวชี้วัด -> คะแนนคุณภาพ -> ราคาที่เหมาะสม

ใช้งาน:
    python moonset.py PTTEP.BK
    python moonset.py AAPL --type growth --r 0.09 --mos 0.3

หุ้นไทยต้องเติม .BK ท้ายชื่อ (เช่น CPALL.BK)
ผลลัพธ์: สรุปบนหน้าจอ + ไฟล์ Excel ในโฟลเดอร์ output/

ข้อจำกัด: ข้อมูลจาก Yahoo Finance (ไม่ใช่ API ทางการ) มักย้อนหลังได้ราว 4 ปี
ไม่เหมาะกับธนาคาร/ประกัน เพราะโครงสร้างงบต่างออกไป
ผลลัพธ์เป็นเครื่องมือช่วยคัดกรอง ไม่ใช่คำแนะนำการลงทุน
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field

import pandas as pd

# ---------------------------------------------------------------------------
# ค่าตั้งต้น (ปรับได้ผ่าน command line)
# ---------------------------------------------------------------------------
DEFAULT_R = 0.10          # อัตราคิดลด (ผลตอบแทนที่ต้องการ)
DEFAULT_G_TERMINAL = 0.03  # การเติบโตระยะยาวหลังปีที่ 10
DEFAULT_MOS = 0.25        # Margin of Safety
DEFAULT_FAIR_PE = 10.0    # P/E ที่ใช้กับกำไรเฉลี่ยของหุ้นวัฏจักร
MAX_GROWTH = 0.20         # เพดานการเติบโตช่วง 5 ปีแรก (กันการคาดการณ์เกินจริง)

CYCLICAL_SECTORS = {"Energy", "Basic Materials"}

# ---------------------------------------------------------------------------
# 1) ดึงข้อมูล: 12 ค่า
# ---------------------------------------------------------------------------
# ชื่อแถวใน yfinance ไม่ตรงกันทุกบริษัท จึงใส่ชื่อสำรองไว้ไล่หาตามลำดับ
FIELDS = {
    # งบกำไรขาดทุน
    "revenue":          ("income", ["Total Revenue", "Operating Revenue"]),
    "operating_income": ("income", ["Operating Income", "EBIT"]),
    "net_income":       ("income", ["Net Income Common Stockholders", "Net Income",
                                    "Net Income From Continuing Operation Net Minority Interest"]),
    "tax":              ("income", ["Tax Provision"]),
    # งบดุล
    "cash":             ("balance", ["Cash Cash Equivalents And Short Term Investments",
                                     "Cash And Cash Equivalents"]),
    "debt":             ("balance", ["Total Debt"]),
    "equity":           ("balance", ["Stockholders Equity", "Common Stock Equity"]),
    "shares":           ("balance", ["Ordinary Shares Number", "Share Issued"]),
    # งบกระแสเงินสด
    "ocf":              ("cashflow", ["Operating Cash Flow",
                                      "Cash Flow From Continuing Operating Activities"]),
    "capex":            ("cashflow", ["Capital Expenditure"]),
    "dividends":        ("cashflow", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
}

LABELS_TH = {
    "revenue": "รายได้รวม", "operating_income": "กำไรจากการดำเนินงาน",
    "net_income": "กำไรสุทธิ", "tax": "ภาษีเงินได้", "cash": "เงินสด+เงินลงทุนระยะสั้น",
    "debt": "หนี้ที่มีดอกเบี้ย", "equity": "ส่วนของผู้ถือหุ้น", "shares": "จำนวนหุ้น",
    "ocf": "เงินสดจากการดำเนินงาน", "capex": "รายจ่ายลงทุน", "dividends": "เงินปันผลจ่าย",
    "price": "ราคา ณ สิ้นปีบัญชี",
}


@dataclass
class StockData:
    symbol: str
    name: str
    sector: str | None
    currency: str
    fx_note: str | None
    price: float
    raw: pd.DataFrame          # index = ปี, columns = 12 ค่า
    warnings: list = field(default_factory=list)


def _pick_row(df: pd.DataFrame, names: list[str]):
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def fetch(symbol: str, ticker=None) -> StockData:
    """ดึง 12 ค่ารายปีจาก yfinance (ส่ง ticker จำลองเข้ามาได้เพื่อทดสอบ)"""
    if ticker is None:
        import yfinance as yf
        ticker = yf.Ticker(symbol)

    statements = {
        "income": ticker.income_stmt,
        "balance": ticker.balance_sheet,
        "cashflow": ticker.cashflow,
    }
    if all(s is None or s.empty for s in statements.values()):
        raise RuntimeError(f"ไม่พบงบการเงินของ {symbol} — เช็กชื่อหุ้น (หุ้นไทยต้องลงท้าย .BK)")

    warnings = []
    cols = {}
    for key, (stmt, names) in FIELDS.items():
        row = _pick_row(statements[stmt], names)
        if row is None:
            warnings.append(f"ไม่พบ '{LABELS_TH[key]}' ในงบ — ถือเป็น 0/ว่าง")
            continue
        cols[key] = row
    raw = pd.DataFrame(cols)
    raw.index = pd.to_datetime(raw.index)
    raw = raw.sort_index()
    # ตัดปีที่ข้อมูลหลักว่าง (yfinance บางทีมีคอลัมน์ปีเก่าที่ว่างเกือบทั้งหมด)
    raw = raw[raw.get("revenue", pd.Series(index=raw.index, dtype=float)).notna()]
    for key in FIELDS:
        if key not in raw:
            raw[key] = float("nan")
    raw = raw[list(FIELDS)]
    # ปีบัญชีซ้ำ (เช่น บริษัทเปลี่ยนรอบบัญชี) -> เก็บงบล่าสุดของปีนั้น
    raw = raw[~raw.index.year.duplicated(keep="last")]

    info = _get_info(ticker)
    name = info.get("longName") or info.get("shortName") or symbol
    sector = info.get("sector")
    industry = info.get("industry") or ""
    price_ccy = info.get("currency") or _fast_currency(ticker) or "?"
    fin_ccy = info.get("financialCurrency")
    if not fin_ccy:
        fin_ccy = price_ccy
        warnings.append("ไม่ทราบสกุลเงินของงบ (Yahoo ไม่ส่งข้อมูลบริษัทมา) — ถือว่าเป็นสกุลเดียวกับราคา "
                        "ถ้าบริษัทรายงานงบเป็น USD (เช่น PTTEP) ตัวเลขจะผิด ให้ลองใหม่ภายหลัง")
    if sector == "Financial Services" and any(k in industry for k in ("Bank", "Insurance")):
        warnings.append(f"หุ้นกลุ่ม {industry} — โครงสร้างงบต่างจากบริษัททั่วไป "
                        "เกณฑ์หนี้/FCF/ROIC ใช้ไม่ได้ ผลลัพธ์ไม่น่าเชื่อถือ")

    # ราคาย้อนหลัง -> ราคาปัจจุบัน และราคา ณ วันสิ้นปีบัญชี (Close ของ yfinance ปรับตามการแตกพาร์แล้ว)
    hist = ticker.history(period="10y", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"ไม่พบราคาหุ้นของ {symbol}")
    close = hist["Close"].dropna()   # แท่งของวันนี้บางครั้งเป็นค่าว่าง
    if close.empty:
        raise RuntimeError(f"ไม่พบราคาหุ้นของ {symbol}")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    price = float(close.iloc[-1])
    raw["price"] = [float(close[:d].iloc[-1]) if (close.index <= d).any() else float("nan")
                    for d in raw.index]

    # จำนวนหุ้นในงบเป็นตัวเลขตามที่รายงานแต่ละปี -> ปรับตามการแตกพาร์/หุ้นปันผลให้ตรงกับราคา
    split_note = _adjust_shares_for_splits(raw, ticker, info)
    if split_note:
        warnings.append(split_note)

    # บางบริษัทรายงานงบเป็นสกุลอื่น (เช่น USD) แต่ราคาเป็นบาท -> แปลงงบเป็นสกุลของราคา
    fx_note = None
    if fin_ccy != price_ccy and fin_ccy != "?" and price_ccy != "?":
        fx = _fx_series(fin_ccy, price_ccy, raw.index, ticker_factory=getattr(ticker, "fx_factory", None))
        money_cols = [c for c in FIELDS if c != "shares"]
        raw[money_cols] = raw[money_cols].mul(fx.values, axis=0)
        fx_note = f"งบรายงานเป็น {fin_ccy} แปลงเป็น {price_ccy} ด้วยอัตราแลกเปลี่ยน ณ สิ้นปีบัญชี"

    raw.index = raw.index.year
    raw.index.name = "ปีบัญชี"
    for key in ("net_income", "shares", "equity"):
        missing = [str(y) for y in raw.index[raw[key].isna()]]
        if missing and key in cols:
            warnings.append(f"'{LABELS_TH[key]}' ว่างในปี {', '.join(missing)} — ปีนั้นไม่ถูกใช้คำนวณ")
    return StockData(symbol, name, sector, price_ccy, fx_note, price, raw, warnings)


def _get_info(ticker, tries=2) -> dict:
    """.info โดน Yahoo บล็อก/จำกัดบ่อยที่สุด -> ลองซ้ำก่อนยอมแพ้"""
    for _ in range(tries):
        try:
            info = ticker.info or {}
            if info:
                return info
        except Exception:
            pass
    return {}


def _fast_currency(ticker):
    try:
        return ticker.fast_info["currency"]
    except Exception:
        return None


def _adjust_shares_for_splits(raw: pd.DataFrame, ticker, info: dict) -> str | None:
    """ปรับจำนวนหุ้นปีเก่าให้เป็นหน่วยเดียวกับหุ้นปัจจุบัน

    Yahoo บางบริษัทปรับงบย้อนหลังให้แล้ว บางบริษัทไม่ปรับ จึงปรับเฉพาะเมื่อเห็นว่า
    จำนวนหุ้นกระโดดสอดคล้องกับอัตราแตกพาร์จริง (คลาดเคลื่อนไม่เกิน 15%)
    """
    try:
        splits = ticker.splits
    except Exception:
        return None
    if splits is None or len(splits) == 0:
        return None
    splits = splits[splits > 0].copy()
    splits.index = pd.to_datetime(splits.index).tz_localize(None)
    shares = raw["shares"]
    dates = list(raw.index)
    close_to = lambda a, b: b > 0 and abs(a / b - 1) <= 0.15
    applied = []

    # แตกพาร์ระหว่างปีงบ: ถ้าหุ้นกระโดดตามอัตรา -> ปรับปีก่อนหน้าทั้งหมด
    for prev, cur in zip(dates[:-1], dates[1:]):
        ratio = float(splits[(splits.index > prev) & (splits.index <= cur)].prod())
        if ratio == 1 or pd.isna(shares[prev]) or pd.isna(shares[cur]):
            continue
        if close_to(shares[cur] / shares[prev], ratio):
            raw.loc[raw.index <= prev, "shares"] *= ratio
            applied.append(f"{cur.year} (×{ratio:g})")

    # แตกพาร์หลังปีงบล่าสุด: ราคาปรับแล้วแต่งบยังไม่ปรับ
    after = float(splits[splits.index > dates[-1]].prod())
    if after != 1 and not pd.isna(shares.iloc[-1]):
        now = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if not now or close_to(now / shares.iloc[-1], after):
            raw["shares"] *= after
            applied.append(f"หลังปีงบล่าสุด (×{after:g})")
    if applied:
        return "ปรับจำนวนหุ้นตามการแตกพาร์/หุ้นปันผล: " + ", ".join(applied)
    return None


def _fx_series(src: str, dst: str, dates, ticker_factory=None) -> pd.Series:
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    h = ticker_factory(f"{src}{dst}=X").history(period="10y")["Close"]
    h.index = pd.to_datetime(h.index).tz_localize(None)
    return pd.Series([float(h[:d].iloc[-1]) if (h.index <= d).any() else float(h.iloc[0])
                      for d in dates], index=dates)


# ---------------------------------------------------------------------------
# 2) ตัวชี้วัด
# ---------------------------------------------------------------------------
def _div(a, b):
    try:
        if b is None or a is None or pd.isna(a) or pd.isna(b) or b == 0:
            return float("nan")
        return a / b
    except TypeError:
        return float("nan")


def cagr(first, last, years):
    """อัตราเติบโตเฉลี่ยต่อปี — คืน NaN ถ้าค่าเริ่ม/จบติดลบ (คำนวณไม่ได้อย่างมีความหมาย)"""
    if years <= 0 or pd.isna(first) or pd.isna(last) or first <= 0 or last <= 0:
        return float("nan")
    return (last / first) ** (1 / years) - 1


def compute_metrics(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy().fillna({"tax": 0, "dividends": 0, "capex": 0, "debt": 0, "cash": 0})
    m = pd.DataFrame(index=d.index)
    m["eps"] = d.net_income / d.shares
    m["dps"] = -d.dividends / d.shares          # yfinance เก็บปันผลจ่ายเป็นค่าติดลบ
    m["bvps"] = d.equity / d.shares
    m["fcf"] = d.ocf + d.capex                  # capex เป็นค่าติดลบ
    m["fcfps"] = m.fcf / d.shares
    m["op_margin"] = d.operating_income / d.revenue
    m["net_margin"] = d.net_income / d.revenue
    m["roe"] = d.net_income / d.equity
    tax_rate = (d.tax / (d.net_income + d.tax)).clip(0, 0.5)
    m["tax_rate"] = tax_rate.where((d.net_income + d.tax) > 0, 0.20)
    invested = d.equity + d.debt - d.cash
    m["roic"] = (d.operating_income * (1 - m.tax_rate)) / invested.where(invested > 0)
    m["de"] = d.debt / d.equity
    m["net_debt_equity"] = (d.debt - d.cash) / d.equity
    m["cash_conversion"] = d.ocf / d.net_income.where(d.net_income > 0)
    m["payout"] = m.dps / m.eps.where(m.eps > 0)
    m["pe"] = d.price / m.eps.where(m.eps > 0)
    m["pbv"] = d.price / m.bvps
    m["div_yield"] = m.dps / d.price
    m["fcf_yield"] = m.fcfps / d.price
    return m


def series_cagr(s: pd.Series) -> float:
    """CAGR จากปีแรกถึงปีสุดท้ายที่มีข้อมูล (ข้ามปีที่ว่าง แทนที่จะได้ NaN ทั้งก้อน)"""
    s = s.dropna()
    if len(s) < 2:
        return float("nan")
    return cagr(s.iloc[0], s.iloc[-1], s.index[-1] - s.index[0])


def growth_summary(raw: pd.DataFrame, m: pd.DataFrame) -> dict:
    eps = m.eps.dropna()
    shares = raw.shares.dropna()
    return {
        "years": len(raw) - 1,
        "revenue_cagr": series_cagr(raw.revenue),
        "eps_cagr": series_cagr(m.eps),
        "fcfps_cagr": series_cagr(m.fcfps),
        "bvps_cagr": series_cagr(m.bvps),
        "eps_last_change": _div(eps.iloc[-1], eps.iloc[-2]) - 1 if len(eps) > 1 else float("nan"),
        "shares_change": _div(shares.iloc[-1], shares.iloc[0]) - 1 if len(shares) > 1 else float("nan"),
    }


# ---------------------------------------------------------------------------
# 3) คะแนนคุณภาพ (เต็ม 10) + เกณฑ์ตัดทิ้ง
# ---------------------------------------------------------------------------
def score(raw: pd.DataFrame, m: pd.DataFrame, g: dict) -> dict:
    flags = []
    if (raw.net_income < 0).sum() > max(1, len(raw) // 4):
        flags.append("ขาดทุนบ่อยเกินไป")
    elif (raw.net_income < 0).any():
        flags.append("มีปีที่ขาดทุน")
    if m.fcf.sum() < 0:
        flags.append("FCF รวมทุกปีติดลบ")
    negative_equity = not pd.isna(raw.equity.iloc[-1]) and raw.equity.iloc[-1] <= 0
    if negative_equity:
        flags.append("ส่วนของผู้ถือหุ้นติดลบ (อัตราส่วนหนี้ใช้ไม่ได้)")
    elif m.de.iloc[-1] > 2:
        flags.append("D/E เกิน 2 เท่า")
    if g["shares_change"] > 0.10:
        flags.append("จำนวนหุ้นเพิ่มเกิน 10% (ถูก dilute)")
    hard_fail = any(f in flags for f in
                    ["ขาดทุนบ่อยเกินไป", "FCF รวมทุกปีติดลบ", "D/E เกิน 2 เท่า",
                     "จำนวนหุ้นเพิ่มเกิน 10% (ถูก dilute)"])

    def band(x, hi, lo):  # >hi = 2, >=lo = 1, else 0
        if pd.isna(x):
            return 0
        return 2 if x > hi else (1 if x >= lo else 0)

    roic = m.roic.mean()
    eps_growth = g["eps_cagr"]
    cash_conv = m.cash_conversion.mean()
    nde = m.net_debt_equity.iloc[-1]
    eps = m.eps.dropna()

    s = {}
    s["ผลตอบแทน (ROIC เฉลี่ย)"] = (band(roic, 0.15, 0.08), roic)
    s["การเติบโต (EPS ต่อปี)"] = (band(eps_growth, 0.10, 0.0), eps_growth)
    if len(eps) < 2:
        cons = 0
    elif (eps > 0).all() and (eps.diff().dropna() > 0).all():
        cons = 2
    elif (eps > 0).all() and eps.min() / eps.max() >= 0.5:
        cons = 1
    else:
        cons = 0
    ups = int((eps.diff().dropna() > 0).sum())
    s["ความสม่ำเสมอของกำไร"] = (cons, f"EPS เพิ่มขึ้น {ups}/{len(eps) - 1} ปี"
                                + ("" if (eps > 0).all() else ", มีปีขาดทุน"))
    s["คุณภาพกำไร (OCF/กำไร)"] = (band(cash_conv, 1.0, 0.7), cash_conv)
    if negative_equity or pd.isna(nde):
        strength = 0
    else:
        strength = 2 if nde <= 0 else (1 if nde < 0.5 else 0)
    s["ความแข็งแรง (หนี้สุทธิ/ทุน)"] = (strength, nde)

    total = sum(v[0] for v in s.values())
    return {"parts": s, "total": total, "flags": flags, "hard_fail": hard_fail}


# ---------------------------------------------------------------------------
# 4) จัดกลุ่ม + ประเมินมูลค่า
# ---------------------------------------------------------------------------
def classify(sd: StockData, m: pd.DataFrame, g: dict, override: str | None = None) -> tuple[str, str]:
    if override:
        return override, "กำหนดเอง"
    eps = m.eps
    worst_drop = eps.pct_change().min()  # ปีที่ EPS ลดลงแรงที่สุด
    if sd.sector in CYCLICAL_SECTORS or (eps <= 0).any() or _nz(worst_drop) < -0.20:
        why = f"กลุ่ม {sd.sector}" if sd.sector in CYCLICAL_SECTORS else "กำไรผันผวนสูง"
        return "cyclical", why
    payout = m.payout.iloc[-3:].mean()
    growth = max(_nz(g["eps_cagr"]), _nz(g["revenue_cagr"]))
    if growth >= 0.10 and (pd.isna(payout) or payout < 0.5):
        return "growth", f"กำไร/รายได้โต {growth:.0%} ต่อปี และจ่ายปันผลน้อย"
    if not pd.isna(payout) and payout >= 0.5:
        return "dividend", f"จ่ายปันผล {payout:.0%} ของกำไร"
    return "stable", "โตปานกลาง จ่ายปันผลไม่สูง"


def _nz(x, default=0.0):
    return default if x is None or pd.isna(x) else x


def two_stage_value(base, g1, r, g_term, years1=5, years2=5):
    """มูลค่าปัจจุบันของกระแสเงินต่อหุ้น: โต g1 5 ปี -> ค่อยๆ ลดลงเหลือ g_term ใน 5 ปีถัดไป -> terminal"""
    if base is None or pd.isna(base) or base <= 0 or r <= g_term:
        return float("nan")
    value, cf = 0.0, base
    for t in range(1, years1 + years2 + 1):
        if t <= years1:
            growth = g1
        else:
            k = t - years1
            growth = g1 + (g_term - g1) * k / years2
        cf *= 1 + growth
        value += cf / (1 + r) ** t
    terminal = cf * (1 + g_term) / (r - g_term)
    value += terminal / (1 + r) ** (years1 + years2)
    return value


def reverse_dcf(price, base, r, g_term):
    """ราคาปัจจุบันสะท้อนว่าตลาดคาดการเติบโตช่วง 5 ปีแรกปีละกี่ %"""
    if pd.isna(base) or base <= 0:
        return float("nan")
    lo, hi = -0.30, 1.00
    if two_stage_value(base, hi, r, g_term) < price:
        return float("inf")
    if two_stage_value(base, lo, r, g_term) > price:
        return lo
    for _ in range(100):
        mid = (lo + hi) / 2
        if two_stage_value(base, mid, r, g_term) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def valuate(sd: StockData, m: pd.DataFrame, g: dict, kind: str,
            r=DEFAULT_R, g_term=DEFAULT_G_TERMINAL, fair_pe=DEFAULT_FAIR_PE) -> dict:
    # ใช้ค่าที่ต่ำที่สุดของการเติบโตที่คำนวณได้ (ระมัดระวัง) — ถ้าคำนวณไม่ได้เลยถือเป็น 0%
    known = [x for x in (g["eps_cagr"], g["revenue_cagr"], g["fcfps_cagr"]) if not pd.isna(x)]
    growth_in = min(known) if known else 0.0
    g1 = max(0.0, min(growth_in, MAX_GROWTH))

    fcf_base = m.fcfps.dropna().iloc[-3:].mean()  # เฉลี่ย 3 ปีล่าสุด ลดผลของปีที่ลงทุนหนัก
    dps_base = m.dps.dropna().iloc[-1] if m.dps.notna().any() else float("nan")
    eps_norm = m.eps.mean()                       # กำไรเฉลี่ยทุกปีที่มี (ใช้กับหุ้นวัฏจักร)
    eps_last = m.eps.dropna().iloc[-1] if m.eps.notna().any() else float("nan")
    bvps = m.bvps.dropna().iloc[-1] if m.bvps.notna().any() else float("nan")

    methods = {
        "DCF (FCF ต่อหุ้น)": two_stage_value(fcf_base, g1, r, g_term),
        "DDM (ปันผล)": two_stage_value(dps_base, min(g1, 0.08), r, g_term),
        "กำไรเฉลี่ย × P/E ที่เหมาะสม": eps_norm * fair_pe if eps_norm > 0 else float("nan"),
        "Graham Number": math.sqrt(22.5 * eps_last * bvps) if eps_last > 0 and bvps > 0 else float("nan"),
    }
    primary_by_kind = {
        "growth": ["DCF (FCF ต่อหุ้น)"],
        "dividend": ["DDM (ปันผล)", "DCF (FCF ต่อหุ้น)"],
        "cyclical": ["กำไรเฉลี่ย × P/E ที่เหมาะสม"],
        "stable": ["DCF (FCF ต่อหุ้น)", "กำไรเฉลี่ย × P/E ที่เหมาะสม"],
    }
    used = [k for k in primary_by_kind[kind] if not pd.isna(methods[k])]
    if not used:  # วิธีหลักใช้ไม่ได้ (เช่น FCF ติดลบ) -> ใช้ค่ากลางของวิธีที่เหลือ
        used = [k for k, v in methods.items() if not pd.isna(v)]
    fair = pd.Series([methods[k] for k in used]).median() if used else float("nan")

    pe_last = sd.price / eps_last if eps_last > 0 else float("nan")
    return {
        "g1": g1, "r": r, "g_term": g_term, "fair_pe": fair_pe,
        "methods": methods, "used": used, "fair_value": fair,
        "implied_growth": reverse_dcf(sd.price, fcf_base, r, g_term),
        "peg": pe_last / (g["eps_cagr"] * 100) if _nz(g["eps_cagr"]) > 0 and not pd.isna(pe_last) else float("nan"),
        "pe": pe_last,
    }


def verdict(quality: int, hard_fail: bool, mos_actual: float, mos_req: float) -> str:
    cheap = not pd.isna(mos_actual) and mos_actual >= mos_req
    if hard_fail:
        return "ไม่ผ่านเกณฑ์ขั้นต่ำ — ตัดทิ้ง หรือศึกษาด้วยความระวังสูง"
    if pd.isna(mos_actual):
        return "ข้อมูลไม่พอประเมินมูลค่า — ดูคำเตือนด้านบน แล้วตรวจกับงบจริง"
    good = quality >= 7
    if good and cheap:
        return "⭐ คุณภาพสูง + ราคาต่ำกว่าราคาที่ควรซื้อ — น่าศึกษาต่อที่สุด"
    if good:
        return "คุณภาพสูง แต่ราคายังไม่ถูกพอ — ใส่ watchlist รอราคา"
    if cheap:
        return "ราคาถูก แต่คุณภาพปานกลาง/ต่ำ — ระวังกับดักของถูก"
    return "คุณภาพปานกลาง/ต่ำ และราคาไม่ถูก — ผ่านไปก่อน"


# ---------------------------------------------------------------------------
# 5) รายงาน
# ---------------------------------------------------------------------------
KIND_TH = {"growth": "หุ้นเติบโต", "dividend": "หุ้นปันผล", "cyclical": "หุ้นวัฏจักร", "stable": "หุ้นมั่นคง"}


def pct(x):
    return "-" if x is None or pd.isna(x) else ("∞" if x == float("inf") else f"{x:.1%}")


def num(x, d=2):
    return "-" if x is None or pd.isna(x) else f"{x:,.{d}f}"


def analyze(symbol, kind=None, r=DEFAULT_R, mos=DEFAULT_MOS, fair_pe=DEFAULT_FAIR_PE,
            g_term=DEFAULT_G_TERMINAL, ticker=None) -> dict:
    sd = fetch(symbol, ticker=ticker)
    if len(sd.raw) < 2:
        raise RuntimeError("มีงบไม่ถึง 2 ปี คำนวณการเติบโตไม่ได้")
    if sd.raw.shares.isna().all() or sd.raw.net_income.isna().all():
        raise RuntimeError("ไม่พบจำนวนหุ้นหรือกำไรสุทธิในงบ — คำนวณต่อหุ้นไม่ได้")
    m = compute_metrics(sd.raw)
    g = growth_summary(sd.raw, m)
    sc = score(sd.raw, m, g)
    k, why = classify(sd, m, g, kind)
    v = valuate(sd, m, g, k, r=r, g_term=g_term, fair_pe=fair_pe)
    buy_price = v["fair_value"] * (1 - mos)
    fv = v["fair_value"]
    mos_actual = 1 - sd.price / fv if not pd.isna(fv) and fv > 0 else float("nan")
    # P/E ผิดธรรมชาติมาก มักเกิดจากสกุลเงินงบไม่ตรงกับราคา หรือจำนวนหุ้นผิดหน่วย
    if not pd.isna(v["pe"]) and (v["pe"] > 150 or v["pe"] < 1):
        sd.warnings.append(f"P/E ล่าสุด {v['pe']:.1f} ผิดปกติ — ตรวจสกุลเงินของงบและจำนวนหุ้นกับงบจริง")
    return {"data": sd, "metrics": m, "growth": g, "score": sc, "kind": k, "kind_why": why,
            "val": v, "mos_req": mos, "buy_price": buy_price, "mos_actual": mos_actual,
            "verdict": verdict(sc["total"], sc["hard_fail"], mos_actual, mos)}


def print_report(res: dict):
    sd, m, g, sc, v = res["data"], res["metrics"], res["growth"], res["score"], res["val"]
    c = sd.currency
    line = "─" * 64
    print(line)
    print(f"{sd.name} ({sd.symbol})  |  กลุ่ม: {sd.sector or '-'}")
    print(f"ราคาปัจจุบัน: {num(sd.price)} {c}   |   ข้อมูลงบ: {sd.raw.index[0]}–{sd.raw.index[-1]}")
    if sd.fx_note:
        print(f"หมายเหตุ: {sd.fx_note}")
    for w in sd.warnings:
        print(f"⚠ {w}")
    print(line)

    print("ตัวชี้วัดรายปี")
    show = pd.DataFrame({
        "EPS": m.eps.map(num), "DPS": m.dps.map(num), "FCF/หุ้น": m.fcfps.map(num),
        "ROE": m.roe.map(pct), "ROIC": m.roic.map(pct), "Net margin": m.net_margin.map(pct),
        "D/E": m.de.map(lambda x: num(x)), "P/E": m.pe.map(lambda x: num(x, 1)),
    })
    print(show.to_string())
    print(f"\nการเติบโตเฉลี่ย {g['years']} ปี: รายได้ {pct(g['revenue_cagr'])} | EPS {pct(g['eps_cagr'])} | "
          f"FCF/หุ้น {pct(g['fcfps_cagr'])} | BV/หุ้น {pct(g['bvps_cagr'])}")
    print(line)

    print(f"คะแนนคุณภาพ: {sc['total']}/10")
    for name, (pts, val) in sc["parts"].items():
        shown = val if isinstance(val, str) else (num(val) if "หนี้" in name or "OCF" in name else pct(val))
        print(f"  {'●' * pts}{'○' * (2 - pts)}  {name}: {shown}")
    if sc["flags"]:
        print("  สัญญาณที่ต้องระวัง: " + ", ".join(sc["flags"]))
    print(line)

    print(f"ประเภท: {KIND_TH[res['kind']]} ({res['kind_why']})")
    print(f"สมมติฐาน: อัตราคิดลด {pct(v['r'])}, โตช่วงแรก {pct(v['g1'])}/ปี, ระยะยาว {pct(v['g_term'])}, "
          f"P/E เหมาะสม {v['fair_pe']:.0f}")
    for name, val in v["methods"].items():
        mark = "→" if name in v["used"] else " "
        print(f"  {mark} {name}: {num(val)} {c}")
    print(f"\n  ราคาที่เหมาะสม (Fair Value): {num(v['fair_value'])} {c}")
    print(f"  ราคาที่ควรซื้อ (เผื่อ MOS {pct(res['mos_req'])}): {num(res['buy_price'])} {c}")
    print(f"  ส่วนต่างราคาปัจจุบันกับ Fair Value: {pct(res['mos_actual'])} "
          f"({'ต่ำกว่า' if _nz(res['mos_actual']) > 0 else 'สูงกว่า'}มูลค่า)")
    print(f"  Reverse DCF: ราคานี้คาดว่า FCF จะโต {pct(v['implied_growth'])}/ปี ใน 5 ปีแรก")
    print(f"  P/E ล่าสุด {num(v['pe'], 1)} | PEG {num(v['peg'])}")
    print(line)
    print(f"สรุป: {res['verdict']}")
    print("(เครื่องมือคัดกรอง ไม่ใช่คำแนะนำการลงทุน — ตรวจตัวเลขกับงบจริงก่อนใช้)")
    print(line)


def save_excel(res: dict, out_dir="output") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{res['data'].symbol.replace('.', '_')}.xlsx")
    write_excel(res, path)
    return path


def excel_bytes(res: dict) -> bytes:
    import io
    buf = io.BytesIO()
    write_excel(res, buf)
    return buf.getvalue()


def write_excel(res: dict, target):
    sd, m, v, sc = res["data"], res["metrics"], res["val"], res["score"]
    path = target
    summary = [
        ("ชื่อ", sd.name), ("สัญลักษณ์", sd.symbol), ("ราคาปัจจุบัน", sd.price), ("สกุลเงิน", sd.currency),
        ("ประเภท", KIND_TH[res["kind"]]), ("เหตุผลที่จัดกลุ่ม", res["kind_why"]),
        ("คะแนนคุณภาพ (เต็ม 10)", sc["total"]),
        *[(f"  {k}", p) for k, (p, _) in sc["parts"].items()],
        ("สัญญาณที่ต้องระวัง", ", ".join(sc["flags"]) or "-"),
        *[(f"มูลค่า: {k}", val) for k, val in v["methods"].items()],
        ("วิธีที่ใช้คำนวณ Fair Value", ", ".join(v["used"])),
        ("Fair Value", v["fair_value"]), ("ราคาที่ควรซื้อ", res["buy_price"]),
        ("ส่วนต่างกับ Fair Value", res["mos_actual"]),
        ("Reverse DCF: การเติบโตที่ราคาสะท้อน", v["implied_growth"]),
        ("อัตราคิดลด", v["r"]), ("การเติบโตช่วงแรกที่ใช้", v["g1"]), ("การเติบโตระยะยาว", v["g_term"]),
        ("สรุป", res["verdict"]),
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(summary, columns=["รายการ", "ค่า"]).to_excel(xw, sheet_name="สรุป", index=False)
        sd.raw.rename(columns=LABELS_TH).T.to_excel(xw, sheet_name="ข้อมูลดิบ 12 ค่า")
        m.T.to_excel(xw, sheet_name="ตัวชี้วัด")
    return path


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # ให้ภาษาไทยแสดงผลบน Windows
    except Exception:
        pass
    p = argparse.ArgumentParser(description="moonset — ประเมินหุ้นรายตัว")
    p.add_argument("symbols", nargs="+", help="ชื่อหุ้น เช่น PTTEP.BK AAPL (ใส่หลายตัวได้)")
    p.add_argument("--type", choices=list(KIND_TH), help="บังคับประเภทหุ้น (ไม่ใส่ = จัดกลุ่มอัตโนมัติ)")
    p.add_argument("--r", type=float, default=DEFAULT_R, help="อัตราคิดลด (ค่าตั้งต้น 0.10)")
    p.add_argument("--mos", type=float, default=DEFAULT_MOS, help="Margin of Safety (ค่าตั้งต้น 0.25)")
    p.add_argument("--pe", type=float, default=DEFAULT_FAIR_PE, help="P/E เหมาะสมสำหรับหุ้นวัฏจักร (ค่าตั้งต้น 10)")
    p.add_argument("--g", type=float, default=DEFAULT_G_TERMINAL, help="การเติบโตระยะยาว (ค่าตั้งต้น 0.03)")
    p.add_argument("--no-excel", action="store_true", help="ไม่บันทึกไฟล์ Excel")
    a = p.parse_args(argv)

    for sym in a.symbols:
        try:
            res = analyze(sym.upper(), kind=a.type, r=a.r, mos=a.mos, fair_pe=a.pe, g_term=a.g)
        except Exception as e:
            print(f"✖ {sym}: {e}")
            continue
        print_report(res)
        if not a.no_excel:
            print(f"บันทึกไฟล์: {save_excel(res)}\n")


if __name__ == "__main__":
    main()
