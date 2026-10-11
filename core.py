"""BizSaathi core: SQLite storage, Sarvam AI command parsing, and transactional business logic.

Rule: the AI only *extracts* (who, what, how many, how much was paid). Every price, total,
balance and stock change is computed here from the database, and nothing is written until the
owner confirms the preview.
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bizsaathi.db")
MODEL = "sarvam-105b"

MODULES = ["Orders", "Invoices", "Payments", "Inventory", "Customer Management", "Follow-ups", "Business Insights"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, phone TEXT,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0), stock INTEGER NOT NULL CHECK (stock >= 0),
    low_stock_at INTEGER NOT NULL DEFAULT 10, aliases TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
    created_at TEXT NOT NULL, total REAL NOT NULL, request_id TEXT NOT NULL UNIQUE,
    source_text TEXT);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL, line_total REAL NOT NULL);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    invoice_no TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id), amount REAL NOT NULL CHECK (amount > 0),
    method TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT);
CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
    change INTEGER NOT NULL, reason TEXT NOT NULL, ref TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS translations (lang TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY (lang, src));
CREATE TABLE IF NOT EXISTS processed_requests (request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
"""

# A business type is just data: a starter catalog. The parser, rules and UI read whatever catalog is
# in the database, so supporting a new kind of shop needs no code changes.
# name, unit, price (2026 MRP, ₹), stock, low-stock threshold, aliases
# (English / Hinglish / Hindi / Bengali, plus Tamil / Telugu where shoppers use them)
BUSINESS_TEMPLATES = {
    "Kirana / General store": ("Maa Durga General Store", [
        ("Water Bottle 1L", "bottle", 40, 60, 15,
         "bottle,bottles,water,water bottle,paani,pani,paani ki bottle,jol,बोतल,पानी,বোতল,জল,পানি,தண்ணீர்,నీళ్ళు"),
        ("Parle-G Biscuit", "pack", 10, 200, 30, "biscuit,biscuits,parle,parle g,parle-g,बिस्कुट,বিস্কুট,பிஸ்கட்"),
        ("Amul Milk 500ml", "packet", 34, 40, 10, "milk,doodh,dudh,amul,amul gold,दूध,দুধ,பால்,పాలు"),
        ("Tata Salt 1kg", "packet", 30, 35, 10, "salt,namak,noon,tata salt,नमक,লবণ,নুন,உப்பு,ఉప్పు"),
        ("Aashirvaad Atta 5kg", "bag", 295, 14, 5, "atta,aata,flour,wheat flour,gehu ka atta,आटा,আটা,கோதுமை மாவு"),
        ("Fortune Oil 1L", "pouch", 165, 6, 8, "oil,tel,cooking oil,soyabean oil,refined oil,तेल,তেল,எண்ணெய்,నూనె"),
        ("Mustard Oil 1L", "bottle", 195, 15, 5,
         "mustard oil,sarson tel,sarson ka tel,sorsher tel,kachi ghani,सरसों तेल,সরষের তেল"),
        ("Sugar 1kg", "packet", 48, 30, 10, "sugar,cheeni,chini,चीनी,চিনি,சர்க்கரை,చక్కెర"),
        ("Toor Dal 1kg", "packet", 170, 18, 6, "dal,daal,toor,toor dal,arhar,arhar dal,दाल,अरहर,ডাল,துவரம் பருப்பு,కంది పప్పు"),
        ("Basmati Rice 5kg", "bag", 499, 4, 5, "rice,chawal,basmati,basmati rice,चावल,চাল,அரிசி,బియ్యం"),
        ("Maggi Noodles", "pack", 14, 90, 20, "maggi,noodles,maggi noodles,मैगी,ম্যাগি,மேகி"),
        ("Lux Soap", "bar", 38, 45, 10, "soap,sabun,lux,साबुन,সাবান,சோப்பு,సబ్బు"),
        ("Colgate Toothpaste 100g", "tube", 60, 25, 8, "toothpaste,colgate,paste,manjan,टूथपेस्ट,টুথপেস্ট"),
        ("Surf Excel 1kg", "packet", 145, 20, 6, "surf,surf excel,detergent,washing powder,सर्फ,সার্ফ,ডিটারজেন্ট"),
        ("Tata Tea Gold 250g", "packet", 165, 20, 6, "tea,chai,chai patti,tata tea,चाय,चायपत्ती,চা পাতা,தேயிலை,టీ పొడి"),
        ("Eggs (1 pc)", "piece", 7, 120, 30, "egg,eggs,anda,ande,dim,अंडा,अंडे,ডিম,முட்டை,గుడ్డు"),
        ("Britannia Bread 400g", "loaf", 50, 15, 4, "bread,pav,double roti,pauruti,ब्रेड,পাউরুটি,ரொட்டி"),
        ("Amul Butter 100g", "pack", 62, 3, 5, "butter,makhan,amul butter,मक्खन,মাখন,வெண்ணெய்"),
    ]),
    "Bakery & sweets": ("Kolkata Sweet House", [
        ("Rasgulla (1 pc)", "piece", 20, 200, 40, "rasgulla,rosogolla,roshogolla,रसगुल्ला,রসগোল্লা"),
        ("Sandesh (1 pc)", "piece", 25, 150, 30, "sandesh,sondesh,संदेश,সন্দেশ"),
        ("Langcha (1 pc)", "piece", 25, 100, 25, "langcha,lyangcha,लांचा,ল্যাংচা"),
        ("Gulab Jamun (1 pc)", "piece", 20, 120, 25, "gulab jamun,jamun,pantua,गुलाब जामुन,পান্তুয়া"),
        ("Mishti Doi 250g", "cup", 70, 40, 10, "mishti doi,doi,sweet curd,dahi,मिष्टी दोई,মিষ্টি দই"),
        ("Kaju Barfi 250g", "box", 300, 4, 5, "kaju barfi,kaju katli,barfi,काजू बर्फी,কাজু বরফি"),
        ("Jalebi 250g", "box", 80, 20, 5, "jalebi,jilipi,जलेबी,জিলিপি"),
        ("Samosa", "piece", 15, 80, 20, "samosa,singara,shingara,समोसा,শিঙাড়া"),
        ("Kachori", "piece", 20, 60, 15, "kachori,kochuri,कचौरी,কচুরি"),
        ("Veg Puff", "piece", 25, 40, 10, "puff,veg puff,patties,पफ,প্যাটিস"),
        ("Cream Roll", "piece", 20, 50, 10, "cream roll,roll,क्रीम रोल,ক্রিম রোল"),
        ("Bread Loaf", "loaf", 50, 30, 8, "bread,pav,double roti,pauruti,ब्रेड,পাউরুটি"),
        ("Fruit Cake 250g", "cake", 120, 25, 6, "fruit cake,plum cake,फ्रूट केक,ফ্রুট কেক"),
        ("Chocolate Cake 500g", "cake", 550, 2, 2, "cake,chocolate cake,birthday cake,केक,কেক"),
        ("Cookies Box", "box", 150, 25, 6, "cookies,biscuits,cookie box,कुकीज़,কুকিজ"),
    ]),
    "Medical store": ("Sanjeevani Medicos", [
        ("Paracetamol 500mg (strip)", "strip", 25, 120, 25, "paracetamol,crocin,calpol,fever tablet,bukhar ki dawai,पेरासिटामोल,প্যারাসিটামল"),
        ("Dolo 650 (strip)", "strip", 34, 100, 25, "dolo,dolo 650,डोलो,ডোলো"),
        ("Cetirizine 10mg (strip)", "strip", 20, 80, 20, "cetirizine,allergy tablet,cetzine,okacet,सेट्रिज़िन"),
        ("Pantoprazole 40mg (strip)", "strip", 110, 50, 12, "pantoprazole,pan 40,pantop,gas tablet,acidity tablet,गैस की दवा"),
        ("Azithromycin 500mg (strip)", "strip", 120, 6, 8, "azithromycin,azithral,azee,एज़िथ्रोमाइसिन"),
        ("Metformin 500mg (strip)", "strip", 35, 60, 15, "metformin,sugar tablet,diabetes tablet,glycomet,शुगर की दवा"),
        ("ORS Sachet", "sachet", 22, 100, 25, "ors,electral,glucose,ओआरएस,ও আর এস"),
        ("Cough Syrup 100ml", "bottle", 120, 30, 8, "cough syrup,syrup,khansi,benadryl,खांसी की दवा,কাশির সিরাপ"),
        ("Vicks VapoRub 50ml", "bottle", 155, 25, 6, "vicks,vaporub,balm,विक्स,ভিক্স"),
        ("Volini Gel 30g", "tube", 125, 4, 5, "volini,pain gel,moov,dard ki dawa,वोलिनी"),
        ("Dettol Antiseptic 250ml", "bottle", 140, 20, 5, "dettol,antiseptic,डेटॉल,ডেটল"),
        ("Bandage Roll", "roll", 45, 50, 10, "bandage,patti,crepe bandage,पट्टी,ব্যান্ডেজ"),
        ("Band-Aid (10 pcs)", "pack", 30, 40, 10, "band aid,bandaid,plaster,बैंड एड"),
        ("Hand Sanitizer 200ml", "bottle", 100, 35, 8, "sanitizer,hand sanitizer,सैनिटाइज़र,স্যানিটাইজার"),
        ("Face Mask (pack of 5)", "pack", 50, 60, 15, "mask,face mask,मास्क,মাস্ক"),
        ("Digital Thermometer", "piece", 250, 3, 3, "thermometer,थर्मामीटर,থার্মোমিটার"),
    ]),
    "Hardware & paint": ("Vishwakarma Hardware", [
        ("Cement 50kg", "bag", 420, 9, 10, "cement,ultratech,acc,सीमेंट,সিমেন্ট"),
        ("Wall Putty 20kg", "bag", 900, 15, 4, "putty,wall putty,birla putty,पुट्टी,পুটি"),
        ("Emulsion Paint 4L", "can", 1450, 10, 3, "paint,emulsion,asian paints,पेंट,পেইন্ট"),
        ("Primer 4L", "can", 850, 8, 3, "primer,प्राइमर,প্রাইমার"),
        ("Paint Brush 4in", "piece", 120, 30, 8, "brush,paint brush,ब्रश,ব্রাশ"),
        ("Sandpaper Sheet", "sheet", 15, 100, 20, "sandpaper,regmal,रेगमाल,শিরিষ কাগজ"),
        ("Screws (box of 100)", "box", 90, 40, 10, "screw,screws,pench,पेंच,স্ক্রু"),
        ("Wire Nails 1kg", "packet", 110, 25, 6, "nails,keel,kil,कील,পেরেক"),
        ("PVC Pipe 1in (10ft)", "length", 210, 25, 6, "pipe,pvc pipe,पाइप,পাইপ"),
        ("Fevicol SH 1kg", "tin", 340, 12, 4, "fevicol,glue,gond,फेविकोल,ফেভিকল"),
        ("LED Bulb 9W", "piece", 99, 60, 15, "bulb,led,led bulb,बल्ब,বাল্ব"),
        ("Switch 6A", "piece", 35, 80, 20, "switch,light switch,स्विच,সুইচ"),
        ("Copper Wire 1.5mm (90m)", "coil", 1650, 2, 3, "wire,copper wire,taar,तार,তার"),
        ("Extension Board 4-socket", "piece", 350, 3, 4, "extension,extension board,spike guard,एक्सटेंशन"),
        ("Electrical Tape", "roll", 25, 70, 15, "tape,insulation tape,टेप,টেপ"),
        ("Padlock 50mm", "piece", 220, 18, 5, "lock,padlock,tala,ताला,তালা"),
    ]),
    "Stationery": ("Vidya Stationers", [
        ("Notebook 200 pages", "piece", 70, 120, 25, "notebook,copy,classmate,कॉपी,খাতা"),
        ("Long Register 300 pages", "piece", 130, 40, 10, "register,long register,रजिस्टर,রেজিস্টার"),
        ("Ball Pen (blue)", "piece", 10, 300, 50, "pen,ball pen,blue pen,पेन,কলম"),
        ("Gel Pen (black)", "piece", 20, 150, 30, "gel pen,black pen,जेल पेन"),
        ("Pencil", "piece", 5, 250, 50, "pencil,apsara,पेंसिल,পেন্সিল"),
        ("Eraser", "piece", 5, 200, 40, "eraser,rubber,रबर,ইরেজার,রাবার"),
        ("Sharpener", "piece", 5, 150, 30, "sharpener,cutter,शार्पनर,কাটার"),
        ("Scale 30cm", "piece", 15, 80, 20, "scale,ruler,स्केल,স্কেল"),
        ("Highlighter", "piece", 30, 60, 15, "highlighter,marker,हाइलाइटर"),
        ("Geometry Box", "box", 150, 4, 5, "geometry box,compass box,ज्योमेट्री बॉक्स,জ্যামিতি বাক্স"),
        ("A4 Paper Ream", "ream", 350, 3, 4, "a4,paper,rim,ream,कागज़,কাগজ"),
        ("Glue Stick", "piece", 25, 60, 15, "glue,fevistick,glue stick,गोंद,আঠা"),
        ("Stapler", "piece", 120, 15, 4, "stapler,स्टेपलर,স্ট্যাপলার"),
        ("Colour Pencils (12)", "box", 90, 30, 8, "colour pencil,color pencils,crayons,रंगीन पेंसिल,রং পেন্সিল"),
        ("Sticky Notes", "pad", 60, 40, 10, "sticky notes,post it,स्टिकी नोट्स"),
        ("Scientific Calculator", "piece", 650, 2, 3, "calculator,casio,fx-82,कैलकुलेटर,ক্যালকুলেটর"),
    ]),
    "Custom (start empty)": ("My Shop", []),
}
DEFAULT_TEMPLATE = "Kirana / General store"
# Obviously fictional numbers. First names stay unique so "Amit" / "Priya" / "Sunita" resolve to one person.
# No "Rahul" on purpose: the live demo creates him as a new customer.
SEED_CUSTOMERS = [
    ("Priya Sharma", "98300 11223"), ("Amit Das", "98310 44556"), ("Sunita Devi", "97480 77889"),
    ("Subhajit Mondal", "90510 22334"), ("Rina Ghosh", "83480 55667"), ("Mohammed Irfan", "70010 88990"),
    ("Tanmay Mahato", "62970 12121"), ("Ankit Agarwal", "99030 34343"), ("Lakshmi Narayanan", "94440 56565"),
    ("Venkatesh Reddy", "91000 78787"),
]
# How each regular settles up: "full" pays at the counter, "khata" runs a tab and pays some of it later,
# "clears" pays part at the counter and later clears the whole tab.
_PAY_STYLE = {"Priya Sharma": "full", "Ankit Agarwal": "full", "Lakshmi Narayanan": "full", "Venkatesh Reddy": "full",
              "Amit Das": "khata", "Sunita Devi": "khata", "Subhajit Mondal": "khata", "Tanmay Mahato": "khata",
              "Rina Ghosh": "clears", "Mohammed Irfan": "clears", "Walk-in Customer": "full"}
