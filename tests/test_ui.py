"""UI tests for BizSaathi: drive every widget with Streamlit's AppTest.

Run from the project dir:  .venv/bin/python -m pytest tests/test_ui.py -q
Each test gets a fresh SQLite file. AI calls are faked (deterministic) except the tests marked `live`,
which make a handful of real Sarvam calls (skipped when SARVAM_API_KEY is missing).
"""
import json
import os
import sys

import pytest
import streamlit as st
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import core  # noqa: E402

APP = os.path.join(ROOT, "app.py")
TIMEOUT = 90

# ---------------------------------------------------------------- deterministic stand-ins for the AI
FAKE = {
    "Rahul ordered 10 bottles": {"intent": "sale", "customer_name": "Rahul", "payment_amount": 200,
                                 "payment_method": "cash", "language": "English",
                                 "items": [{"product": "bottles", "quantity": 10, "stated_unit_price": 40}]},
    "Amit paid ₹": {"intent": "payment", "customer_name": "Amit", "payment_amount": 50, "payment_method": "upi",
                      "language": "English", "items": []},
    "Amit wants 20 bags": {"intent": "sale", "customer_name": "Amit", "payment_amount": None, "payment_method": "cash",
                           "language": "English",
                           "items": [{"product": "basmati rice", "quantity": 20, "stated_unit_price": None}]},
    "प्रिया": {"intent": "sale", "customer_name": "Priya", "payment_amount": 50, "payment_method": "upi",
               "language": "Hindi", "items": [{"product": "cheeni", "quantity": 2, "stated_unit_price": None},
                                               {"product": "maggi", "quantity": 3, "stated_unit_price": None}]},
    "সুনীতা": {"intent": "sale", "customer_name": "Sunita", "payment_amount": 100, "payment_method": "cash",
               "language": "Bengali", "items": [{"product": "soap", "quantity": 4, "stated_unit_price": None},
                                                 {"product": "milk", "quantity": 2, "stated_unit_price": None}]},
}
CALLS = {"parse": 0, "speak": 0, "translate": 0}


def fake_parse(text, conn):
    CALLS["parse"] += 1
    for k, v in FAKE.items():
        if text.startswith(k):
            d = json.loads(json.dumps(v))
            if d["intent"] == "payment":
                d["payment_amount"] = float(text.split("₹")[1].split()[0])
            return core.normalise_parsed(d)
    if "rasgulla" in text.lower() or "Rasgulla" in text:  # bakery sample
        return core.normalise_parsed({"intent": "sale", "customer_name": "Rahul", "payment_amount": 10,
                                      "payment_method": "cash", "items": [{"product": "rasgulla", "quantity": 3}]})
    raise RuntimeError("fake parser: unknown text " + text)


def fake_speak(text, lang):
    CALLS["speak"] += 1
    return b"RIFF0000WAVEfake"


def fake_translate(texts, lang, conn):
    CALLS["translate"] += 1
    if lang == "en-IN":
        return list(texts)
    out = [f"[{lang}] {t}" for t in texts]
    for src, dst in zip(texts, out):  # cache like the real one, so T() picks it up on the redraw
        conn.execute("INSERT OR REPLACE INTO translations(lang, src, dst) VALUES (?,?,?)", (lang, src, dst))
    return out


LIVE = pytest.mark.skipif(not core.ai_available(), reason="SARVAM_API_KEY missing")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "ui.db"))
    st.cache_resource.clear()
    st.cache_data.clear()
    monkeypatch.setattr(core, "parse_command", fake_parse)
    monkeypatch.setattr(core, "speak", fake_speak)
    monkeypatch.setattr(core, "translate_many", fake_translate)
    core.init_db()
    conn = core.connect()
    yield conn
    conn.close()
    st.cache_resource.clear()


def new_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    ok(at)
    return at


def ok(at):
    assert not at.exception, [e.value for e in at.exception]


def run(at):
    """Rerun the app. Grid edits made with edit_grid() are re-sent on every run, as the browser does."""
    grids = getattr(at, "_grids", {})
    if grids:
        orig = at._tree.get_widget_states

        def with_grids():
            ws = orig()
            for wid, delta in grids.items():
                ws.widgets.append(WidgetState(id=wid, string_value=json.dumps(delta)))
            return ws

        at._tree.get_widget_states = with_grids
    at.run()
    ok(at)
    return at


