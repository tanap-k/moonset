"""
moonset — หน้าเว็บ (Streamlit)

รัน:  streamlit run app.py
แล้วเปิด http://localhost:8501 ในเบราว์เซอร์ (ปกติจะเปิดให้อัตโนมัติ)

โหมดทดลองไม่ต้องต่อเน็ต:  set MOONSET_DEMO=1  แล้วใส่ชื่อ DEMO.BK หรือ DEMOE.BK
"""
import os

import altair as alt
import pandas as pd
import streamlit as st

import moonset as ms

st.set_page_config(page_title="moonset", page_icon="🌙", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
div[data-testid="stMetricValue"] {font-size: 1.6rem;}
.verdict {padding: .9rem 1.1rem; border-radius: .6rem; font-weight: 600; margin: .4rem 0 1rem;}
.v-best {background: #e7f6ec; color: #135c2e; border-left: 5px solid #2e9e5b;}
.v-watch {background: #e8f0fb; color: #1b3f73; border-left: 5px solid #3b73c4;}
.v-trap {background: #fdf3e2; color: #6b4708; border-left: 5px solid #d99a26;}
.v-pass {background: #f1f1f1; color: #444; border-left: 5px solid #999;}
.v-fail {background: #fbe9e9; color: #7a1d1d; border-left: 5px solid #c94040;}
@media (prefers-color-scheme: dark) {
  .v-best {background:#16301f;color:#bfe8cd}.v-watch{background:#172539;color:#c3d6f3}
  .v-trap{background:#3a2c10;color:#f2d9a8}.v-pass{background:#2a2a2a;color:#ccc}.v-fail{background:#3a1717;color:#f2c0c0}
}
</style>
""", unsafe_allow_html=True)

DEMO = os.environ.get("MOONSET_DEMO") == "1"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def run(symbol, kind, r, mos, fair_pe, g_term):
    ticker = None
    if DEMO:
        import test_offline as t
        demos = {"DEMO.BK": t.growth_co, "DEMOE.BK": t.usd_reporter}
        if symbol not in demos:
            raise RuntimeError("โหมดทดลองใช้ได้เฉพาะ DEMO.BK และ DEMOE.BK")
        ticker = demos[symbol]()
    return ms.analyze(symbol, kind=kind, r=r, mos=mos, fair_pe=fair_pe, g_term=g_term, ticker=ticker)


def verdict_class(text):
    if text.startswith("⭐"):
        return "v-best"
    if text.startswith("ไม่ผ่าน"):
        return "v-fail"
    if text.startswith("คุณภาพสูง"):
        return "v-watch"
    if text.startswith("ราคาถูก"):
        return "v-trap"
    if text.startswith("ข้อมูลไม่พอ"):
        return "v-fail"
    return "v-pass"


def fmt(x, d=2):
    return ms.num(x, d)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🌙 moonset")
    st.caption("ประเมินหุ้นรายตัว: คะแนนคุณภาพ + ราคาที่เหมาะสม")
    raw_syms = st.text_input("ชื่อหุ้น (คั่นด้วยเว้นวรรคหรือจุลภาค)",
                             value="DEMO.BK, DEMOE.BK" if DEMO else "PTTEP.BK",
                             help="หุ้นไทยเติม .BK เช่น CPALL.BK — หุ้นอเมริกาใส่ชื่อตรงๆ เช่น AAPL")
    st.subheader("สมมติฐาน")
    r = st.slider("อัตราคิดลด (ผลตอบแทนที่ต้องการ)", 0.06, 0.15, ms.DEFAULT_R, 0.005, format="%.3f")
    mos = st.slider("Margin of Safety", 0.0, 0.5, ms.DEFAULT_MOS, 0.05, format="%.2f")
    g_term = st.slider("การเติบโตระยะยาว", 0.0, 0.05, ms.DEFAULT_G_TERMINAL, 0.005, format="%.3f")
    fair_pe = st.slider("P/E เหมาะสม (หุ้นวัฏจักร)", 5.0, 20.0, ms.DEFAULT_FAIR_PE, 0.5)
    kind_opt = st.selectbox("ประเภทหุ้น", ["อัตโนมัติ"] + list(ms.KIND_TH.values()))
    kind = None if kind_opt == "อัตโนมัติ" else {v: k for k, v in ms.KIND_TH.items()}[kind_opt]
    go = st.button("วิเคราะห์", type="primary", width="stretch")
    st.divider()
    st.caption("ข้อมูลจาก Yahoo Finance (ไม่ใช่ API ทางการ) ย้อนหลังราว 4 ปี · ไม่เหมาะกับธนาคาร/ประกัน · "
               "เครื่องมือคัดกรอง ไม่ใช่คำแนะนำการลงทุน")

symbols = [s.strip().upper() for s in raw_syms.replace(",", " ").split() if s.strip()]
if go:
    st.session_state["symbols"] = symbols
symbols = st.session_state.get("symbols")

if not symbols:
    st.header("🌙 moonset")
    st.write("ใส่ชื่อหุ้นทางซ้าย แล้วกด **วิเคราะห์**")
    st.markdown("""
- **คะแนนคุณภาพเต็ม 10**: ROIC, การเติบโตของ EPS, ความสม่ำเสมอ, คุณภาพกำไร, หนี้
- **จัดกลุ่มอัตโนมัติ**: เติบโต / ปันผล / วัฏจักร / มั่นคง แล้วเลือกวิธีประเมินให้ตรงกลุ่ม
- **ราคาที่เหมาะสม + ราคาที่ควรซื้อ** และ Reverse DCF ว่าราคาตอนนี้คาดการเติบโตไว้เท่าไร
""")
    st.stop()

results, errors = {}, {}
with st.spinner("กำลังดึงงบการเงิน..."):
    for s in symbols:
        try:
            results[s] = run(s, kind, r, mos, fair_pe, g_term)
        except Exception as e:  # noqa: BLE001
            errors[s] = str(e)
for s, e in errors.items():
    st.error(f"{s}: {e}")
if not results:
    st.stop()

# ---------------------------------------------------------------------------
# ตารางเปรียบเทียบ (เมื่อใส่หลายตัว)
# ---------------------------------------------------------------------------
if len(results) > 1:
    st.header("เปรียบเทียบ")
    rows = []
    for s, res in results.items():
        rows.append({
            "หุ้น": s, "ประเภท": ms.KIND_TH[res["kind"]], "คะแนน": res["score"]["total"],
            "ราคา": res["data"].price, "Fair Value": res["val"]["fair_value"],
            "ราคาที่ควรซื้อ": res["buy_price"], "ส่วนต่าง": res["mos_actual"],
            "สรุป": res["verdict"].split(" — ")[0],
        })
    comp = pd.DataFrame(rows).sort_values(["คะแนน", "ส่วนต่าง"], ascending=False)
    st.dataframe(comp, hide_index=True, width="stretch", column_config={
        "คะแนน": st.column_config.ProgressColumn("คะแนน", min_value=0, max_value=10, format="%d/10"),
        "ราคา": st.column_config.NumberColumn(format="%.2f"),
        "Fair Value": st.column_config.NumberColumn(format="%.2f"),
        "ราคาที่ควรซื้อ": st.column_config.NumberColumn(format="%.2f"),
        "ส่วนต่าง": st.column_config.NumberColumn(format="percent"),
    })

# ---------------------------------------------------------------------------
# รายตัว
# ---------------------------------------------------------------------------
tabs = st.tabs(list(results)) if len(results) > 1 else [st.container()]
for tab, (sym, res) in zip(tabs, results.items()):
    sd, m, g, sc, v = res["data"], res["metrics"], res["growth"], res["score"], res["val"]
    c = sd.currency
    with tab:
        st.header(f"{sd.name}")
        st.caption(f"{sd.symbol} · {sd.sector or '-'} · งบปี {sd.raw.index[0]}–{sd.raw.index[-1]} · "
                   f"ประเภท: **{ms.KIND_TH[res['kind']]}** ({res['kind_why']})")
        if sd.fx_note:
            st.info(sd.fx_note)
        for w in sd.warnings:
            st.warning(w)

        st.markdown(f'<div class="verdict {verdict_class(res["verdict"])}">{res["verdict"]}</div>',
                    unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("ราคาปัจจุบัน", f"{fmt(sd.price)} {c}")
        k2.metric("ราคาที่เหมาะสม", f"{fmt(v['fair_value'])} {c}",
                  delta=f"{ms.pct(res['mos_actual'])} {'ต่ำกว่า' if ms._nz(res['mos_actual']) > 0 else 'สูงกว่า'}มูลค่า",
                  delta_color="normal" if ms._nz(res["mos_actual"]) > 0 else "inverse")
        k3.metric(f"ราคาที่ควรซื้อ (MOS {mos:.0%})", f"{fmt(res['buy_price'])} {c}")
        k4.metric("คะแนนคุณภาพ", f"{sc['total']}/10")

        left, right = st.columns([1, 1.3])
        with left:
            st.subheader("คะแนนคุณภาพ")
            for name, (pts, val) in sc["parts"].items():
                shown = val if isinstance(val, str) else (fmt(val) if ("หนี้" in name or "OCF" in name) else ms.pct(val))
                st.markdown(f"**{name}** — {shown}")
                st.progress(pts / 2, text=f"{pts}/2")
            if sc["flags"]:
                st.warning("สัญญาณที่ต้องระวัง: " + ", ".join(sc["flags"]))

        with right:
            st.subheader("มูลค่าจากแต่ละวิธี")
            vm = pd.DataFrame([{"วิธี": k, "มูลค่า": val, "ใช้คำนวณ": "ใช้" if k in v["used"] else "อ้างอิง"}
                               for k, val in v["methods"].items() if not pd.isna(val)])
            if not vm.empty:
                bars = alt.Chart(vm).mark_bar(cornerRadiusEnd=3).encode(
                    x=alt.X("มูลค่า:Q", title=c),
                    y=alt.Y("วิธี:N", sort=None, title=None, axis=alt.Axis(labelLimit=220)),
                    color=alt.Color("ใช้คำนวณ:N", scale=alt.Scale(domain=["ใช้", "อ้างอิง"],
                                                                   range=["#3b73c4", "#b8c4d6"]), legend=None),
                    tooltip=["วิธี", alt.Tooltip("มูลค่า:Q", format=",.2f")],
                )
                price_rule = alt.Chart(pd.DataFrame({"x": [sd.price]})).mark_rule(
                    color="#d1495b", strokeWidth=2, strokeDash=[5, 3]).encode(x="x:Q")
                st.altair_chart((bars + price_rule).properties(height=220), width="stretch")
                st.caption("แท่งสีเข้ม = วิธีที่ใช้คำนวณราคาที่เหมาะสม · เส้นแดงประ = ราคาปัจจุบัน")
            st.markdown(
                f"- **Reverse DCF:** ราคานี้คาดว่า FCF จะโต **{ms.pct(v['implied_growth'])}/ปี** ใน 5 ปีแรก\n"
                f"- P/E ล่าสุด **{fmt(v['pe'], 1)}** · PEG **{fmt(v['peg'])}**\n"
                f"- สมมติฐาน: อัตราคิดลด {ms.pct(v['r'])}, โตช่วงแรก {ms.pct(v['g1'])}/ปี, "
                f"ระยะยาว {ms.pct(v['g_term'])}")

        st.subheader("แนวโน้มรายปี")
        ch1, ch2 = st.columns(2)
        per_share = m[["eps", "dps", "fcfps"]].rename(columns={"eps": "EPS", "dps": "DPS", "fcfps": "FCF/หุ้น"})
        per_share.index = per_share.index.astype(str)
        long = per_share.reset_index(names="ปี").melt("ปี", var_name="รายการ", value_name="ค่า")
        ch1.altair_chart(alt.Chart(long).mark_bar().encode(
            x=alt.X("ปี:N", title=None), xOffset="รายการ:N", y=alt.Y("ค่า:Q", title=f"{c} ต่อหุ้น"),
            color=alt.Color("รายการ:N", scale=alt.Scale(range=["#3b73c4", "#2e9e5b", "#d99a26"])),
            tooltip=["ปี", "รายการ", alt.Tooltip("ค่า:Q", format=",.2f")],
        ).properties(height=260, title="ต่อหุ้น"), width="stretch")

        ret = m[["roe", "roic", "net_margin"]].rename(columns={"roe": "ROE", "roic": "ROIC", "net_margin": "Net margin"})
        ret.index = ret.index.astype(str)
        long2 = ret.reset_index(names="ปี").melt("ปี", var_name="รายการ", value_name="ค่า")
        ch2.altair_chart(alt.Chart(long2).mark_line(point=True).encode(
            x=alt.X("ปี:N", title=None), y=alt.Y("ค่า:Q", axis=alt.Axis(format="%"), title=None),
            color=alt.Color("รายการ:N", scale=alt.Scale(range=["#3b73c4", "#2e9e5b", "#d99a26"])),
            tooltip=["ปี", "รายการ", alt.Tooltip("ค่า:Q", format=".1%")],
        ).properties(height=260, title="ผลตอบแทนและอัตรากำไร"), width="stretch")

        st.markdown(f"**การเติบโตเฉลี่ย {g['years']} ปี:** รายได้ {ms.pct(g['revenue_cagr'])} · "
                    f"EPS {ms.pct(g['eps_cagr'])} · FCF/หุ้น {ms.pct(g['fcfps_cagr'])} · "
                    f"BV/หุ้น {ms.pct(g['bvps_cagr'])}")

        table = pd.DataFrame({
            "EPS": m.eps.map(fmt), "DPS": m.dps.map(fmt), "FCF/หุ้น": m.fcfps.map(fmt),
            "BV/หุ้น": m.bvps.map(fmt), "ROE": m.roe.map(ms.pct), "ROIC": m.roic.map(ms.pct),
            "Op margin": m.op_margin.map(ms.pct), "Net margin": m.net_margin.map(ms.pct),
            "D/E": m.de.map(fmt), "OCF/กำไร": m.cash_conversion.map(fmt),
            "Payout": m.payout.map(ms.pct), "P/E": m.pe.map(lambda x: fmt(x, 1)),
            "P/BV": m.pbv.map(fmt), "Div yield": m.div_yield.map(ms.pct),
        }).T
        table.columns = table.columns.astype(str)
        st.dataframe(table, width="stretch")

        with st.expander("ข้อมูลดิบ 12 ค่า"):
            raw_show = sd.raw.rename(columns=ms.LABELS_TH).T
            raw_show.columns = raw_show.columns.astype(str)
            st.dataframe(raw_show.style.format("{:,.2f}", na_rep="-"), width="stretch")

        st.download_button("ดาวน์โหลด Excel", data=ms.excel_bytes(res),
                           file_name=f"{sd.symbol.replace('.', '_')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"dl-{sym}")
        st.caption("ตรวจตัวเลขกับงบจริง (เว็บ SET) ก่อนใช้ · เครื่องมือคัดกรอง ไม่ใช่คำแนะนำการลงทุน")