# Kept out of the seeded history so the scripted live demo starts from known numbers.
_DEMO_PROTECTED = {"Water Bottle 1L"}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """All-or-nothing: BEGIN IMMEDIATE takes the write lock up front so concurrent submits serialise."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def init_db(reset: bool = False, template: str | None = None, business_name: str | None = None) -> None:
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = connect()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        _seed(conn, template or DEFAULT_TEMPLATE, business_name)
    conn.close()


def _seed(conn: sqlite3.Connection, template: str, business_name: str | None) -> None:
    default_name, products = BUSINESS_TEMPLATES[template]
    rng = random.Random(42)  # deterministic: every fresh shop of a type looks the same
    start = datetime.now()
    with transaction(conn):
        for name, unit, price, stock, low, aliases in products:
            conn.execute(
                "INSERT INTO products(name, unit, price, stock, low_stock_at, aliases) VALUES (?,?,?,?,?,?)",
                (name, unit, price, stock, low, aliases))
        for name, phone in SEED_CUSTOMERS:
            joined = (start - timedelta(days=rng.randint(30, 240), hours=rng.randint(0, 10))).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT INTO customers(name, phone, created_at) VALUES (?,?,?)", (name, phone, joined))
        for m in MODULES:
            conn.execute("INSERT INTO settings(key, value) VALUES (?, '1')", (f"module:{m}",))
        conn.execute("INSERT INTO settings(key, value) VALUES ('business_name', ?)", (business_name or default_name,))
        conn.execute("INSERT INTO settings(key, value) VALUES ('business_type', ?)", (template,))
    if len(products) < 3:
        return
    _seed_history(conn, products, rng, start)


def _seed_history(conn, products, rng, start: datetime) -> None:
    """Two weeks of believable trade, written through the same build_plan -> commit_plan path the app uses.
    Items that start below their reorder level, and demo-protected items, are never sold, and no sale takes
    any other item down to its reorder level, so the low-stock list is exactly what the catalog declares."""
    mods = {m: True for m in MODULES}
    initial = {p[0]: (p[2], p[3], p[4]) for p in products}  # name -> (price, stock, low)
    sellable = [n for n, (_, s, low) in initial.items() if s > low and n not in _DEMO_PROTECTED]
    if not sellable:
        return
    regulars = [c for c, _ in SEED_CUSTOMERS]
    weights = [9 if c in ("Amit Das", "Sunita Devi", "Priya Sharma") else 5 for c in regulars] + [8]
    buyers = regulars + ["Walk-in Customer"]
    today0 = start.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days_ago: int, hour: float) -> datetime:
        if days_ago == 0:  # today: spread across the part of the day that has already happened
            span = (start - today0).total_seconds()
            return today0 + timedelta(seconds=span * min(hour, 21) / 22)
        return today0 - timedelta(days=days_ago) + timedelta(hours=hour)

    events = []  # (when, kind, data)
    for d in range(13, -1, -1):
        n = 3 if d == 0 else rng.choice([1, 2, 2, 2, 3])
        for h in sorted(rng.uniform(8, 21) for _ in range(n)):
            cust = rng.choices(buyers, weights)[0]
            picks = rng.sample(sellable, min(len(sellable), rng.choice([1, 2, 2, 3, 3, 4])))
            events.append((at(d, h), "sale", cust, picks))
    # Settling up against the tab, and two supplier deliveries.
    for d, cust in [(9, "Rina Ghosh"), (6, "Amit Das"), (4, "Mohammed Irfan"), (3, "Subhajit Mondal"),
                    (1, "Sunita Devi"), (1, "Tanmay Mahato")]:
        events.append((at(d, rng.uniform(17, 20.5)), "payment", cust, None))
    events.append((at(8, 7.5), "restock", None, None))
    events.append((at(3, 7.5), "restock", None, None))
    events.sort(key=lambda e: e[0])
    # Every regular shows up at least once: the first sales of the fortnight go round the customer book.
    sale_idx = [i for i, e in enumerate(events) if e[1] == "sale"]
    first = regulars[:]
    rng.shuffle(first)
    for i, cust in zip(sale_idx, first):
        events[i] = (events[i][0], "sale", cust, events[i][3])

    def stock_of(name):
        return conn.execute("SELECT stock FROM products WHERE name=?", (name,)).fetchone()[0]

    def qty_for(price):
        if price <= 12:
            return rng.randint(3, 12)
        if price <= 30:
            return rng.randint(2, 6)
        if price <= 80:
            return rng.randint(1, 4)
        if price <= 200:
            return rng.randint(1, 2)
        return 1

    restocked = 0
    for when, kind, cust, picks in events:
        ts = when.strftime("%Y-%m-%d %H:%M:%S")
        try:
            if kind == "sale":
                items = []
                for name in picks:
                    price, _, low = initial[name]
                    q = min(qty_for(price), stock_of(name) - low - 1)
                    if q > 0:
                        items.append({"product": name, "quantity": q, "stated_unit_price": None})
                if not items:
                    continue
                style = _PAY_STYLE.get(cust, "full")
                plan = build_plan({"intent": "sale", "customer_name": cust, "items": items, "payment_amount": None,
                                   "payment_method": rng.choices(["cash", "upi", "card"], [5, 4, 1])[0]}, mods, conn)
                sub = plan["subtotal"]
                share = 1.0 if style == "full" else rng.choice([0.0, 0.0, 0.5] if style == "khata" else [1.0, 0.5, 0.0])
                plan["payment_amount"] = sub if share == 1.0 else float(min(sub, round(sub * share / 10) * 10))
                if plan["payment_amount"] == 0 and plan["payment_method"] == "card":
                    plan["payment_method"] = "cash"
                recompute(plan, mods, conn)
            elif kind == "payment":
                c = find_customer(cust, conn)
                due = customer_dues(conn, c["id"]) if c else 0
                if _PAY_STYLE.get(cust) == "clears":
                    amount = due
                else:  # pays a round part of the tab and keeps the rest running
                    amount = float(int(due * rng.uniform(0.35, 0.6) / 50) * 50)
                if amount <= 0:
                    continue
                plan = build_plan({"intent": "payment", "customer_name": cust, "items": [], "payment_amount": amount,
                                   "payment_method": rng.choice(["cash", "upi"])}, mods, conn)
            else:  # restock the two most-sold items back up toward their opening level
                rows = conn.execute("""SELECT p.name, p.stock FROM products p JOIN order_items oi ON oi.product_id = p.id
                                       GROUP BY p.id ORDER BY SUM(oi.quantity) DESC""").fetchall()
                rows = [r for r in rows if r["name"] in sellable][restocked * 2: restocked * 2 + 2]
                restocked += 1
                items = [{"product": r["name"], "quantity": max(initial[r["name"]][1] - r["stock"], 1),
                          "stated_unit_price": None} for r in rows]
                if not items:
                    continue
                plan = build_plan({"intent": "restock", "customer_name": None, "items": items, "payment_amount": None,
                                   "payment_method": None}, mods, conn)
            plan["source_text"] = None
            commit_plan(plan, mods, conn, when=ts)
        except ValueError:  # e.g. would break a stock or money rule: skip, history is decoration
            continue


def save_catalog(conn, rows: list[dict]) -> int:
    """Insert or update catalog rows from the owner's editor. All-or-nothing. Returns rows written."""
    clean = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        low = r.get("low_stock_at")
        try:
            price, stock, low = float(r["price"]), int(r["stock"]), int(0 if low is None or low != low else low)
            if price != price:  # a cleared cell arrives as NaN, which SQLite would store as NULL
                raise ValueError
        except (TypeError, ValueError, KeyError):
            raise ValueError(f"'{name}': price, stock and reorder level must be numbers.")
        if price < 0 or stock < 0 or low < 0:
            raise ValueError(f"'{name}': values can't be negative.")
        clean.append((name, str(r.get("unit") or "unit").strip(), price, stock, low, str(r.get("aliases") or "").strip()))
    with transaction(conn):
        for name, unit, price, stock, low, aliases in clean:
            old = conn.execute("SELECT id, stock FROM products WHERE name=?", (name,)).fetchone()
            conn.execute("""INSERT INTO products(name, unit, price, stock, low_stock_at, aliases) VALUES (?,?,?,?,?,?)
                            ON CONFLICT(name) DO UPDATE SET unit=excluded.unit, price=excluded.price,
                            stock=excluded.stock, low_stock_at=excluded.low_stock_at, aliases=excluded.aliases""",
                         (name, unit, price, stock, low, aliases))
            change = stock - (old["stock"] if old else 0)
            if change:
                pid = old["id"] if old else conn.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()[0]
                conn.execute("INSERT INTO stock_moves(product_id, change, reason, ref, created_at) VALUES (?,?,?,?,?)",
                             (pid, change, "manual adjustment", None, now()))
    return len(clean)