def go(at, page):
    at.radio(key="page").set_value(page)
    return run(at)


def btn(at, label):
    """Find a button (incl. form submit buttons) by its label."""
    hits = [b for b in at.button if b.label == label]
    assert hits, f"no button {label!r}; have {[b.label for b in at.button]}"
    return hits[0]


def title(at) -> str:
    return [m.value for m in at.markdown if m.value.startswith('<p class="page-title">')][0]


def md_text(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def stock(conn, name):
    return conn.execute("SELECT stock FROM products WHERE name=?", (name,)).fetchone()[0]


def preview_rid(at) -> str:
    return at.session_state["plan"]["request_id"]


def edit_grid(at, key, delta):
    """AppTest has no data_editor API: send the editor's JSON delta as its widget state (kept for later runs)."""
    ids = [n.proto.id for n in at if hasattr(n, "proto") and isinstance(getattr(n.proto, "id", None), str)
           and n.proto.id.endswith("-" + key)]
    assert ids, f"data editor {key} not found"
    at._grids = getattr(at, "_grids", {})
    at._grids[ids[0]] = {"edited_rows": {}, "added_rows": [], "deleted_rows": [], **delta}
    return run(at)


# ================================================================= sidebar
def test_navigation_every_page(db):
    at = new_app()
    pages = at.radio(key="page").options
    assert len(pages) == 9
    for p in ["Assistant", "Dashboard", "Orders", "Invoices", "Customers & Dues", "Inventory", "Follow-ups",
              "Insights", "Settings"]:
        go(at, p)
        assert at.session_state["page"] == p


def test_toggles_persist_and_hide_pages(db):
    at = new_app()
    for m in core.MODULES:
        at.toggle(key=f"tog_{m}").set_value(False)
        run(at)
        assert core.get_modules(db)[m] is False
        assert at.toggle(key=f"tog_{m}").value is False
        run(at)  # plain rerun: no flip-flop
        assert at.toggle(key=f"tog_{m}").value is False and core.get_modules(db)[m] is False
    opts = at.radio(key="page").options
    for hidden in ["Orders", "Invoices", "Inventory", "Follow-ups", "Insights"]:
        assert hidden not in opts
    for m in core.MODULES:
        at.toggle(key=f"tog_{m}").set_value(True)
        run(at)
        assert core.get_modules(db)[m] is True
        run(at)
        assert at.toggle(key=f"tog_{m}").value is True
    assert len(at.radio(key="page").options) == 9


def test_hiding_current_page_falls_back(db):
    at = new_app()
    go(at, "Orders")
    at.toggle(key="tog_Orders").set_value(False)
    run(at)
    assert at.session_state["page"] == "Assistant"
    assert "Orders" not in at.radio(key="page").options


def test_language_switch(db):
    at = new_app()
    en_title = title(at)
    at.selectbox(key="lang").set_value("hi-IN")
    run(at)
    assert at.session_state["lang"] == "hi-IN"
    run(at)  # language must stick across reruns (label change must not reset the widget)
    assert at.session_state["lang"] == "hi-IN"
    hi_title = title(at)
    assert hi_title != en_title
    for p in ["Dashboard", "Settings", "Assistant"]:
        go(at, p)
        assert at.session_state["lang"] == "hi-IN" and at.session_state["page"] == p
    at.selectbox(key="lang").set_value("en-IN")
    run(at)
    assert at.session_state["lang"] == "en-IN"
    assert title(at) == en_title


# ================================================================= assistant
EXAMPLES = {"Sale with advance": "Create order for Rahul", "Payment against dues": "Record UPI payment ₹27.00 from Amit Das",
            "Not enough stock": "Insufficient stock", "Hindi": "Create order for Priya Sharma",
            "Bengali": "Create order for Sunita Devi"}


@pytest.mark.parametrize("label,expect", list(EXAMPLES.items()))
def test_example_buttons(db, label, expect):
    at = new_app()
    btn(at, label).click()
    run(at)
    assert at.session_state["plan"] is not None
    text = md_text(at) + "\n".join(e.value for e in at.error)
    assert expect in text, text


def test_understand_typed_and_empty(db):
    at = new_app()
    btn(at, "Understand").click()
    run(at)
    assert any("Type or speak" in e.value for e in at.error)
    assert at.session_state["plan"] is None
    at.text_area(key="cmd").input("Amit paid ₹50 towards his dues by UPI.")
    btn(at, "Understand").click()
    run(at)
    assert at.session_state["plan"]["intent"] == "payment"


def test_unparseable_text_friendly_error(db):
    at = new_app()
    at.text_area(key="cmd").input("zzz nonsense")
    btn(at, "Understand").click()
    run(at)
    assert any("couldn't read" in e.value for e in at.error)


def test_sale_edit_confirm_duplicate_record_another(db):
    at = new_app()
    btn(at, "Sale with advance").click()
    run(at)
    rid = preview_rid(at)
    assert "₹200" in md_text(at)  # outstanding 400-200
    at.number_input(key=f"pa_{rid}").set_value(100.0)
    run(at)
    assert at.session_state["plan"]["balance"] == 300
    assert "₹300" in md_text(at)
    at.selectbox(key=f"me_{rid}").set_value("upi")
    at.text_input(key=f"cu_{rid}").input("Rahul Kumar")
    run(at)
    assert at.session_state["plan"]["payment_method"] == "upi"
    assert at.session_state["plan"]["customer_name"] == "Rahul Kumar"
    orders, s0 = count(db, "orders"), stock(db, "Water Bottle 1L")
    confirm = at.button(key=f"ok_{rid}")
    assert not confirm.disabled
    confirm.click()
    run(at)
    assert at.session_state["plan"] is None and at.session_state["last_result"]
    assert count(db, "orders") == orders + 1
    assert stock(db, "Water Bottle 1L") == s0 - 10
    assert any("Order saved" in m.value for m in at.markdown)
    assert any(m.value.startswith("**Bill INV-") for m in at.markdown)
    pay = db.execute("SELECT amount, method FROM payments ORDER BY id DESC LIMIT 1").fetchone()
    assert (pay["amount"], pay["method"]) == (100, "upi")
    # duplicate submit is blocked
    btn(at, "Test: submit the same entry again").click()
    run(at)
    assert any("Blocked by the database" in s.value for s in at.success)
    assert count(db, "orders") == orders + 1
    # record another -> step 1, empty box
    btn(at, "Record another").click()
    run(at)
    assert at.session_state["last_result"] is None
    assert at.text_area(key="cmd").value == ""


def test_change_type_to_payment_and_restock(db):
    at = new_app()
    btn(at, "Sale with advance").click()
    run(at)
    rid = preview_rid(at)
    at.selectbox(key=f"in_{rid}").set_value("restock")
    run(at)
    assert at.text_input(key=f"cu_{rid}").disabled
    s0 = stock(db, "Water Bottle 1L")
    at.button(key=f"ok_{rid}").click()
    run(at)
    assert stock(db, "Water Bottle 1L") == s0 + 10


def test_not_enough_stock_disables_confirm(db):
    at = new_app()
    btn(at, "Not enough stock").click()
    run(at)
    rid = preview_rid(at)
    assert at.button(key=f"ok_{rid}").disabled
    btn(at, "Discard").click()
    run(at)
    assert at.session_state["plan"] is None
    assert at.text_area(key="cmd") is not None


def test_discard(db):
    at = new_app()
    btn(at, "Hindi").click()
    run(at)
    btn(at, "Discard").click()
    run(at)
    assert at.session_state["plan"] is None
    assert not [m for m in at.markdown if "Review before saving" in m.value]


def test_payment_reduces_dues(db):
    at = new_app()
    amit = core.find_customer("Amit", db)
    before = core.customer_dues(db, amit["id"])
    btn(at, "Payment against dues").click()
    run(at)
    amt = at.session_state["plan"]["payment_amount"]
    assert 0 < amt <= before
    assert not at.button(key=f"ok_{preview_rid(at)}").disabled
    at.button(key=f"ok_{preview_rid(at)}").click()
    run(at)
    assert core.customer_dues(db, amit["id"]) == before - amt


def test_inventory_off_skips_stock(db):
    at = new_app()
    at.toggle(key="tog_Inventory").set_value(False)
    run(at)
    btn(at, "Sale with advance").click()
    run(at)
    assert "Skipped" in md_text(at) and "Stock not changed" in md_text(at)
    s0 = stock(db, "Water Bottle 1L")
    at.button(key=f"ok_{preview_rid(at)}").click()
    run(at)
    assert stock(db, "Water Bottle 1L") == s0
    assert at.session_state["last_result"]


def test_toggle_during_preview_recomputes(db):
    at = new_app()
    btn(at, "Not enough stock").click()
    run(at)
    rid = preview_rid(at)
    assert at.button(key=f"ok_{rid}").disabled
    at.toggle(key="tog_Inventory").set_value(False)
    run(at)
    assert not at.button(key=f"ok_{rid}").disabled  # no stock check with Inventory off
    assert at.toggle(key="tog_Inventory").value is False


def test_manual_entry_add_row(db):
    at = new_app()
    btn(at, "Manual entry").click()
    run(at)
    plan = at.session_state["plan"]
    assert plan["source"] == "manual" and plan["lines"] == []
    rid = plan["request_id"]
    assert at.button(key=f"ok_{rid}").disabled
    edit_grid(at, f"ed_{rid}", {"added_rows": [{"Product": "Lux Soap", "Qty": 3}]})
    plan = at.session_state["plan"]
    assert len(plan["lines"]) == 1 and plan["subtotal"] == 3 * 38, plan
    at.text_input(key=f"cu_{rid}").input("Priya")
    at.number_input(key=f"pa_{rid}").set_value(14.0)
    run(at)
    assert at.session_state["plan"]["balance"] == 100
    assert not at.button(key=f"ok_{rid}").disabled
    n = count(db, "orders")
    at.button(key=f"ok_{rid}").click()
    run(at)
    assert count(db, "orders") == n + 1


def test_edit_quantity_in_grid(db):
    at = new_app()
    btn(at, "Not enough stock").click()
    run(at)
    rid = preview_rid(at)
    edit_grid(at, f"ed_{rid}", {"edited_rows": {"0": {"Qty": 2}}})
    assert not at.button(key=f"ok_{rid}").disabled
    assert at.session_state["plan"]["subtotal"] == 900


# ================================================================= other pages
def test_orders_search_and_bill(db):
    at = new_app()
    go(at, "Orders")
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 3
    at.text_input[0].input("Priya")
    run(at)
    assert len(at.dataframe[0].value) == 1
    at.text_input[0].input("nobody-xyz")
    run(at)
    assert any("No matching" in i.value for i in at.info)
    at.text_input[0].input("")
    run(at)
    sb = at.main.selectbox[-1]
    sb.set_value(sb.options[1])
    run(at)
    assert any(getattr(n, "type", "") == "download_button" or "download_button" in str(type(n)).lower()
               or getattr(getattr(n, "proto", None), "label", "") == "Download bill (.html)" for n in at)


def test_invoices_page(db):
    at = new_app()
    go(at, "Invoices")
    sb = at.main.selectbox[-1]
    assert len(sb.options) == 3
    for o in sb.options:
        sb.set_value(o)
        run(at)


def test_customers_add(db):
    at = new_app()
    go(at, "Customers & Dues")
    at.button(key="save_cust").click()
    run(at)
    assert any("Enter a name" in e.value for e in at.error)
    at.text_input(key="new_cust_name").input("Kavita Rao")
    at.text_input(key="new_cust_phone").input("99999 00000")
    at.button(key="save_cust").click()
    run(at)
    assert db.execute("SELECT phone FROM customers WHERE name='Kavita Rao'").fetchone()[0] == "99999 00000"
    assert at.text_input(key="new_cust_name").value == "" and at.text_input(key="new_cust_phone").value == ""
    assert any("Kavita Rao" in s.value for s in at.success)


def test_inventory_catalog_save(db):
    at = new_app()
    go(at, "Inventory")
    n_products = count(db, "products")
    names = [r[0] for r in db.execute("SELECT name FROM products ORDER BY name")]
    i = names.index("Lux Soap")
    edit_grid(at, f"catalog_editor_{at.session_state['catalog_ver']}",
              {"edited_rows": {str(i): {"price": 41.5}},
               "added_rows": [{"name": "Test Candle", "unit": "piece", "price": 12, "stock": 5, "low_stock_at": 1}]})
    at.button(key="save_catalog").click()
    run(at)
    assert any("Saved" in s.value for s in at.success)
    assert db.execute("SELECT price FROM products WHERE name='Lux Soap'").fetchone()[0] == 41.5
    assert count(db, "products") == n_products + 1
    run(at)
    run(at)  # the browser keeps re-sending the old grid edits; they must not touch the fresh editor
    at.button(key="save_catalog").click()
    run(at)
    assert count(db, "products") == n_products + 1
    assert db.execute("SELECT COUNT(*) FROM stock_moves WHERE reason='manual adjustment'").fetchone()[0] == 1
    # invalid value -> friendly error, nothing written
    edit_grid(at, f"catalog_editor_{at.session_state['catalog_ver']}", {"edited_rows": {str(i): {"price": None}}})
    at.button(key="save_catalog").click()
    run(at)
    assert any("must be numbers" in e.value for e in at.error)
    assert db.execute("SELECT price FROM products WHERE name='Lux Soap'").fetchone()[0] == 41.5


def test_followups_listen(db):
    at = new_app()
    go(at, "Follow-ups")
    listen = [b for b in at.button if b.label == "Listen"]
    assert listen
    listen[0].click()
    run(at)
    assert CALLS["speak"] >= 1


def test_insights(db):
    at = new_app()
    go(at, "Insights")
    assert at.dataframe


def test_settings_name_and_setup(db):
    at = new_app()
    go(at, "Settings")
    at.text_input(key="biz_name").input("Viraj Stores")
    at.button(key="save_name").click()
    run(at)
    assert core.get_setting(db, "business_name") == "Viraj Stores"
    assert any("Viraj Stores" in m.value for m in at.sidebar.markdown)
    assert at.button(key="setup_btn").disabled
    at.selectbox(key="setup_type").set_value("Bakery & sweets")
    run(at)
    at.checkbox(key="ok_setup").check()
    run(at)
    assert not at.button(key="setup_btn").disabled
    at.toggle(key="tog_Orders").set_value(False)
    run(at)
    at.button(key="setup_btn").click()
    run(at)
    conn = core.connect()
    names = [r[0] for r in conn.execute("SELECT name FROM products")]
    assert "Rasgulla (1 pc)" in names and "Water Bottle 1L" not in names
    assert all(core.get_modules(conn).values())
    assert all(at.toggle(key=f"tog_{m}").value for m in core.MODULES)
    assert at.text_input(key="biz_name").value == "Kolkata Sweet House"
    assert at.button(key="setup_btn").disabled  # confirmation must be re-ticked
    run(at)
    go(at, "Assistant")
    assert "Rasgulla" in " ".join(b.label for b in at.button) or at.button
    conn.close()


def test_reset_demo_data(db):
    at = new_app()
    btn(at, "Sale with advance").click()
    run(at)
    at.button(key=f"ok_{preview_rid(at)}").click()
    run(at)
    assert count(db, "orders") == 4
    go(at, "Settings")
    at.button(key="reset_btn").click()
    run(at)
    conn = core.connect()
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    conn.close()
    go(at, "Assistant")
    assert at.session_state["last_result"] is None


# ================================================================= live (few real Sarvam calls)
@LIVE
def test_live_understand_and_listen(db, monkeypatch):
    path = core.DB_PATH
    monkeypatch.undo()  # real parse / speak / translate
    monkeypatch.setattr(core, "DB_PATH", path)
    st.cache_resource.clear()
    at = new_app()
    at.text_area(key="cmd").input("Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance.")
    btn(at, "Understand").click()
    run(at)
    plan = at.session_state["plan"]
    assert plan and plan["intent"] == "sale" and plan["subtotal"] == 400 and plan["balance"] == 200, plan
    go(at, "Follow-ups")
    [b for b in at.button if b.label == "Listen"][0].click()
    run(at)  # may fail upstream; must not crash
