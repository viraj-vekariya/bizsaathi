"""BizSaathi — one configurable, multilingual AI operations assistant for local businesses.

Run:  .venv/bin/streamlit run app.py
"""
import hashlib
import html
from datetime import datetime

import pandas as pd
import streamlit as st

import core

st.set_page_config(page_title="BizSaathi", page_icon="📒", layout="wide")
core.init_db()


@st.cache_resource
def get_conn():
    return core.connect()


conn = get_conn()

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1250px;}
.kpi {border: 1px solid rgba(128,128,128,.25); border-radius: 10px; padding: 14px 16px;}
.kpi .l {font-size: .78rem; opacity: .7; text-transform: uppercase; letter-spacing: .04em;}
.kpi .v {font-size: 1.6rem; font-weight: 700; margin-top: 2px;}
.kpi .s {font-size: .8rem; opacity: .65;}
.pill {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem; margin: 0 4px 4px 0;
       border: 1px solid rgba(128,128,128,.3);}
.pill.on {background: rgba(34,160,90,.12); border-color: rgba(34,160,90,.5);}
.pill.off {opacity: .5; text-decoration: line-through;}
.act {padding: 6px 10px; border-left: 3px solid #22a05a; margin: 4px 0; background: rgba(34,160,90,.06); border-radius: 4px;}
.skip {padding: 6px 10px; border-left: 3px solid #999; margin: 4px 0; background: rgba(128,128,128,.08); border-radius: 4px;}
.big-total {font-size: 1.15rem;}
.step {display:inline-block; padding: 6px 14px; margin: 0 6px 10px 0; border-radius: 8px; font-size: .9rem;
       border: 1px solid rgba(128,128,128,.3); opacity: .55;}
.step.cur {opacity: 1; border-color: #1f6f4a; background: rgba(31,111,74,.08); font-weight: 600;}
.step.done {opacity: .85;}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("cmd", "")
ss.setdefault("plan", None)
ss.setdefault("last_result", None)
ss.setdefault("audio_hash", None)


def inr(x) -> str:
    return f"₹{x:,.2f}" if x is not None else "—"


def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div>'
                 f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ sidebar
modules = core.get_modules(conn)
with st.sidebar:
    biz = core.get_setting(conn, "business_name", "My Shop")
    st.markdown(f"## BizSaathi\n**{biz}**")
    st.caption("Your shop's AI assistant — type or speak in English, Hindi, Hinglish or Bengali.")

    pages = ["Assistant", "Dashboard"]
    if modules["Orders"]:
        pages.append("Orders")
    if modules["Invoices"]:
        pages.append("Invoices")
    if modules["Customer Management"] or modules["Payments"]:
        pages.append("Customers & Dues")
    if modules["Inventory"]:
        pages.append("Inventory")
    if modules["Follow-ups"]:
        pages.append("Follow-ups")
    if modules["Business Insights"]:
        pages.append("Insights")
    pages.append("Settings")
    page = st.radio("Go to", pages, label_visibility="collapsed")

    st.divider()
    st.markdown("**Capabilities**")
    st.caption("Pick what your business needs. Disabled modules never run.")
    for m in core.MODULES:
        new = st.toggle(m, value=modules[m], key=f"tog_{m}")
        if new != modules[m]:
            core.set_module(conn, m, new)
            modules[m] = new
            if ss.plan:  # re-check a pending preview against the new configuration
                core.recompute(ss.plan, modules, conn)
            st.rerun()
    st.divider()
    st.caption(("Sarvam AI connected" if core.ai_available() else "SARVAM_API_KEY missing")
               + f" · model `{core.MODEL}`")


def module_pills():
    return "".join(f'<span class="pill {"on" if modules[m] else "off"}">{m}</span>' for m in core.MODULES)


def kpi_row():
    s = core.dashboard_stats(conn)
    c = st.columns(4)
    kpi(c[0], "Today's sales", inr(s["sales_today"]), f'{s["orders_today"]} order(s)')
    kpi(c[1], "Collected today", inr(s["collected_today"]) if modules["Payments"] else "off", "payments received")
    kpi(c[2], "Outstanding dues", inr(s["outstanding"]) if modules["Payments"] else "off", "across all customers")
    kpi(c[3], "Low-stock items", s["low_stock"] if modules["Inventory"] else "off", "at or below reorder level")


# ------------------------------------------------------------------ invoice rendering
def invoice_html(order_id: int) -> str | None:
    d = core.invoice_data(conn, order_id)
    if not d:
        return None
    o = d["order"]
    paid = sum(p["amount"] for p in d["payments"])
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{html.escape(it['name'])}</td><td style='text-align:right'>{it['quantity']} {it['unit']}</td>"
        f"<td style='text-align:right'>₹{it['unit_price']:,.2f}</td><td style='text-align:right'>₹{it['line_total']:,.2f}</td></tr>"
        for i, it in enumerate(d["items"]))
    pays = "".join(f"<tr><td colspan=4 style='text-align:right'>Paid ({p['method'].upper()}, {p['created_at'][:16]})</td>"
                   f"<td style='text-align:right'>− ₹{p['amount']:,.2f}</td></tr>" for p in d["payments"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{o['invoice_no'] or 'Order'}</title>
<style>body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#111;background:#fff;margin:0;padding:24px}}
.inv{{max-width:640px;margin:auto;border:1px solid #ddd;border-radius:10px;padding:24px}}
h2{{margin:0}} table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}}
th,td{{padding:7px 6px;border-bottom:1px solid #eee}} th{{text-align:left;background:#fafafa}}
.muted{{color:#666;font-size:13px}} .tot td{{font-weight:700}} .due td{{font-weight:700;color:#b42318}}
@media print{{.noprint{{display:none}} body{{padding:0}} .inv{{border:none}}}}</style></head><body><div class="inv">
<div style="display:flex;justify-content:space-between;align-items:flex-start">
<div><h2>{html.escape(core.get_setting(conn, 'business_name', 'My Shop'))}</h2><div class="muted">Bill / Invoice</div></div>
<div style="text-align:right"><b>{o['invoice_no'] or f"Order #{o['id']}"}</b><div class="muted">{(o['invoice_date'] or o['created_at'])[:16]}</div></div></div>
<p><span class="muted">Billed to</span><br><b>{html.escape(o['customer'])}</b>{('<br>' + html.escape(o['phone'])) if o['phone'] else ''}</p>
<table><tr><th>#</th><th>Item</th><th style="text-align:right">Qty</th><th style="text-align:right">Rate</th><th style="text-align:right">Amount</th></tr>
{rows}<tr class="tot"><td colspan=4 style="text-align:right">Total</td><td style="text-align:right">₹{o['total']:,.2f}</td></tr>
{pays}<tr class="due"><td colspan=4 style="text-align:right">Balance due</td><td style="text-align:right">₹{o['total'] - paid:,.2f}</td></tr></table>
<p class="muted" style="margin-top:18px">Simple bill generated by BizSaathi. Not a GST tax invoice.</p>
<button class="noprint" onclick="window.print()" style="padding:8px 14px;border-radius:8px;border:1px solid #ccc;background:#fff;cursor:pointer">🖨️ Print</button>
</div></body></html>"""


def show_invoice(order_id: int, key: str):
    h = invoice_html(order_id)
    if not h:
        st.warning("Order not found.")
        return
    st.components.v1.html(h, height=560, scrolling=True)
    st.download_button("Download printable bill (.html)", h, file_name=f"bill-order-{order_id}.html",
                       mime="text/html", key=key)


# ------------------------------------------------------------------ assistant
def samples() -> list[tuple[str, str]]:
    """Example commands built from whatever catalog this shop has, so they work for any business type."""
    if core.get_setting(conn, "business_type") == core.DEFAULT_TEMPLATE:
        return [("Sale with advance", "Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance."),
                ("Payment against dues", "Amit paid ₹50 towards his dues by UPI."),
                ("Not enough stock", "Amit wants 20 bags of basmati rice."),
                ("Hinglish", "Priya ne 2 kilo cheeni aur 3 Maggi liya, 50 rupay UPI se diye")]
    prods = conn.execute("SELECT name, unit, price, stock FROM products ORDER BY id").fetchall()
    if not prods:
        return []
    p0 = prods[0]
    p1 = prods[1] if len(prods) > 1 else p0
    low = min(prods, key=lambda p: p["stock"])
    q = 3
    return [("Sale with advance", f"Rahul bought {q} {p0['name']} and 1 {p1['name']}. "
                                  f"He paid ₹{int(p0['price'] * q // 2)} in advance."),
            ("Payment against dues", "Amit paid ₹50 towards his dues by UPI."),
            ("Not enough stock", f"Amit wants {low['stock'] + 20} {low['name']}."),
            ("Hinglish", f"Priya ne 2 {p1['name']} liye, poora paisa cash mein diya")]


def run_parse(text: str):
    ss.last_result = None
    text = (text or "").strip()
    if not text:
        ss.parse_error = "Type or speak an instruction first."
        return
    try:
        with st.spinner("Sarvam-105B is reading your instruction…"):
            parsed = core.parse_command(text, conn)
    except Exception as e:  # API down, bad key, rate limit, bad JSON
        ss.plan = None
        ss.parse_error = f"AI couldn't read that ({type(e).__name__}: {str(e)[:160]}). Use manual entry below."
        return
    ss.parse_error = None
    plan = core.build_plan(parsed, modules, conn)
    plan["source_text"] = text
    plan["source"] = "ai"
    ss.plan = plan


def manual_plan(intent="sale"):
    plan = core.build_plan({"intent": intent, "customer_name": None, "items": [], "payment_amount": None,
                            "payment_method": "cash"}, modules, conn)
    plan["errors"] = []
    plan["source_text"] = "(manual entry)"
    plan["source"] = "manual"
    ss.plan = plan
    ss.parse_error = None
    ss.last_result = None


def render_preview():
    plan = ss.plan
    products = {p["name"]: p for p in conn.execute("SELECT * FROM products ORDER BY name")}
    st.markdown("### Review before saving")
    src = "Extracted by Sarvam-105B" if plan.get("source") == "ai" else "Manual entry"
    lang = f" · language: **{plan['language']}**" if plan.get("language") else ""
    st.caption(f"{src}{lang} · “{plan.get('source_text', '')}”")

    c1, c2, c3, c4 = st.columns([1.1, 1.6, 1, 1])
    intents = ["sale", "payment", "restock"]
    intent = c1.selectbox("Type", intents, index=intents.index(plan["intent"]) if plan["intent"] in intents else 0,
                          key=f"in_{plan['request_id']}")
    cust = c2.text_input("Customer", value=plan["customer_name"] or "", key=f"cu_{plan['request_id']}",
                         disabled=intent == "restock")
    pay = c3.number_input("Paid now (₹)", min_value=0.0, step=10.0, value=float(plan["payment_amount"] or 0),
                          key=f"pa_{plan['request_id']}", disabled=intent == "restock")
    methods = ["cash", "upi", "card", "other"]
    method = c4.selectbox("Method", methods, index=methods.index(plan["payment_method"]) if plan["payment_method"] in methods else 0,
                          key=f"me_{plan['request_id']}", disabled=intent == "restock")

    lines = plan["lines"]
    if intent != "payment":
        df = pd.DataFrame([{"Product": l["product"], "You said": l["spoken"], "Qty": l["quantity"] if l["ok"] or
                            isinstance(l["quantity"], int) else None, "Rate (₹)": l["unit_price"]} for l in lines],
                          columns=["Product", "You said", "Qty", "Rate (₹)"])
        edited = st.data_editor(
            df, num_rows="dynamic", width="stretch", key=f"ed_{plan['request_id']}",
            column_config={
                "Product": st.column_config.SelectboxColumn("Product", options=list(products), required=True),
                "You said": st.column_config.TextColumn("You said", disabled=True),
                "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, format="%d"),
                "Rate (₹)": st.column_config.NumberColumn("Rate (₹)", min_value=0.0, step=1.0, format="%.2f",
                                                         help="From your catalog. Edit only if you agreed a different price."),
            })
        new_lines = []
        for _, r in edited.iterrows():
            name = r["Product"] if isinstance(r["Product"], str) else None
            p = products.get(name)
            q = r["Qty"]
            q = int(q) if pd.notna(q) and float(q) == int(q) else (None if pd.isna(q) else q)
            rate = float(r["Rate (₹)"]) if pd.notna(r["Rate (₹)"]) else (float(p["price"]) if p else 0.0)
            prev = next((l for l in lines if l["product"] == name), None)
            if p and prev is None:  # newly picked product -> catalog price
                rate = float(p["price"]) if pd.isna(r["Rate (₹)"]) else rate
            new_lines.append({"spoken": r["You said"] if isinstance(r["You said"], str) else (name or ""),
                              "product_id": p["id"] if p else None, "product": name, "unit": p["unit"] if p else "",
                              "quantity": q, "unit_price": rate, "line_total": 0.0, "stock": None, "ok": True})
        plan["lines"] = new_lines
    else:
        plan["lines"] = []

    plan.update(intent=intent, customer_name=cust.strip() or None, payment_amount=float(pay), payment_method=method)
    core.recompute(plan, modules, conn)

    left, right = st.columns([1.3, 1])
    with left:
        st.markdown("**What will happen when you confirm**")
        for a in plan["actions"]:
            st.markdown(f'<div class="act">{html.escape(a)}</div>', unsafe_allow_html=True)
        for s in plan["skipped"]:
            st.markdown(f'<div class="skip">Skipped: {html.escape(s)}</div>', unsafe_allow_html=True)
    with right:
        if intent == "sale":
            st.markdown(f'<div class="big-total">Bill: <b>{inr(plan["subtotal"])}</b><br>'
                        f'Paid now: <b>{inr(plan["payment_amount"] if modules["Payments"] else 0)}</b><br>'
                        f'Outstanding on this bill: <b>{inr(plan["balance"])}</b></div>', unsafe_allow_html=True)
            if plan["prior_dues"] > 0:
                st.caption(f"{plan['customer_name']} already owes {inr(plan['prior_dues'])} from earlier bills.")
        elif intent == "payment":
            st.markdown(f'<div class="big-total">Current dues: <b>{inr(plan["prior_dues"])}</b><br>'
                        f'Paying: <b>{inr(plan["payment_amount"])}</b><br>'
                        f'Remaining: <b>{inr(plan["balance"])}</b></div>', unsafe_allow_html=True)
    for w in plan["warnings"]:
        st.warning(w, icon="⚠️")
    for e in plan["errors"]:
        st.error(e, icon="⛔")

    b1, b2, _ = st.columns([1.2, 1, 3])
    if b1.button("Confirm & save", type="primary", disabled=bool(plan["errors"]), width="stretch"):
        try:
            res = core.commit_plan(plan, modules, conn)
            ss.last_result = {"plan": plan, "res": res}
            ss.plan = None
            ss.clear_cmd = True
            st.rerun()
        except core.DuplicateSubmission as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Nothing was saved — {e}")
    if b2.button("Discard", width="stretch"):
        ss.plan = None
        st.rerun()


def render_result():
    r = ss.last_result
    plan, res = r["plan"], r["res"]
    msg = {"sale": f"Saved order #{res['order_id']} for {plan['customer_name']}",
           "payment": f"Recorded {inr(plan['payment_amount'])} from {plan['customer_name']}",
           "restock": "Stock updated"}[plan["intent"]]
    st.success(f"{msg} — all changes written in one transaction.", icon="✅")
    for a in plan["actions"]:
        st.markdown(f'<div class="act">{html.escape(a)}</div>', unsafe_allow_html=True)
    with st.expander("Safety check: submit the exact same command again"):
        st.caption("Each preview carries a one-time ID. Re-submitting it is refused by the database, "
                   "so a double tap or a flaky network can never bill a customer twice.")
        if st.button("Re-submit same command"):
            try:
                core.commit_plan(plan, modules, conn)
                st.error("Saved twice — this should not happen.")
            except core.DuplicateSubmission as e:
                st.success(f"Blocked: {e}")
    if plan["intent"] == "sale" and res.get("invoice_no"):
        with st.expander(f"Bill {res['invoice_no']}", expanded=True):
            show_invoice(res["order_id"], key=f"dl_last_{res['order_id']}")


def use_sample(text: str):
    ss.cmd = text
    run_parse(text)


def page_assistant():
    st.markdown(f"### What happened in the shop today?")
    step = 3 if (ss.last_result and not ss.plan) else 2 if ss.plan else 1
    st.markdown("".join(
        f'<span class="step {"cur" if i == step else "done" if i < step else ""}">{i}. {t}</span>'
        for i, t in enumerate(["Tell BizSaathi what happened", "Review what will change", "Saved to your books"], 1)),
        unsafe_allow_html=True)
    kpi_row()
    st.write("")
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        st.info("Your catalog is empty. Add your products on the Inventory page, or pick a business type in Settings.")

    if hasattr(st, "audio_input"):
        audio = st.audio_input("Speak your instruction (Sarvam Saaras speech-to-text)")
        if audio is not None:
            data = audio.getvalue()
            h = hashlib.md5(data).hexdigest()
            if h != ss.audio_hash:
                ss.audio_hash = h
                try:
                    with st.spinner("Transcribing with Sarvam…"):
                        names = [r["name"] for r in conn.execute("SELECT name FROM products")] + \
                                [r["name"] for r in conn.execute("SELECT name FROM customers")]
                        text = core.transcribe(data, "command.wav", keyterms=names)
                    if text:
                        ss.cmd = text
                        run_parse(text)
                    else:
                        st.warning("Didn't catch that — please try again or type it.")
                except Exception as e:
                    st.warning(f"Voice input failed ({str(e)[:120]}). Type the instruction instead.")

    if ss.pop("clear_cmd", False):
        ss.cmd = ""
    st.text_area("Or type it", key="cmd", height=80,
                 placeholder="e.g. Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance.")
    c = st.columns([1, 1, 4])
    c[0].button("Understand", type="primary", width="stretch", on_click=lambda: run_parse(ss.cmd))
    c[1].button("Manual entry", width="stretch", on_click=manual_plan)

    st.caption("Try an example:")
    ex = samples()
    cols = st.columns(max(len(ex), 1))
    for col, (label, text) in zip(cols, ex):
        col.button(label, width="stretch", on_click=use_sample, args=(text,), key=f"ex_{label}")

    if ss.get("parse_error"):
        st.error(ss.parse_error)
    if ss.plan:
        st.divider()
        render_preview()
    elif ss.last_result:
        st.divider()
        render_result()


# ------------------------------------------------------------------ other pages
def page_dashboard():
    st.markdown("### Dashboard")
    kpi_row()
    st.write("")
    a, b = st.columns([1.6, 1])
    with a:
        st.markdown("**Recent orders**")
        rows = core.orders_table(conn)[:8]
        if rows:
            st.dataframe(pd.DataFrame([{"#": r["id"], "When": r["created_at"][:16], "Customer": r["customer"],
                                        "Items": r["items"], "Total": r["total"], "Due": r["due"]} for r in rows]),
                         hide_index=True, width="stretch",
                         column_config={"Total": st.column_config.NumberColumn(format="₹%.2f"),
                                        "Due": st.column_config.NumberColumn(format="₹%.2f")})
        else:
            st.info("No orders yet.")
    with b:
        if modules["Inventory"]:
            st.markdown("**Low stock**")
            low = conn.execute("SELECT name, stock, low_stock_at, unit FROM products WHERE stock <= low_stock_at "
                               "ORDER BY stock").fetchall()
            for p in low:
                st.markdown(f"🔴 **{p['name']}** — {p['stock']} {p['unit']}(s) left (reorder at {p['low_stock_at']})")
            if not low:
                st.success("All items above reorder level.")
        if modules["Payments"]:
            st.markdown("**Top dues**")
            for c in [c for c in core.customers_with_dues(conn) if c["due"] > 0.001][:5]:
                st.markdown(f"• {c['name']} — **{inr(c['due'])}**")


def page_orders():
    st.markdown("### Orders")
    q = st.text_input("Search by customer, product, order # or invoice #")
    rows = core.orders_table(conn, q)
    if not rows:
        st.info("No matching orders.")
        return
    st.dataframe(pd.DataFrame([{"#": r["id"], "When": r["created_at"][:16], "Customer": r["customer"],
                                "Items": r["items"], "Total": r["total"], "Paid": r["paid"], "Due": r["due"],
                                "Invoice": r["invoice_no"] or "—"} for r in rows]),
                 hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="₹%.2f") for k in ("Total", "Paid", "Due")})


def page_invoices():
    st.markdown("### Invoices")
    rows = [r for r in core.orders_table(conn) if r["invoice_no"]]
    if not rows:
        st.info("No invoices yet.")
        return
    labels = {f"{r['invoice_no']} · {r['customer']} · {inr(r['total'])}": r["id"] for r in rows}
    choice = st.selectbox("Invoice", list(labels))
    show_invoice(labels[choice], key=f"dl_inv_{labels[choice]}")


def page_customers():
    st.markdown("### Customers & dues")
    rows = core.customers_with_dues(conn)
    st.dataframe(pd.DataFrame([{"Customer": r["name"], "Phone": r["phone"] or "", "Billed": r["billed"],
                                "Paid": r["paid"], "Due": r["due"], "Last order": (r["last_order"] or "")[:10]}
                               for r in rows]), hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="₹%.2f") for k in ("Billed", "Paid", "Due")})
    if modules["Customer Management"]:
        with st.expander("Add / update customer"):
            n = st.text_input("Name")
            ph = st.text_input("Phone")
            if st.button("Save customer") and n.strip():
                conn.execute("INSERT INTO customers(name, phone, created_at) VALUES (?,?,?) "
                             "ON CONFLICT(name) DO UPDATE SET phone=excluded.phone", (n.strip(), ph.strip(), core.now()))
                st.success(f"Saved {n.strip()}.")
                st.rerun()


def page_inventory():
    st.markdown("### Inventory & catalog")
    st.caption("Edit prices, stock and the names customers use for each item, or add new rows. "
               "BizSaathi's AI reads this catalog, so any kind of shop works.")
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    df = pd.DataFrame([{"Status": "Low" if r["stock"] <= r["low_stock_at"] else "OK", "name": r["name"],
                        "unit": r["unit"], "price": r["price"], "stock": r["stock"], "low_stock_at": r["low_stock_at"],
                        "aliases": r["aliases"]} for r in rows],
                      columns=["Status", "name", "unit", "price", "stock", "low_stock_at", "aliases"])
    edited = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="catalog_editor",
                            column_config={
                                "Status": st.column_config.TextColumn(disabled=True),
                                "name": st.column_config.TextColumn("Product", required=True),
                                "unit": st.column_config.TextColumn("Unit"),
                                "price": st.column_config.NumberColumn("Price (₹)", min_value=0.0, format="%.2f"),
                                "stock": st.column_config.NumberColumn("Stock", min_value=0, step=1, format="%d"),
                                "low_stock_at": st.column_config.NumberColumn("Reorder at", min_value=0, step=1, format="%d"),
                                "aliases": st.column_config.TextColumn("Also called (comma-separated)", width="large"),
                            })
    if st.button("Save catalog", type="primary"):
        try:
            n = core.save_catalog(conn, edited.to_dict("records"))
            st.success(f"Saved {n} product(s).")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    st.markdown("**Recent stock movements**")
    moves = conn.execute("""SELECT m.created_at, p.name, m.change, m.reason, m.ref FROM stock_moves m
                            JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 12""").fetchall()
    if moves:
        st.dataframe(pd.DataFrame([{"When": m["created_at"][:16], "Product": m["name"], "Change": m["change"],
                                    "Reason": m["reason"], "Ref": m["ref"] or ""} for m in moves]),
                     hide_index=True, width="stretch")


def page_followups():
    st.markdown("### Follow-ups")
    st.caption("Customers with unpaid balances, oldest first, with a ready-to-send reminder.")
    due = [c for c in core.customers_with_dues(conn) if c["due"] > 0.001]
    if not due:
        st.success("No pending dues.")
        return
    biz = core.get_setting(conn, "business_name", "our shop")
    for c in sorted(due, key=lambda c: c["last_order"] or ""):
        days = (datetime.now() - datetime.strptime(c["last_order"][:19], "%Y-%m-%d %H:%M:%S")).days if c["last_order"] else 0
        with st.container(border=True):
            st.markdown(f"**{c['name']}** · due **{inr(c['due'])}** · last purchase {days} day(s) ago")
            st.code(f"Namaste {c['name'].split()[0]} ji, {biz} se yaad dilana tha — aapka ₹{c['due']:,.0f} baaki hai. "
                    f"Suvidha anusaar UPI ya cash se de dijiye. Dhanyavaad! 🙏", language=None)


def page_insights():
    st.markdown("### Business insights")
    st.caption("Computed directly from your saved orders — no AI guesses.")
    daily = pd.read_sql_query("SELECT date(created_at) AS day, SUM(total) AS sales FROM orders "
                              "GROUP BY day ORDER BY day", conn)
    top = pd.read_sql_query("""SELECT p.name AS product, SUM(oi.quantity) AS units, SUM(oi.line_total) AS revenue
                               FROM order_items oi JOIN products p ON p.id=oi.product_id
                               GROUP BY p.id ORDER BY revenue DESC LIMIT 8""", conn)
    a, b = st.columns(2)
    with a:
        st.markdown("**Sales by day (₹)**")
        if not daily.empty:
            st.bar_chart(daily.set_index("day"))
    with b:
        st.markdown("**Top products by revenue**")
        if not top.empty:
            st.dataframe(top, hide_index=True, width="stretch",
                         column_config={"revenue": st.column_config.NumberColumn("revenue", format="₹%.2f")})
    billed = conn.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    c = st.columns(3)
    kpi(c[0], "Total billed", inr(billed))
    kpi(c[1], "Collected", inr(paid), f"{(paid / billed * 100 if billed else 0):.0f}% collection rate")
    kpi(c[2], "Customers", conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])


def page_settings():
    st.markdown("### Settings")
    name = st.text_input("Business name", core.get_setting(conn, "business_name", ""))
    if st.button("Save name"):
        core.set_setting(conn, "business_name", name.strip() or "My Shop")
        st.rerun()
    st.divider()
    st.markdown("**Set up for a different kind of business**")
    st.caption("Loads a starter catalog for that business type. Everything else — AI parsing, rules, bills, "
               "dues — works the same. This replaces all current data.")
    types = list(core.BUSINESS_TEMPLATES)
    cur = core.get_setting(conn, "business_type", core.DEFAULT_TEMPLATE)
    t = st.selectbox("Business type", types, index=types.index(cur) if cur in types else 0)
    new_name = st.text_input("Shop name", core.BUSINESS_TEMPLATES[t][0], key=f"nm_{t}")
    ok = st.checkbox("I understand this wipes the current orders, customers and stock")
    if st.button("Set up shop", disabled=not ok):
        get_conn.clear()
        core.init_db(reset=True, template=t, business_name=new_name.strip() or None)
        for k in ("plan", "last_result", "parse_error"):
            ss[k] = None
        st.rerun()


{"Assistant": page_assistant, "Dashboard": page_dashboard, "Orders": page_orders, "Invoices": page_invoices,
 "Customers & Dues": page_customers, "Inventory": page_inventory, "Follow-ups": page_followups,
 "Insights": page_insights, "Settings": page_settings}[page]()