# ---------------------------------------------------------------- settings

def get_modules(conn) -> dict[str, bool]:
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'module:%'").fetchall()
    found = {r["key"][7:]: r["value"] == "1" for r in rows}
    return {m: found.get(m, True) for m in MODULES}


def set_module(conn, module: str, enabled: bool) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (f"module:{module}", "1" if enabled else "0"))


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))


# ---------------------------------------------------------------- AI extraction

PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["sale", "payment", "restock", "unknown"]},
        "customer_name": {"type": ["string", "null"]},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "product": {"type": "string"},
                "quantity": {"type": "number"},
                "stated_unit_price": {"type": ["number", "null"]},
            },
            "required": ["product", "quantity", "stated_unit_price"],
            "additionalProperties": False}},
        "payment_amount": {"type": ["number", "null"]},
        "payment_method": {"type": ["string", "null"], "enum": ["cash", "upi", "card", "other", None]},
        "language": {"type": "string"},
    },
    "required": ["intent", "customer_name", "items", "payment_amount", "payment_method", "language"],
    "additionalProperties": False,
}


def _system_prompt(conn) -> str:
    products = conn.execute("SELECT name, aliases FROM products ORDER BY name").fetchall()
    customers = [r["name"] for r in conn.execute("SELECT name FROM customers ORDER BY name")]
    catalog = "\n".join(f"- {p['name']} (also called: {p['aliases']})" for p in products)
    return f"""You extract structured shop transactions from a shop owner's instruction.
The instruction may be in English, Hindi, Hinglish, Bengali or a mix, typed or transcribed from speech.

Shop catalog (map every item to the closest catalog name; if nothing fits, keep the item as spoken):
{catalog}

Known customers: {", ".join(customers) or "none yet"}. Reuse a known name when it clearly refers to the same person; transliterate names to English letters.

Intents:
- "sale": a customer bought items (an advance/partial payment may also be mentioned).
- "payment": a customer paid money towards earlier dues and bought nothing.
- "restock": the owner received new stock from a supplier (customer_name null).
- "unknown": anything else.

Rules:
- Extract ONLY what the instruction says. Never invent prices, totals or payments.
- quantity = number of units. stated_unit_price = per-unit price only if the instruction says it, else null.
- payment_amount = money actually paid now (advance, partial, full); null if not mentioned. If they say "paid in full" without an amount, set null.
- payment_method: "upi" for UPI/GPay/PhonePe/Paytm, "card", "cash" when cash is said OR no method is mentioned, "other" only for cheque/bank transfer.
- language: the language of the instruction, e.g. "English", "Hindi", "Hinglish", "Bengali".
Return only JSON matching the schema."""


