"""BizSaathi — one configurable AI operations assistant for local shops, in 11 Indian languages.

Run:  streamlit run app.py
UI rules: the database is the source of truth for every toggle and value; callbacks only record intent in
session state; slow work (AI calls) runs in the page body where a spinner can show. Every visible string goes
through T() (static) or TL() (dynamic) so the whole UI follows the chosen language.
"""
import hashlib
import html
import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

import core

st.set_page_config(page_title="BizSaathi", page_icon="📒", layout="wide", initial_sidebar_state="expanded")
core.init_db()
st.logo("assets/logo.svg", icon_image="assets/icon.svg", size="large")


@st.cache_resource
def get_conn():
    return core.connect()


conn = get_conn()
ss = st.session_state
for k, v in {"cmd": "", "plan": None, "last_result": None, "audio_hash": None, "parse_error": None,
             "to_parse": None, "page": "Assistant", "flash": None, "lang": "en-IN"}.items():
    ss.setdefault(k, v)


# ------------------------------------------------------------------ language layer
@st.cache_data
def load_i18n() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


I18N = load_i18n()
LANG = ss.lang
_missing: list[str] = []


def T(s: str) -> str:
    """Translate a static UI string (pre-built i18n.json, then the SQLite cache, else queued for one batch call)."""
    if LANG == "en-IN":
        return s
    hit = I18N.get(LANG, {}).get(s)
    if hit:
        return hit
    row = conn.execute("SELECT dst FROM translations WHERE lang=? AND src=?", (LANG, s)).fetchone()
    if row:
        return row[0]
    _missing.append(s)
    return s


def TL(items: list[str]) -> list[str]:
    """Translate dynamic text (actions, errors, reminders) live with Sarvam Translate; cached in SQLite."""
    return core.translate_many(list(items), LANG, conn) if LANG != "en-IN" else list(items)


