"""Offline tests for BizSaathi business logic (no API calls). Run: .venv/bin/python test_core.py"""
import os, tempfile
import core

core.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")
core.init_db(reset=True)
conn = core.connect()
ALL = {m: True for m in core.MODULES}

def stock(name):
    return conn.execute("SELECT stock FROM products WHERE name=?", (name,)).fetchone()[0]

def sale(cust, items, pay=None, mods=ALL):
    return core.build_plan({"intent": "sale", "customer_name": cust, "payment_amount": pay, "payment_method": "cash",
                            "items": [{"product": p, "quantity": q, "stated_unit_price": None} for p, q in items]}, mods, conn)

# 1. Rahul demo: 10 bottles @40, 200 advance
s0 = stock("Water Bottle 1L")
p = sale("Rahul", [("bottles", 10)], 200)
assert not p["errors"] and p["subtotal"] == 400 and p["balance"] == 200, p
r = core.commit_plan(p, ALL, conn)
assert stock("Water Bottle 1L") == s0 - 10
assert r["invoice_no"] and len(r["payment_ids"]) == 1
rahul = core.find_customer("Rahul", conn)
assert core.customer_dues(conn, rahul["id"]) == 200
print("1 Rahul sale OK", r)

# 2. duplicate submission blocked, nothing changes
try:
    core.commit_plan(p, ALL, conn); raise SystemExit("duplicate NOT blocked")
except core.DuplicateSubmission:
    pass
assert stock("Water Bottle 1L") == s0 - 10 and core.customer_dues(conn, rahul["id"]) == 200
print("2 duplicate blocked OK")

# 3. insufficient stock rejected at plan time
p = sale("Amit", [("rice", 999)])
assert any("Insufficient stock" in e for e in p["errors"]), p["errors"]
print("3 insufficient stock OK")

# 4. stock changes between preview and confirm -> rollback, nothing half-written
p = sale("Amit", [("sugar", 2), ("rice", 3)])
assert not p["errors"]
conn.execute("UPDATE products SET stock = 1 WHERE name='Basmati Rice 5kg'")
n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]; sugar = stock("Sugar 1kg")
try:
    core.commit_plan(p, ALL, conn); raise SystemExit("should fail")
except ValueError:
    pass
assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == n_orders and stock("Sugar 1kg") == sugar
print("4 atomic rollback OK")

# 5. unknown product / invalid qty
p = sale("Amit", [("iphone", 1), ("sugar", 0), ("maggi", 2.5)])
assert len(p["errors"]) == 3, p["errors"]
print("5 validation OK")

# 6. Inventory disabled -> stock untouched; Payments disabled -> payment skipped; Invoices off -> no invoice
mods = dict(ALL, Inventory=False, Payments=False, Invoices=False)
sm = stock("Maggi Noodles")
p = sale("Priya", [("maggi", 5)], 70, mods)
assert not p["errors"] and p["skipped"] and p["balance"] == p["subtotal"]
r = core.commit_plan(p, mods, conn)
assert stock("Maggi Noodles") == sm and not r["payment_ids"] and not r["invoice_no"]
print("6 module toggles respected OK")

# 7. Orders disabled -> sale refused
p = sale("Priya", [("maggi", 1)], None, dict(ALL, Orders=False))
assert any("Orders module is disabled" in e for e in p["errors"])
print("7 orders-off refused OK")

# 8. payment against dues, FIFO, overpay rejected
p = core.build_plan({"intent": "payment", "customer_name": "rahul", "items": [], "payment_amount": 150,
                     "payment_method": "upi"}, ALL, conn)
assert not p["errors"], p["errors"]
core.commit_plan(p, ALL, conn)
assert core.customer_dues(conn, rahul["id"]) == 50
p = core.build_plan({"intent": "payment", "customer_name": "Rahul", "items": [], "payment_amount": 500,
                     "payment_method": "upi"}, ALL, conn)
assert p["errors"]
print("8 payments OK")

# 9. overpayment on a sale rejected
p = sale("Rahul", [("salt", 1)], 1000)
assert any("more than the bill" in e for e in p["errors"])
print("9 overpay OK")

# 10. restock
so = stock("Fortune Oil 1L")
p = core.build_plan({"intent": "restock", "customer_name": None, "payment_amount": None, "payment_method": None,
                     "items": [{"product": "tel", "quantity": 24, "stated_unit_price": None}]}, ALL, conn)
core.commit_plan(p, ALL, conn); assert stock("Fortune Oil 1L") == so + 24
print("10 restock OK")

# 11. Hindi / Bengali aliases match
for w, exp in [("बोतल", "Water Bottle 1L"), ("সাবান", "Lux Soap"), ("cheeni", "Sugar 1kg"), ("chawal", "Basmati Rice 5kg")]:
    assert core.match_product(w, conn)["name"] == exp, w
print("11 alias matching OK")
print("ALL TESTS PASSED")