def ai_available() -> bool:
    return bool(os.getenv("SARVAM_API_KEY"))


_API_DOWN_UNTIL = 0.0  # circuit breaker: after a failure, skip Sarvam briefly instead of waiting on every click


def api_failed() -> None:
    global _API_DOWN_UNTIL
    import time
    _API_DOWN_UNTIL = time.time() + 120


def _client():
    import time
    from sarvamai import SarvamAI
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is missing from .env")
    if time.time() < _API_DOWN_UNTIL:
        raise RuntimeError("Sarvam API recently failed; using offline mode for a moment")
    return SarvamAI(api_subscription_key=key, timeout=20)


def parse_command(text: str, conn) -> dict:
    """Sarvam-105B first; if the API is unreachable or out of credits, fall back to offline rules so the
    demo flow never dead-ends (the owner still reviews the preview before anything is saved)."""
    try:
        return _parse_with_ai(text, conn)
    except Exception:
        api_failed()
        from offline_parser import parse_offline
        parsed = normalise_parsed(parse_offline(text, conn, match_product, find_customer))
        parsed["language"] = "offline rules (AI unavailable)"
        if parsed["intent"] == "unknown":
            raise
        return parsed


def _parse_with_ai(text: str, conn) -> dict:
    client = _client()
    messages = [{"role": "system", "content": _system_prompt(conn)}, {"role": "user", "content": text}]
    try:
        resp = client.chat.completions(
            model=MODEL, messages=messages, temperature=0, reasoning_effort=None, max_tokens=800,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "shop_transaction", "strict": True, "schema": PARSE_SCHEMA}})
    except Exception:
        # Some schema features may be rejected; fall back to plain JSON mode with the shape in the prompt.
        messages[0]["content"] += "\nJSON shape: " + json.dumps(PARSE_SCHEMA["properties"])
        resp = client.chat.completions(model=MODEL, messages=messages, temperature=0, reasoning_effort=None,
                                       max_tokens=800, response_format={"type": "json_object"})
    content = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError(f"Model did not return JSON: {content[:200]}")
    parsed = normalise_parsed(json.loads(match.group(0)))
    if parsed["payment_method"] == "other" and not re.search(r"cheque|check|bank|neft|imps|rtgs|transfer", text, re.I):
        parsed["payment_method"] = "cash"
    return parsed