# ------------------------------------------------------------------ styles
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root { --ink:#17201b; --muted:#5d6a63; --line:#e3e7e4; --brand:#1f6f4a; --brand-soft:#e9f3ee;
        --bad:#b42318; --card:#ffffff; --bg:#f7f8f6; }
html, body, .stMarkdown, .stTextInput, .stButton button { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: var(--bg); }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1180px; }
section[data-testid="stSidebar"] { background: #fff; border-right: 1px solid var(--line); }
.page-title { font-size: 1.55rem; font-weight: 700; color: var(--ink); margin: 0; }
.page-sub { color: var(--muted); margin: 2px 0 14px 0; font-size: .95rem; }
.brand { font-weight: 700; font-size: 1.25rem; color: var(--ink); }
.brand-sub { color: var(--muted); font-size: .85rem; margin-bottom: 6px; }
.chip { display:inline-block; padding: 2px 9px; border-radius: 999px; font-size: .75rem; font-weight: 500;
        border: 1px solid var(--line); background: #fff; color: var(--muted); margin: 0 4px 4px 0; }
.chip.ok { color: var(--brand); border-color: #bcd9c9; background: var(--brand-soft); }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; height: 100%; }
.kpi .l { font-size: .74rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; font-weight: 600; }
.kpi .v { font-size: 1.55rem; font-weight: 700; color: var(--ink); margin-top: 4px; }
.kpi .s { font-size: .8rem; color: var(--muted); }
.steps { display:flex; gap: 8px; margin: 4px 0 16px 0; flex-wrap: wrap; }
.step { flex: 1; min-width: 150px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line);
        background: #fff; color: var(--muted); font-size: .88rem; }
.step b { display:block; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; }
.step.cur { border-color: var(--brand); color: var(--ink); box-shadow: 0 0 0 1px var(--brand) inset; }
.step.done { color: var(--brand); }
.row { display:flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.row:last-child { border-bottom: none; }
.row.total { font-weight: 700; font-size: 1.05rem; }
.row.due { font-weight: 700; color: var(--bad); }
.act { padding: 8px 12px; margin: 6px 0; border-radius: 8px; background: var(--brand-soft); color: var(--ink);
       border-left: 3px solid var(--brand); font-size: .93rem; }
.skip { padding: 8px 12px; margin: 6px 0; border-radius: 8px; background: #f1f2f0; color: var(--muted);
        border-left: 3px solid #a9b1ac; font-size: .93rem; }
.saved { padding: 14px 16px; border-radius: 12px; background: var(--brand-soft); border: 1px solid #bcd9c9; margin-bottom: 6px; }
.saved .t { font-weight: 700; font-size: 1.05rem; color: var(--brand); }
.muted { color: var(--muted); font-size: .85rem; }
.stButton button, .stFormSubmitButton button, .stDownloadButton button { border-radius: 8px; font-weight: 500; }
</style>""", unsafe_allow_html=True)


def inr(x) -> str:
    if x is None:
        return "—"
    return f"₹{x:,.0f}" if abs(x - round(x)) < 0.005 else f"₹{x:,.2f}"


def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="l">{html.escape(label)}</div><div class="v">{value}</div>'
                 f'<div class="s">{html.escape(sub)}</div></div>', unsafe_allow_html=True)


def header(title, sub=""):
    st.markdown(f'<p class="page-title">{html.escape(title)}</p><p class="page-sub">{html.escape(sub)}</p>',
                unsafe_allow_html=True)


def flash():
    if ss.flash:
        kind, msg = ss.flash
        getattr(st, kind)(msg)
        ss.flash = None


def reset_ui_state():
    """After the database is replaced, forget every widget value that mirrored the old data."""
    for k in list(ss.keys()):
        if k.startswith(("tog_", "ed_", "in_", "cu_", "pa_", "me_", "catalog_editor", "biz_name", "voice_", "rem_",
                         "ok_setup", "nm_")):
            del ss[k]
    ss.plan = ss.last_result = ss.parse_error = ss.to_parse = None
    ss.cmd = ""
    ss.catalog_ver = ss.get("catalog_ver", 0) + 1


# ------------------------------------------------------------------ sidebar
modules = core.get_modules(conn)


def on_toggle(m):
    core.set_module(conn, m, bool(ss[f"tog_{m}"]))
    if ss.plan:
        core.recompute(ss.plan, core.get_modules(conn), conn)


PAGES = [("Assistant", None), ("Dashboard", None), ("Orders", "Orders"), ("Invoices", "Invoices"),
         ("Customers & Dues", None), ("Inventory", "Inventory"), ("Follow-ups", "Follow-ups"),
         ("Insights", "Business Insights"), ("Settings", None)]

with st.sidebar:
    st.markdown(f'<div class="brand-sub">{html.escape(core.get_setting(conn, "business_name", "My Shop"))}</div>',
                unsafe_allow_html=True)
    st.selectbox(T("Language"), list(core.LANGUAGES), format_func=core.LANGUAGES.get, key="lang")
    visible = [p for p, need in PAGES if need is None or modules.get(need)]
    # Re-assert the page every run: toggling a module changes the radio's options, which makes Streamlit treat it
    # as a new widget that would otherwise snap back to the first page.
    ss.page = ss.page if ss.page in visible else "Assistant"
    st.radio(T("Navigate"), visible, key="page", format_func=T, label_visibility="collapsed")
    st.divider()
    st.markdown(f"**{T('Capabilities')}**")
    st.caption(T("Switch on only what your business needs. A switched-off module never runs."))
    for m in core.MODULES:
        ss[f"tog_{m}"] = modules[m]  # database is the source of truth (shared across devices)
        st.toggle(T(m), key=f"tog_{m}", on_change=on_toggle, args=(m,))
    st.divider()
    ok = core.ai_available()
    st.markdown(f'<span class="chip {"ok" if ok else ""}">{T("Sarvam AI connected") if ok else T("API key missing")}</span>'
                '<span class="chip">Sarvam-105B</span><span class="chip">Saaras v4</span>'
                '<span class="chip">Sarvam Translate</span><span class="chip">Bulbul v3</span>', unsafe_allow_html=True)

modules = core.get_modules(conn)


def kpi_row():
    s = core.dashboard_stats(conn)
    c = st.columns(4)
    kpi(c[0], T("Today's sales"), inr(s["sales_today"]), f'{s["orders_today"]} {T("orders today")}')
    kpi(c[1], T("Collected today"), inr(s["collected_today"]) if modules["Payments"] else T("Off"), T("payments received"))
    kpi(c[2], T("Outstanding dues"), inr(s["outstanding"]) if modules["Payments"] else T("Off"), T("all customers"))
    kpi(c[3], T("Low-stock items"), s["low_stock"] if modules["Inventory"] else T("Off"), T("at or below reorder level"))


def money_cols(*names):
    return {n: st.column_config.NumberColumn(T(n), format="₹%.2f") for n in names}


# ------------------------------------------------------------------ invoice
def invoice_html(order_id: int) -> str | None:
    d = core.invoice_data(conn, order_id)
    if not d:
        return None
    o = d["order"]
    paid = sum(p["amount"] for p in d["payments"])
    L = {k: html.escape(T(k)) for k in ("Bill / Receipt", "Billed to", "Item", "Qty", "Rate", "Amount", "Total", "Paid",
                                        "Balance due", "Print bill",
                                        "Generated by BizSaathi. Simple receipt — not a GST tax invoice.")}
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{html.escape(it['name'])}</td><td class=r>{it['quantity']} {html.escape(it['unit'])}</td>"
        f"<td class=r>₹{it['unit_price']:,.2f}</td><td class=r>₹{it['line_total']:,.2f}</td></tr>"
        for i, it in enumerate(d["items"]))
    pays = "".join(f"<tr><td colspan=4 class=r>{L['Paid']} · {p['method'].upper()} · {p['created_at'][:16]}</td>"
                   f"<td class=r>− ₹{p['amount']:,.2f}</td></tr>" for p in d["payments"])
    title = o["invoice_no"] or f"Order #{o['id']}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Inter,-apple-system,Segoe UI,Arial,sans-serif;color:#17201b;background:#fff;margin:0;padding:16px}}
.inv{{max-width:640px;margin:auto;border:1px solid #e3e7e4;border-radius:12px;padding:22px}}
h2{{margin:0;font-size:20px}} table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}}
th,td{{padding:8px 6px;border-bottom:1px solid #eef0ee;text-align:left}} th{{background:#f7f8f6;font-weight:600}}
.r{{text-align:right}} .muted{{color:#5d6a63;font-size:13px}} .tot td{{font-weight:700}} .due td{{font-weight:700;color:#b42318}}
button{{padding:8px 14px;border-radius:8px;border:1px solid #cfd6d2;background:#fff;cursor:pointer;font:inherit}}
@media print{{.noprint{{display:none}} body{{padding:0}} .inv{{border:none}}}}</style></head><body><div class="inv">
<div style="display:flex;justify-content:space-between;gap:12px">
<div><h2>{html.escape(core.get_setting(conn, 'business_name', 'My Shop'))}</h2><div class="muted">{L['Bill / Receipt']}</div></div>
<div style="text-align:right"><b>{title}</b><div class="muted">{(o['invoice_date'] or o['created_at'])[:16]}</div></div></div>
<p><span class="muted">{L['Billed to']}</span><br><b>{html.escape(o['customer'])}</b>{('<br>' + html.escape(o['phone'])) if o['phone'] else ''}</p>
<table><tr><th>#</th><th>{L['Item']}</th><th class=r>{L['Qty']}</th><th class=r>{L['Rate']}</th><th class=r>{L['Amount']}</th></tr>
{rows}<tr class="tot"><td colspan=4 class=r>{L['Total']}</td><td class=r>₹{o['total']:,.2f}</td></tr>
{pays}<tr class="due"><td colspan=4 class=r>{L['Balance due']}</td><td class=r>₹{o['total'] - paid:,.2f}</td></tr></table>
<p class="muted" style="margin-top:16px">{L['Generated by BizSaathi. Simple receipt — not a GST tax invoice.']}</p>
<button class="noprint" onclick="window.print()">{L['Print bill']}</button></div></body></html>"""


def show_invoice(order_id: int, key: str):
    h = invoice_html(order_id)
    if not h:
        st.warning(T("Order not found."))
        return
    st.components.v1.html(h, height=520, scrolling=True)
    st.download_button(T("Download bill (.html)"), h, file_name=f"bill-order-{order_id}.html", mime="text/html", key=key)


# ------------------------------------------------------------------ assistant: state changes (callbacks)
def samples() -> list[tuple[str, str]]:
    """Example commands built from this shop's own catalog, so they work for any business type."""
    amit = core.find_customer("Amit", conn)
    due = core.customer_dues(conn, amit["id"]) if amit else 0
    pay_text = f"Amit paid ₹{50 if due >= 50 or due < 1 else int(due)} towards his dues by UPI."  # never more than owed
    if core.get_setting(conn, "business_type") == core.DEFAULT_TEMPLATE:
        return [("Sale with advance", "Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance."),
                ("Payment against dues", pay_text),
                ("Not enough stock", "Amit wants 20 bags of basmati rice."),
                ("Hindi", "प्रिया ने 2 किलो चीनी और 3 मैगी ली, 50 रुपये UPI से दिए"),
                ("Bengali", "সুনীতা ৪টা সাবান আর ২ প্যাকেট দুধ নিয়েছে, ১০০ টাকা দিয়েছে")]
    prods = conn.execute("SELECT name, price, stock FROM products ORDER BY id").fetchall()
    if not prods:
        return []
    p0, p1 = prods[0], prods[1] if len(prods) > 1 else prods[0]
    low = min(prods, key=lambda p: p["stock"])
    return [("Sale with advance", f"Rahul bought 3 {p0['name']} and 1 {p1['name']}. He paid ₹{int(p0['price'] * 3 // 2)} in advance."),
            ("Payment against dues", pay_text),
            ("Not enough stock", f"Amit wants {low['stock'] + 20} {low['name']}."),
            ("Hinglish", f"Priya ne 2 {p1['name']} liye, poora paisa cash mein diya")]


def queue_parse(text=None):
    """Callback: remember what to parse; the page body does the (slow) AI call with a spinner."""
    if text is not None:
        ss.cmd = text
    ss.to_parse = ss.cmd or ""
    ss.last_result = None


def set_plan(plan):
    plan["base_lines"] = [dict(l) for l in plan["lines"]]  # the editor always starts from this, never from edits
    ss.plan, ss.parse_error, ss.last_result = plan, None, None


def start_manual():
    plan = core.build_plan({"intent": "sale", "customer_name": None, "items": [], "payment_amount": None,
                            "payment_method": "cash"}, modules, conn)
    plan.update(errors=[], source_text="", source="manual")
    set_plan(plan)


def discard_plan():
    ss.plan = None


def new_entry():
    ss.last_result = None
    ss.cmd = ""


def do_parse(text):
    text = (text or "").strip()
    if not text:
        ss.parse_error = T("Type or speak what happened first.")
        return
    try:
        with st.spinner(T("Reading your instruction with Sarvam-105B…")):
            parsed = core.parse_command(text, conn)
    except Exception:
        ss.plan = None
        ss.parse_error = T("The AI couldn't read that right now. Try again, or use Manual entry.")
        return
    plan = core.build_plan(parsed, modules, conn)
    plan.update(source_text=text, source="ai")
    set_plan(plan)


def confirm_plan():
    plan = ss.plan
    if not plan or plan["errors"]:
        return
    try:
        res = core.commit_plan(plan, core.get_modules(conn), conn)
        ss.last_result = {"plan": plan, "res": res}
        ss.plan = None
        ss.cmd = ""
    except core.DuplicateSubmission:
        ss.flash = ("error", T("This entry was already saved — duplicate submission blocked."))
    except Exception as e:
        ss.flash = ("error", f"{T('Nothing was saved.')} {e}")


def resubmit_last():
    try:
        core.commit_plan(ss.last_result["plan"], core.get_modules(conn), conn)
        ss.flash = ("error", "Saved twice — this should never happen.")
    except core.DuplicateSubmission:
        ss.flash = ("success", T("Blocked by the database: this entry was already saved, so it was not saved twice."))


def spoken_summary(plan) -> str:
    if plan["intent"] == "sale":
        s = f"Order saved for {plan['customer_name']}. Bill {plan['subtotal']:.0f} rupees"
        if plan["payment_amount"] and modules["Payments"]:
            s += f", paid {plan['payment_amount']:.0f} rupees"
        return s + f". {plan['balance']:.0f} rupees outstanding."
    if plan["intent"] == "payment":
        return (f"Received {plan['payment_amount']:.0f} rupees from {plan['customer_name']}. "
                f"{plan['balance']:.0f} rupees still due.")
    return "Stock updated."


# ------------------------------------------------------------------ assistant: rendering
def render_preview():
    plan = ss.plan
    rid = plan["request_id"]
    products = {p["name"]: p for p in conn.execute("SELECT * FROM products ORDER BY name")}
    with st.container(border=True):
        st.markdown(f"#### {T('Review before saving')}")
        if plan.get("source") == "ai":
            lang = f" · {plan['language']}" if plan.get("language") else ""
            st.caption(f"{T('Understood by Sarvam-105B')}{lang} — “{plan.get('source_text', '')}”. {T('Edit anything below.')}")
        else:
            st.caption(T("Manual entry — fill in the details below."))

        intents = {"sale": "Sale", "payment": "Payment received", "restock": "Stock received"}
        c1, c2, c3, c4 = st.columns([1.2, 1.6, 1, 1])
        intent = c1.selectbox(T("Type"), list(intents), format_func=lambda k: T(intents[k]), key=f"in_{rid}",
                              index=list(intents).index(plan["intent"]) if plan["intent"] in intents else 0)
        cust = c2.text_input(T("Customer"), value=plan["customer_name"] or "", key=f"cu_{rid}",
                             disabled=intent == "restock", placeholder="Walk-in Customer")
        pay = c3.number_input(T("Paid now (₹)"), min_value=0.0, step=10.0, value=float(plan["payment_amount"] or 0),
                              key=f"pa_{rid}", disabled=intent == "restock")
        methods = ["cash", "upi", "card", "other"]
        method = c4.selectbox(T("Method"), methods, format_func=str.upper, key=f"me_{rid}", disabled=intent == "restock",
                              index=methods.index(plan["payment_method"]) if plan["payment_method"] in methods else 0)

        new_lines = []
        if intent != "payment":
            base = pd.DataFrame([{"Product": l["product"], "You said": l["spoken"],
                                  "Qty": l["quantity"] if isinstance(l["quantity"], int) else None,
                                  "Rate (₹)": l["unit_price"] if l["product"] else None} for l in plan["base_lines"]],
                                columns=["Product", "You said", "Qty", "Rate (₹)"])
            st.markdown(f"**{T('Items')}**")
            edited = st.data_editor(
                base, num_rows="dynamic", width="stretch", hide_index=True, key=f"ed_{rid}",
                column_config={
                    "Product": st.column_config.SelectboxColumn(T("Product"), options=list(products), required=True,
                                                                width="large"),
                    "You said": st.column_config.TextColumn(T("You said"), disabled=True),
                    "Qty": st.column_config.NumberColumn(T("Qty"), min_value=1, step=1, format="%d", required=True),
                    "Rate (₹)": st.column_config.NumberColumn(T("Rate (₹)"), min_value=0.0, step=1.0, format="%.2f",
                                                             help=T("Leave empty to use your catalog price.")),
                })
            for _, r in edited.iterrows():
                name = r["Product"] if isinstance(r["Product"], str) else None
                p = products.get(name)
                q = r["Qty"]
                q = int(q) if pd.notna(q) and float(q) == int(q) else (None if pd.isna(q) else q)
                rate = float(r["Rate (₹)"]) if pd.notna(r["Rate (₹)"]) else (float(p["price"]) if p else 0.0)
                spoken = r["You said"] if isinstance(r["You said"], str) and r["You said"] else None
                if name is None and q is None and spoken is None:
                    continue  # empty row the owner just added and hasn't filled yet
                new_lines.append({"spoken": spoken or name or "new row", "product_id": p["id"] if p else None,
                                  "product": name, "unit": p["unit"] if p else "", "quantity": q, "unit_price": rate,
                                  "line_total": 0.0, "stock": None, "ok": True})
        plan.update(intent=intent, lines=new_lines, customer_name=cust.strip() or None,
                    payment_amount=0.0 if intent == "restock" else float(pay), payment_method=method)
        core.recompute(plan, modules, conn)

        acts, skips, warns, errs = (TL(plan[k]) for k in ("actions", "skipped", "warnings", "errors"))
        left, right = st.columns([1.35, 1], gap="large")
        with left:
            st.markdown(f"**{T('What will happen when you confirm')}**")
            if not acts:
                st.caption(T("Nothing yet — add the details above."))
            for a in acts:
                st.markdown(f'<div class="act">{html.escape(a)}</div>', unsafe_allow_html=True)
            for s in skips:
                st.markdown(f'<div class="skip">{html.escape(T("Skipped"))} — {html.escape(s)}</div>', unsafe_allow_html=True)
        with right:
            if intent == "sale":
                paid = plan["payment_amount"] if modules["Payments"] else 0
                st.markdown(f'<div class="row total"><span>{T("Bill total")}</span><span>{inr(plan["subtotal"])}</span></div>'
                            f'<div class="row"><span>{T("Paid now")}</span><span>{inr(paid)}</span></div>'
                            f'<div class="row due"><span>{T("Outstanding")}</span><span>{inr(plan["balance"])}</span></div>',
                            unsafe_allow_html=True)
                if plan["prior_dues"] > 0:
                    st.caption(f"{plan['customer_name']}: {T('earlier dues')} {inr(plan['prior_dues'])}")
            elif intent == "payment":
                st.markdown(f'<div class="row"><span>{T("Dues before")}</span><span>{inr(plan["prior_dues"])}</span></div>'
                            f'<div class="row total"><span>{T("Paying now")}</span><span>{inr(plan["payment_amount"])}</span></div>'
                            f'<div class="row due"><span>{T("Remaining")}</span><span>{inr(plan["balance"])}</span></div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="row total"><span>{T("Units received")}</span>'
                            f'<span>{sum(l["quantity"] for l in plan["lines"] if l["ok"])}</span></div>',
                            unsafe_allow_html=True)
        for w in warns:
            st.warning(w)
        for e in errs:
            st.error(e)

        b1, b2, _ = st.columns([1.3, 1, 3])
        b1.button(T("Confirm & save"), type="primary", disabled=bool(plan["errors"]) or not plan["actions"],
                  width="stretch", on_click=confirm_plan, key=f"ok_{rid}")
        b2.button(T("Discard"), width="stretch", on_click=discard_plan, key=f"no_{rid}")


def render_result():
    plan, res = ss.last_result["plan"], ss.last_result["res"]
    rid = plan["request_id"]
    title = {"sale": f"{T('Order saved')} #{res['order_id']} · {plan['customer_name']}",
             "payment": f"{T('Payment received')} · {inr(plan['payment_amount'])} · {plan['customer_name']}",
             "restock": T("Stock updated")}[plan["intent"]]
    with st.container(border=True):
        st.markdown(f'<div class="saved"><div class="t">{html.escape(title)}</div>'
                    f'<div class="muted">{html.escape(T("All changes were written together in one database transaction."))}</div></div>',
                    unsafe_allow_html=True)
        # Spoken confirmation in the owner's language (Sarvam Translate + Bulbul v3), generated once per entry.
        vkey = f"voice_{rid}_{LANG}"
        if vkey not in ss:
            try:
                with st.spinner(T("Preparing spoken confirmation…")):
                    text = TL([spoken_summary(plan)])[0]
                    ss[vkey] = (text, core.speak(text, LANG))
            except Exception:
                ss[vkey] = (None, None)
        text, audio = ss[vkey]
        if audio:
            st.caption(f"{T('Spoken confirmation')}: “{text}”")
            st.audio(audio, format="audio/wav", autoplay=True)
        for a in TL(plan["actions"]):
            st.markdown(f'<div class="act">{html.escape(a)}</div>', unsafe_allow_html=True)
        for s in TL(plan["skipped"]):
            st.markdown(f'<div class="skip">{html.escape(T("Skipped"))} — {html.escape(s)}</div>', unsafe_allow_html=True)
        c1, c2, _ = st.columns([1.2, 1.6, 2])
        c1.button(T("Record another"), type="primary", on_click=new_entry, width="stretch")
        c2.button(T("Test: submit the same entry again"), on_click=resubmit_last, width="stretch",
                  help=T("Every preview has a one-time ID; the database refuses to save it twice."))
        if plan["intent"] == "sale" and res.get("invoice_no"):
            st.markdown(f"**{T('Bill')} {res['invoice_no']}**")
            show_invoice(res["order_id"], key=f"dl_last_{res['order_id']}")


def page_assistant():
    header(T("What happened in the shop?"),
           T("Say it or type it in any Indian language. BizSaathi prepares the order, bill, payment and stock update — you check it, then confirm."))
    step = 3 if ss.last_result and not ss.plan else 2 if ss.plan else 1
    steps = [(T("Tell"), T("Type or speak what happened")), (T("Review"), T("Check and edit the changes")),
             (T("Saved"), T("Bill, dues and stock updated"))]
    st.markdown('<div class="steps">' + "".join(
        f'<div class="step {"cur" if i == step else "done" if i < step else ""}"><b>{i} · {html.escape(a)}</b>{html.escape(b)}</div>'
        for i, (a, b) in enumerate(steps, 1)) + "</div>", unsafe_allow_html=True)
    flash()

    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info(T("Your catalog is empty. Add products on the Inventory page, or choose a business type in Settings."))

    if not ss.plan and not ss.last_result:
        with st.container(border=True):
            audio = st.audio_input(T("Speak (Sarvam Saaras speech-to-text)"), key="mic")
            if audio is not None:
                data = audio.getvalue()
                h = hashlib.md5(data).hexdigest()
                if h != ss.audio_hash:
                    ss.audio_hash = h
                    try:
                        with st.spinner(T("Transcribing with Sarvam Saaras…")):
                            names = [r[0] for r in conn.execute("SELECT name FROM products")] + \
                                    [r[0] for r in conn.execute("SELECT name FROM customers")]
                            text = core.transcribe(data, "command.wav", keyterms=names,
                                                   language_code="unknown" if LANG == "en-IN" else LANG)
                        if text:
                            ss.cmd = text
                            ss.to_parse = text
                        else:
                            ss.parse_error = T("Didn't catch that — please try again or type it.")
                    except Exception:
                        ss.parse_error = T("Voice input failed. Please type the instruction.")

            with st.form("cmd_form", border=False):
                st.text_area(T("Or type it"), key="cmd", height=90,
                             placeholder="Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance.")
                f1, f2, _ = st.columns([1, 1, 3])
                f1.form_submit_button(T("Understand"), type="primary", width="stretch", on_click=queue_parse)
                f2.form_submit_button(T("Manual entry"), width="stretch", on_click=start_manual)
            ex = samples()
            if ex:
                st.caption(T("Or try an example"))
                cols = st.columns(len(ex))
                for col, (label, text) in zip(cols, ex):
                    col.button(T(label), width="stretch", on_click=queue_parse, args=(text,), key=f"ex_{label}")

    if ss.to_parse is not None:  # "" too, so an empty submit shows the friendly error
        text, ss.to_parse = ss.to_parse, None
        do_parse(text)
        st.rerun()

    if ss.parse_error:
        st.error(ss.parse_error)
        ss.parse_error = None
    if ss.plan:
        render_preview()
    elif ss.last_result:
        render_result()
    st.write("")
    kpi_row()


# ------------------------------------------------------------------ other pages
def page_dashboard():
    header(T("Dashboard"), T("Live numbers from your saved orders, payments and stock."))
    kpi_row()
    st.write("")
    a, b = st.columns([1.6, 1], gap="large")
    with a, st.container(border=True):
        st.markdown(f"**{T('Recent orders')}**")
        rows = core.orders_table(conn)[:8]
        if rows:
            st.dataframe(pd.DataFrame([{"#": r["id"], T("When"): r["created_at"][:16], T("Customer"): r["customer"],
                                        T("Items"): r["items"], "Total": r["total"], "Due": r["due"]} for r in rows]),
                         hide_index=True, width="stretch", column_config=money_cols("Total", "Due"))
        else:
            st.caption(T("No orders yet."))
    with b:
        if modules["Inventory"]:
            with st.container(border=True):
                st.markdown(f"**{T('Low stock')}**")
                low = conn.execute("SELECT name, stock, low_stock_at FROM products WHERE stock <= low_stock_at "
                                   "ORDER BY stock").fetchall()
                for p in low:
                    st.markdown(f"**{p['name']}** — {p['stock']} {T('left')} · {T('reorder at')} {p['low_stock_at']}")
                if not low:
                    st.caption(T("Everything is above its reorder level."))
        if modules["Payments"]:
            with st.container(border=True):
                st.markdown(f"**{T('Who owes you')}**")
                dues = [c for c in core.customers_with_dues(conn) if c["due"] > 0.001][:5]
                for c in dues:
                    st.markdown(f"{c['name']} — **{inr(c['due'])}**")
                if not dues:
                    st.caption(T("No pending dues."))


def page_orders():
    header(T("Orders"), T("Every sale, with what was paid and what is still due."))
    q = st.text_input(T("Search"), placeholder=T("Customer, product, order # or invoice #"))
    rows = core.orders_table(conn, q)
    if not rows:
        st.info(T("No matching orders."))
        return
    st.dataframe(pd.DataFrame([{"#": r["id"], T("When"): r["created_at"][:16], T("Customer"): r["customer"],
                                T("Items"): r["items"], "Total": r["total"], "Paid": r["paid"], "Due": r["due"],
                                T("Invoice"): r["invoice_no"] or "—"} for r in rows]),
                 hide_index=True, width="stretch", column_config=money_cols("Total", "Paid", "Due"))
    if modules["Invoices"]:
        opts = {f"#{r['id']} · {r['customer']} · {inr(r['total'])}": r["id"] for r in rows}
        pick = st.selectbox(T("Open the bill for an order"), list(opts))
        show_invoice(opts[pick], key=f"dl_ord_{opts[pick]}")


def page_invoices():
    header(T("Invoices"), T("Printable bills for every order."))
    rows = [r for r in core.orders_table(conn) if r["invoice_no"]]
    if not rows:
        st.info(T("No invoices yet."))
        return
    labels = {f"{r['invoice_no']} · {r['customer']} · {inr(r['total'])}": r["id"] for r in rows}
    choice = st.selectbox(T("Invoice"), list(labels))
    show_invoice(labels[choice], key=f"dl_inv_{labels[choice]}")


def save_customer():
    n, ph = ss.new_cust_name.strip(), ss.new_cust_phone.strip()
    if not n:
        ss.flash = ("error", T("Enter a name."))
        return
    conn.execute("INSERT INTO customers(name, phone, created_at) VALUES (?,?,?) "
                 "ON CONFLICT(name) DO UPDATE SET phone=excluded.phone", (n, ph, core.now()))
    ss.flash = ("success", f"{T('Saved')} {n}.")
    ss.new_cust_name = ss.new_cust_phone = ""


def page_customers():
    header(T("Customers & Dues"), T("Who bought, how much they paid, and what they still owe."))
    flash()
    rows = core.customers_with_dues(conn)
    st.dataframe(pd.DataFrame([{T("Customer"): r["name"], T("Phone"): r["phone"] or "", "Billed": r["billed"],
                                "Paid": r["paid"], "Due": r["due"], T("Last order"): (r["last_order"] or "")[:10]}
                               for r in rows]), hide_index=True, width="stretch",
                 column_config=money_cols("Billed", "Paid", "Due"))
    if modules["Customer Management"]:
        with st.container(border=True):
            st.markdown(f"**{T('Add or update a customer')}**")
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            c1.text_input(T("Name"), key="new_cust_name")
            c2.text_input(T("Phone"), key="new_cust_phone")
            c3.button(T("Save"), type="primary", width="stretch", on_click=save_customer, key="save_cust")


def page_inventory():
    header(T("Inventory & catalog"), T("Edit prices, stock and the names customers use for each item, or add rows. The AI reads this catalog, so any kind of shop works."))
    flash()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    df = pd.DataFrame([{"Status": T("Low") if r["stock"] <= r["low_stock_at"] else T("OK"), "name": r["name"],
                        "unit": r["unit"], "price": r["price"], "stock": r["stock"], "low_stock_at": r["low_stock_at"],
                        "aliases": r["aliases"]} for r in rows],
                      columns=["Status", "name", "unit", "price", "stock", "low_stock_at", "aliases"])
    ss.setdefault("catalog_ver", 0)
    edited = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch",
                            key=f"catalog_editor_{ss.catalog_ver}",
                            column_config={
                                "Status": st.column_config.TextColumn(T("Status"), disabled=True, width="small"),
                                "name": st.column_config.TextColumn(T("Product"), required=True),
                                "unit": st.column_config.TextColumn(T("Unit"), width="small"),
                                "price": st.column_config.NumberColumn(T("Price (₹)"), min_value=0.0, format="%.2f"),
                                "stock": st.column_config.NumberColumn(T("Stock"), min_value=0, step=1, format="%d"),
                                "low_stock_at": st.column_config.NumberColumn(T("Reorder at"), min_value=0, step=1, format="%d"),
                                "aliases": st.column_config.TextColumn(T("Also called (comma-separated)"), width="large"),
                            })
    if st.button(T("Save catalog"), type="primary", key="save_catalog"):
        try:
            n = core.save_catalog(conn, edited.to_dict("records"))
            ss.catalog_ver += 1  # a fresh editor, so the browser's old edits aren't re-applied to the saved rows
            ss.flash = ("success", f"{T('Saved')}: {n}")
        except ValueError as e:
            ss.flash = ("error", str(e))
        st.rerun()
    with st.container(border=True):
        st.markdown(f"**{T('Recent stock movements')}**")
        moves = conn.execute("""SELECT m.created_at, p.name, m.change, m.reason, m.ref FROM stock_moves m
                                JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 12""").fetchall()
        if moves:
            st.dataframe(pd.DataFrame([{T("When"): m["created_at"][:16], T("Product"): m["name"],
                                        T("Change"): m["change"], T("Reason"): T(m["reason"]), "Ref": m["ref"] or ""}
                                       for m in moves]), hide_index=True, width="stretch")
        else:
            st.caption(T("No movements yet."))


def page_followups():
    header(T("Follow-ups"), T("Customers with unpaid balances, oldest first, with a reminder in your language."))
    due = [c for c in core.customers_with_dues(conn) if c["due"] > 0.001]
    if not due:
        st.success(T("No pending dues."))
        return
    biz = core.get_setting(conn, "business_name", "our shop")
    due = sorted(due, key=lambda c: c["last_order"] or "")
    msgs = TL([f"Hello {c['name'].split()[0]}, this is a reminder from {biz}: {c['due']:,.0f} rupees is pending on "
               f"your account. You can pay by UPI or cash at your convenience. Thank you!" for c in due])
    for c, msg in zip(due, msgs):
        days = (datetime.now() - datetime.strptime(c["last_order"][:19], "%Y-%m-%d %H:%M:%S")).days if c["last_order"] else 0
        with st.container(border=True):
            st.markdown(f"**{c['name']}** · {T('owes')} **{inr(c['due'])}** · {T('last purchase')}: {days} {T('days ago')}")
            st.code(msg, language=None, wrap_lines=True)
            key = f"rem_{c['id']}_{LANG}"
            if st.button(T("Listen"), key=f"btn_{key}"):
                try:
                    with st.spinner(T("Generating voice with Bulbul…")):
                        ss[key] = core.speak(msg, LANG)
                except Exception:
                    st.warning(T("Voice is unavailable right now."))
            if ss.get(key):
                st.audio(ss[key], format="audio/wav")


def page_insights():
    header(T("Insights"), T("Computed directly from your saved orders — no AI guesses."))
    daily = pd.read_sql_query("SELECT date(created_at) AS day, SUM(total) AS sales FROM orders "
                              "GROUP BY day ORDER BY day", conn)
    top = pd.read_sql_query("""SELECT p.name AS Product, SUM(oi.quantity) AS Units, SUM(oi.line_total) AS Revenue
                               FROM order_items oi JOIN products p ON p.id=oi.product_id
                               GROUP BY p.id ORDER BY Revenue DESC LIMIT 8""", conn)
    billed = conn.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    c = st.columns(3)
    kpi(c[0], T("Total billed"), inr(billed))
    kpi(c[1], T("Collected"), inr(paid), f"{(paid / billed * 100 if billed else 0):.0f}% {T('collection rate')}")
    kpi(c[2], T("Customers"), conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
    st.write("")
    a, b = st.columns(2, gap="large")
    with a, st.container(border=True):
        st.markdown(f"**{T('Sales by day (₹)')}**")
        if daily.empty:
            st.caption(T("No sales yet."))
        else:
            st.bar_chart(daily.set_index("day"), color="#1f6f4a")
    with b, st.container(border=True):
        st.markdown(f"**{T('Top products by revenue')}**")
        if top.empty:
            st.caption(T("No sales yet."))
        else:
            st.dataframe(top, hide_index=True, width="stretch", column_config=money_cols("Revenue"))


def setup_shop(t, name):
    get_conn.clear()
    core.init_db(reset=True, template=t, business_name=(name or "").strip() or None)
    reset_ui_state()
    ss.flash = ("success", f"{T('Ready')}: {t}")


def save_name():
    core.set_setting(conn, "business_name", ss.biz_name.strip() or "My Shop")
    ss.flash = ("success", T("Business name saved."))


def page_settings():
    header(T("Settings"), T("Your business details and demo controls."))
    flash()
    with st.container(border=True):
        st.markdown(f"**{T('Business name')}**")
        if "biz_name" not in ss:
            ss.biz_name = core.get_setting(conn, "business_name", "")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        c1.text_input(T("Business name"), key="biz_name", label_visibility="collapsed")
        c2.button(T("Save"), on_click=save_name, width="stretch", key="save_name")
    with st.container(border=True):
        st.markdown(f"**{T('Set up for a different kind of business')}**")
        st.caption(T("Loads a starter catalog for that business type. The AI, rules, bills and dues work the same for every type. This replaces all current data."))
        types = list(core.BUSINESS_TEMPLATES)
        cur = core.get_setting(conn, "business_type", core.DEFAULT_TEMPLATE)
        t = st.selectbox(T("Business type"), types, index=types.index(cur) if cur in types else 0, key="setup_type")
        name = st.text_input(T("Shop name"), core.BUSINESS_TEMPLATES[t][0], key=f"nm_{t}")
        ok = st.checkbox(T("I understand this replaces the current orders, customers and stock"), key="ok_setup")
        st.button(T("Set up shop"), type="primary", disabled=not ok, on_click=setup_shop, args=(t, name), key="setup_btn")
    with st.container(border=True):
        st.markdown(f"**{T('Reset demo data')}**")
        st.caption(T("Restores the starter catalog, three customers and three past orders for the current business type."))
        st.button(T("Reset demo data"), key="reset_btn",
                  on_click=setup_shop, args=(cur, core.get_setting(conn, "business_name", "")))


{"Assistant": page_assistant, "Dashboard": page_dashboard, "Orders": page_orders, "Invoices": page_invoices,
 "Customers & Dues": page_customers, "Inventory": page_inventory, "Follow-ups": page_followups,
 "Insights": page_insights, "Settings": page_settings}[ss.page]()

# Any UI string not yet translated for this language: translate them all in ONE Sarvam call, then redraw once.
# Each string is tried once per session, so an API outage can't add a slow call + redraw to every click.
_tried = ss.setdefault("_i18n_tried", set())
_todo = [s for s in dict.fromkeys(_missing) if (LANG, s) not in _tried]
if _todo:
    _tried.update((LANG, s) for s in _todo)
    with st.spinner(f"{core.LANGUAGES[LANG]} …"):
        core.translate_many(_todo, LANG, conn)
    st.rerun()