def normalise_parsed(d: dict) -> dict:
    out = {
        "intent": d.get("intent") if d.get("intent") in ("sale", "payment", "restock") else "unknown",
        "customer_name": (d.get("customer_name") or "").strip() or None,
        "items": [],
        "payment_amount": d.get("payment_amount"),
        "payment_method": d.get("payment_method") if d.get("payment_method") in ("cash", "upi", "card", "other") else "cash",
        "language": d.get("language") or "",
    }
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("product"):
            out["items"].append({"product": str(it["product"]).strip(), "quantity": it.get("quantity"),
                                 "stated_unit_price": it.get("stated_unit_price")})
    return out


def transcribe(audio_bytes: bytes, filename: str = "command.wav", keyterms: list[str] | None = None,
               language_code: str = "unknown") -> str:
    """Sarvam speech-to-text (Saaras). Product/customer names are passed as keyterms. Raises on failure."""
    client = _client()
    last_err = None
    for model in ("saaras:v4", "saaras:v3"):
        try:
            kwargs = {"file": (filename, audio_bytes), "model": model, "mode": "transcribe", "language_code": language_code}
            if keyterms:
                kwargs["keyterms"] = keyterms[:50]
            resp = client.speech_to_text.transcribe(**kwargs)
            return (getattr(resp, "transcript", None) or "").strip()
        except Exception as e:  # try the next model id
            last_err = e
    raise RuntimeError(f"Speech-to-text failed: {last_err}")


# ---------------------------------------------------------------- matching & planning

def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", (s or "").lower()).strip()


def match_product(spoken: str, conn):
    """Map a spoken item name to a catalog row, or None. Exact name/alias first, then fuzzy."""
    s = _norm(spoken)
    if not s:
        return None
    products = conn.execute("SELECT * FROM products").fetchall()
    keys = []
    for p in products:
        for k in [p["name"]] + [a for a in p["aliases"].split(",") if a.strip()]:
            keys.append((_norm(k), p))
    for k, p in keys:
        if s == k:
            return p
    for k, p in keys:  # whole-word containment either way, e.g. "water bottles" / "1L bottle"
        if k and (re.search(rf"\b{re.escape(k)}\b", s) or re.search(rf"\b{re.escape(s)}\b", k)):
            return p
    names = [k for k, _ in keys]
    close = difflib.get_close_matches(s, names, n=1, cutoff=0.72)
    if close:
        return dict((k, p) for k, p in keys)[close[0]]
    return None


def find_customer(name: str, conn):
    if not name:
        return None
    row = conn.execute("SELECT * FROM customers WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()
    if row:
        return row
    rows = conn.execute("SELECT * FROM customers").fetchall()
    first = {r["name"].split()[0].lower(): r for r in rows}
    if name.strip().lower() in first:  # "Priya" -> "Priya Sharma"
        return first[name.strip().lower()]
    return None


def build_plan(parsed: dict, modules: dict, conn) -> dict:
    """Turn extracted intent into a fully priced, validated plan. Prices come only from the DB."""
    plan = {"request_id": str(uuid.uuid4()), "intent": parsed.get("intent", "unknown"),
            "customer_name": parsed.get("customer_name"), "customer_exists": False,
            "lines": [], "subtotal": 0.0, "payment_amount": 0.0,
            "payment_method": parsed.get("payment_method") or "cash",
            "balance": 0.0, "errors": [], "warnings": [], "actions": [], "skipped": [],
            "language": parsed.get("language", ""), "prior_dues": 0.0}
    intent = plan["intent"]
    cust = find_customer(plan["customer_name"], conn)
    if cust:
        plan["customer_name"], plan["customer_exists"] = cust["name"], True
        plan["prior_dues"] = customer_dues(conn, cust["id"])

    if intent == "unknown":
        plan["errors"].append("Couldn't tell whether this is a sale, a payment or a restock. Rephrase, or use manual entry.")
        return plan

    # ---- lines (sale / restock)
    if intent in ("sale", "restock"):
        if not parsed.get("items"):
            plan["errors"].append("No products found in the instruction.")
        seen = {}
        for it in parsed.get("items", []):
            q = it.get("quantity")
            line = {"spoken": it["product"], "product_id": None, "product": None, "unit": "",
                    "quantity": q, "unit_price": 0.0, "line_total": 0.0, "stock": None, "ok": True}
            p = match_product(it["product"], conn)
            if p is None:
                line["ok"] = False
                plan["errors"].append(f"'{it['product']}' is not in your catalog.")
            else:
                line.update(product_id=p["id"], product=p["name"], unit=p["unit"], unit_price=float(p["price"]),
                            stock=int(p["stock"]))
                stated = it.get("stated_unit_price")
                if stated not in (None, "") and abs(float(stated) - float(p["price"])) > 0.001:
                    plan["warnings"].append(
                        f"You said ₹{float(stated):g} for {p['name']}, but the catalog price is ₹{p['price']:g}. "
                        "Using the catalog price — edit it below if you agreed a different price.")
            if not isinstance(q, (int, float)) or q <= 0 or float(q) != int(q):
                line["ok"] = False
                plan["errors"].append(f"Invalid quantity '{q}' for {line['product'] or it['product']} (whole units > 0).")
            else:
                line["quantity"] = int(q)
                line["line_total"] = round(line["unit_price"] * line["quantity"], 2)
            if line["product_id"] and line["product_id"] in seen:  # merge duplicates of the same product
                prev = seen[line["product_id"]]
                if line["ok"] and prev["ok"]:
                    prev["quantity"] += line["quantity"]
                    prev["line_total"] = round(prev["unit_price"] * prev["quantity"], 2)
                continue
            if line["product_id"]:
                seen[line["product_id"]] = line
            plan["lines"].append(line)
        plan["subtotal"] = round(sum(l["line_total"] for l in plan["lines"] if l["ok"]), 2)

    pay = parsed.get("payment_amount")
    if pay not in (None, ""):
        try:
            pay = float(pay)
        except (TypeError, ValueError):
            pay = -1
        if pay < 0:
            plan["errors"].append("Payment amount must be zero or more.")
            pay = 0.0
        plan["payment_amount"] = round(pay, 2)

    validate_plan(plan, modules, conn)
    return plan


def recompute(plan: dict, modules: dict, conn) -> dict:
    """Re-validate after the owner edits the preview (products, quantities, prices, payment, customer)."""
    errors = []
    for l in plan["lines"]:
        if not l["product_id"]:
            l["ok"] = False
            errors.append(f"'{l['spoken']}' is not in your catalog — pick a product or delete the row.")
            continue
        p = conn.execute("SELECT name, unit, stock FROM products WHERE id=?", (l["product_id"],)).fetchone()
        l["product"], l["unit"], l["stock"] = p["name"], p["unit"], int(p["stock"])
        q = l["quantity"]
        l["ok"] = isinstance(q, int) and q > 0 and l["unit_price"] >= 0
        if not l["ok"]:
            errors.append(f"Invalid quantity or price for {l['product']} (whole units > 0, price ≥ 0).")
        l["line_total"] = round(l["unit_price"] * q, 2) if l["ok"] else 0.0
    if plan["intent"] in ("sale", "restock") and not plan["lines"]:
        errors.append("Add at least one product.")
    if plan["payment_amount"] < 0:
        errors.append("Payment amount must be zero or more.")
    plan["subtotal"] = round(sum(l["line_total"] for l in plan["lines"] if l["ok"]), 2)
    cust = find_customer(plan["customer_name"], conn)
    if cust:
        plan["customer_name"] = cust["name"]
    plan["customer_exists"] = bool(cust)
    plan["prior_dues"] = customer_dues(conn, cust["id"]) if cust else 0.0
    plan["errors"], plan["warnings"] = errors, []
    validate_plan(plan, modules, conn)
    return plan


def validate_plan(plan: dict, modules: dict, conn) -> None:
    """Fill plan['actions'] / ['skipped'] / ['balance'] and enforce module + stock + money rules."""
    intent, errors, actions, skipped = plan["intent"], plan["errors"], [], []
    plan["actions"], plan["skipped"] = actions, skipped

    if intent == "sale":
        if not modules.get("Orders"):
            errors.append("The Orders module is disabled, so sales can't be recorded.")
        if not plan["customer_name"]:
            plan["customer_name"] = "Walk-in Customer"
            plan["warnings"].append("No customer named — saving as 'Walk-in Customer'.")
        if modules.get("Inventory"):
            for l in plan["lines"]:
                if l["ok"] and l["stock"] is not None and l["quantity"] > l["stock"]:
                    errors.append(f"Insufficient stock: {l['product']} has {l['stock']} {l['unit']}(s), "
                                  f"order needs {l['quantity']}.")
        pay = plan["payment_amount"]
        if pay and not modules.get("Payments"):
            skipped.append(f"Payment of ₹{pay:,.2f} not recorded — Payments module is disabled.")
            pay_effective = 0.0
        else:
            pay_effective = pay
        if pay_effective > plan["subtotal"] + 1e-9:
            errors.append(f"Payment ₹{pay_effective:,.2f} is more than the bill ₹{plan['subtotal']:,.2f}. "
                          "Record the extra as a separate payment against dues.")
        plan["balance"] = round(plan["subtotal"] - pay_effective, 2)
        if modules.get("Orders"):
            actions.append(f"Create order for {plan['customer_name']}"
                           f"{'' if plan['customer_exists'] else ' (new customer)'} — ₹{plan['subtotal']:,.2f}")
        if modules.get("Invoices"):
            actions.append("Generate invoice")
        else:
            skipped.append("Invoice not generated — Invoices module is disabled.")
        if pay_effective:
            actions.append(f"Record {plan['payment_method'].upper()} payment ₹{pay_effective:,.2f}; "
                           f"outstanding ₹{plan['balance']:,.2f}")
        if modules.get("Inventory"):
            for l in plan["lines"]:
                if l["ok"]:
                    actions.append(f"Reduce {l['product']} stock {l['stock']} → {l['stock'] - l['quantity']}")
        else:
            skipped.append("Stock not changed — Inventory module is disabled.")

    elif intent == "payment":
        if not modules.get("Payments"):
            errors.append("The Payments module is disabled, so payments can't be recorded.")
        if not plan["customer_exists"]:
            errors.append(f"No existing customer called '{plan['customer_name'] or '?'}' with dues.")
        if plan["payment_amount"] <= 0:
            errors.append("No payment amount found.")
        elif plan["customer_exists"] and plan["payment_amount"] > plan["prior_dues"] + 1e-9:
            errors.append(f"Payment ₹{plan['payment_amount']:,.2f} is more than {plan['customer_name']}'s "
                          f"outstanding ₹{plan['prior_dues']:,.2f}.")
        plan["balance"] = round(plan["prior_dues"] - plan["payment_amount"], 2)
        actions.append(f"Record {plan['payment_method'].upper()} payment ₹{plan['payment_amount']:,.2f} from "
                       f"{plan['customer_name']} against oldest dues; remaining ₹{plan['balance']:,.2f}")

    elif intent == "restock":
        if not modules.get("Inventory"):
            errors.append("The Inventory module is disabled, so stock can't be changed.")
        for l in plan["lines"]:
            if l["ok"]:
                actions.append(f"Increase {l['product']} stock {l['stock']} → {l['stock'] + l['quantity']}")

    # de-duplicate messages, keep order
    plan["errors"] = list(dict.fromkeys(errors))
    plan["warnings"] = list(dict.fromkeys(plan["warnings"]))


# ---------------------------------------------------------------- commit

class DuplicateSubmission(Exception):
    pass


def commit_plan(plan: dict, modules: dict, conn, when: str | None = None) -> dict:
    """Write the whole plan in ONE transaction. Re-checks stock inside the lock. Returns ids created."""
    if plan["errors"]:
        raise ValueError("Plan has errors: " + "; ".join(plan["errors"]))
    ts = when or now()
    result = {"order_id": None, "invoice_no": None, "payment_ids": []}
    with transaction(conn):
        try:
            conn.execute("INSERT INTO processed_requests(request_id, created_at) VALUES (?, ?)",
                         (plan["request_id"], ts))
        except sqlite3.IntegrityError:
            raise DuplicateSubmission("This command was already saved — duplicate submission blocked.")

        intent = plan["intent"]
        if intent == "sale":
            cust = find_customer(plan["customer_name"], conn)
            cid = cust["id"] if cust else conn.execute(
                "INSERT INTO customers(name, created_at) VALUES (?, ?)", (plan["customer_name"].strip(), ts)).lastrowid
            lines = [l for l in plan["lines"] if l["ok"]]
            if not lines:
                raise ValueError("Nothing to sell.")
            total = round(sum(l["unit_price"] * l["quantity"] for l in lines), 2)
            oid = conn.execute("INSERT INTO orders(customer_id, created_at, total, request_id, source_text) "
                               "VALUES (?,?,?,?,?)",
                               (cid, ts, total, plan["request_id"], plan.get("source_text"))).lastrowid
            result["order_id"] = oid
            for l in lines:
                conn.execute("INSERT INTO order_items(order_id, product_id, quantity, unit_price, line_total) "
                             "VALUES (?,?,?,?,?)",
                             (oid, l["product_id"], l["quantity"], l["unit_price"],
                              round(l["unit_price"] * l["quantity"], 2)))
                if modules.get("Inventory"):
                    # Guarded decrement: fails if stock changed since the preview.
                    cur = conn.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                                       (l["quantity"], l["product_id"], l["quantity"]))
                    if cur.rowcount != 1:
                        raise ValueError(f"Insufficient stock for {l['product']} (changed since preview).")
                    conn.execute("INSERT INTO stock_moves(product_id, change, reason, ref, created_at) "
                                 "VALUES (?,?,?,?,?)", (l["product_id"], -l["quantity"], "sale", f"order:{oid}", ts))
            if modules.get("Invoices"):
                inv = f"INV-{datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'):%Y%m%d}-{oid:04d}"
                conn.execute("INSERT INTO invoices(order_id, invoice_no, created_at) VALUES (?,?,?)", (oid, inv, ts))
                result["invoice_no"] = inv
            pay = plan["payment_amount"] if modules.get("Payments") else 0
            if pay and pay > 0:
                if pay > total + 1e-9:
                    raise ValueError("Payment exceeds bill.")
                pid = conn.execute("INSERT INTO payments(order_id, customer_id, amount, method, created_at, request_id) "
                                   "VALUES (?,?,?,?,?,?)",
                                   (oid, cid, pay, plan["payment_method"], ts, plan["request_id"])).lastrowid
                result["payment_ids"].append(pid)

        elif intent == "payment":
            cust = find_customer(plan["customer_name"], conn)
            if not cust:
                raise ValueError("Unknown customer.")
            remaining = plan["payment_amount"]
            if remaining > customer_dues(conn, cust["id"]) + 1e-9:
                raise ValueError("Payment exceeds outstanding dues.")
            for o in open_orders(conn, cust["id"]):  # oldest first
                if remaining <= 0:
                    break
                amt = round(min(remaining, o["due"]), 2)
                pid = conn.execute("INSERT INTO payments(order_id, customer_id, amount, method, created_at, request_id) "
                                   "VALUES (?,?,?,?,?,?)",
                                   (o["id"], cust["id"], amt, plan["payment_method"], ts, plan["request_id"])).lastrowid
                result["payment_ids"].append(pid)
                remaining = round(remaining - amt, 2)

        elif intent == "restock":
            for l in plan["lines"]:
                if l["ok"]:
                    conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (l["quantity"], l["product_id"]))
                    conn.execute("INSERT INTO stock_moves(product_id, change, reason, ref, created_at) "
                                 "VALUES (?,?,?,?,?)", (l["product_id"], l["quantity"], "restock", None, ts))
        else:
            raise ValueError("Unknown intent.")
    return result


# ---------------------------------------------------------------- queries

def customer_dues(conn, customer_id: int) -> float:
    row = conn.execute("""
        SELECT COALESCE(SUM(o.total), 0) - COALESCE((SELECT SUM(amount) FROM payments WHERE customer_id = ?), 0)
        FROM orders o WHERE o.customer_id = ?""", (customer_id, customer_id)).fetchone()
    return round(row[0] or 0.0, 2)


def open_orders(conn, customer_id: int):
    return conn.execute("""
        SELECT o.id, o.created_at, o.total, o.total - COALESCE(SUM(p.amount), 0) AS due
        FROM orders o LEFT JOIN payments p ON p.order_id = o.id
        WHERE o.customer_id = ? GROUP BY o.id HAVING due > 0.001 ORDER BY o.created_at, o.id""",
                        (customer_id,)).fetchall()


def dashboard_stats(conn) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    sales = conn.execute("SELECT COALESCE(SUM(total),0), COUNT(*) FROM orders WHERE date(created_at)=?",
                         (today,)).fetchone()
    collected = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at)=?",
                             (today,)).fetchone()[0]
    outstanding = conn.execute("SELECT COALESCE((SELECT SUM(total) FROM orders),0) - "
                               "COALESCE((SELECT SUM(amount) FROM payments),0)").fetchone()[0]
    low = conn.execute("SELECT COUNT(*) FROM products WHERE stock <= low_stock_at").fetchone()[0]
    return {"sales_today": sales[0], "orders_today": sales[1], "collected_today": collected,
            "outstanding": round(outstanding, 2), "low_stock": low}


def orders_table(conn, search: str = ""):
    q = f"%{search.strip()}%"
    return conn.execute("""
        SELECT o.id, o.created_at, c.name AS customer, o.total,
               COALESCE((SELECT SUM(amount) FROM payments WHERE order_id=o.id),0) AS paid,
               o.total - COALESCE((SELECT SUM(amount) FROM payments WHERE order_id=o.id),0) AS due,
               i.invoice_no,
               (SELECT GROUP_CONCAT(p.name || ' × ' || oi.quantity, ', ') FROM order_items oi
                  JOIN products p ON p.id = oi.product_id WHERE oi.order_id = o.id) AS items
        FROM orders o JOIN customers c ON c.id = o.customer_id
        LEFT JOIN invoices i ON i.order_id = o.id
        WHERE c.name LIKE ? OR IFNULL(i.invoice_no,'') LIKE ? OR CAST(o.id AS TEXT) LIKE ?
           OR EXISTS (SELECT 1 FROM order_items oi JOIN products p ON p.id=oi.product_id
                      WHERE oi.order_id=o.id AND p.name LIKE ?)
        ORDER BY o.created_at DESC, o.id DESC""", (q, q, q, q)).fetchall()


def customers_with_dues(conn):
    return conn.execute("""
        SELECT c.id, c.name, c.phone,
               COALESCE((SELECT SUM(total) FROM orders WHERE customer_id=c.id),0) AS billed,
               COALESCE((SELECT SUM(amount) FROM payments WHERE customer_id=c.id),0) AS paid,
               COALESCE((SELECT SUM(total) FROM orders WHERE customer_id=c.id),0)
                 - COALESCE((SELECT SUM(amount) FROM payments WHERE customer_id=c.id),0) AS due,
               (SELECT MAX(created_at) FROM orders WHERE customer_id=c.id) AS last_order
        FROM customers c ORDER BY due DESC, c.name""").fetchall()


def invoice_data(conn, order_id: int):
    o = conn.execute("""SELECT o.*, c.name AS customer, c.phone, i.invoice_no, i.created_at AS invoice_date
                        FROM orders o JOIN customers c ON c.id=o.customer_id
                        LEFT JOIN invoices i ON i.order_id=o.id WHERE o.id=?""", (order_id,)).fetchone()
    if not o:
        return None
    items = conn.execute("""SELECT p.name, p.unit, oi.quantity, oi.unit_price, oi.line_total FROM order_items oi
                            JOIN products p ON p.id=oi.product_id WHERE oi.order_id=? ORDER BY oi.id""",
                         (order_id,)).fetchall()
    pays = conn.execute("SELECT amount, method, created_at FROM payments WHERE order_id=? ORDER BY id",
                        (order_id,)).fetchall()
    return {"order": o, "items": items, "payments": pays}


# ---------------------------------------------------------------- languages (Sarvam Translate + Bulbul)

LANGUAGES = {"en-IN": "English", "hi-IN": "हिन्दी (Hindi)", "bn-IN": "বাংলা (Bengali)", "ta-IN": "தமிழ் (Tamil)",
             "te-IN": "తెలుగు (Telugu)", "mr-IN": "मराठी (Marathi)", "gu-IN": "ગુજરાતી (Gujarati)",
             "kn-IN": "ಕನ್ನಡ (Kannada)", "ml-IN": "മലയാളം (Malayalam)", "pa-IN": "ਪੰਜਾਬੀ (Punjabi)",
             "od-IN": "ଓଡ଼ିଆ (Odia)"}
_SEP = "\n---\n"


def translate_many(texts: list[str], lang: str, conn) -> list[str]:
    """Translate UI/dynamic strings with Sarvam Translate, batching with a separator and caching in SQLite.
    Never raises: on any failure the English text is returned so the app keeps working."""
    if lang == "en-IN" or not texts:
        return list(texts)
    out, missing = {}, []
    for t in dict.fromkeys(texts):
        row = conn.execute("SELECT dst FROM translations WHERE lang=? AND src=?", (lang, t)).fetchone()
        if row:
            out[t] = row[0]
        elif t.strip():
            missing.append(t)
        else:
            out[t] = t
    if missing:
        try:
            client = _client()
        except Exception:
            client = None
        chunks, cur = [], []
        for t in missing:
            if cur and len(_SEP.join(cur + [t])) > 1500:
                chunks.append(cur)
                cur = []
            cur.append(t)
        if cur:
            chunks.append(cur)
        for chunk in chunks:
            got = None
            if client:
                try:
                    r = client.text.translate(input=_SEP.join(chunk), source_language_code="en-IN",
                                              target_language_code=lang, model="sarvam-translate:v1")
                    parts = [p.strip() for p in re.split(r"\n?\s*-{3,}\s*\n?", r.translated_text or "")]
                    parts = [p for p in parts if p != ""]
                    if len(parts) == len(chunk):
                        got = parts
                    else:  # separator got mangled: translate one by one
                        got = [client.text.translate(input=t, source_language_code="en-IN", target_language_code=lang,
                                                     model="sarvam-translate:v1").translated_text.strip() for t in chunk]
                except Exception:
                    api_failed()
                    got = None
            for src, dst in zip(chunk, got or chunk):
                out[src] = dst
                if got:
                    conn.execute("INSERT OR REPLACE INTO translations(lang, src, dst) VALUES (?,?,?)", (lang, src, dst))
    return [out.get(t, t) for t in texts]


def speak(text: str, lang: str) -> bytes:
    """Bulbul text-to-speech; returns WAV bytes. Raises on failure."""
    import base64
    r = _client().text_to_speech.convert(text=text[:1400], language_code=lang, model="bulbul:v3")
    return base64.b64decode(r.audios[0])
