"""Rule-based fallback for when the Sarvam API is unreachable or out of credits.

Handles the common English/Hinglish shapes ("Rahul ordered 10 bottles ... paid ₹200", "Amit paid ₹50 towards dues",
"Supplier se 24 oil aaya"). It returns the same structure as core.parse_command, so the rest of the app (pricing,
validation, preview, confirm) is unchanged — and the owner still reviews everything before it is saved.
"""
import re

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "ek": 1, "do": 2, "teen": 3,
             "char": 4, "paanch": 5, "das": 10}
STOP = {"he", "she", "they", "i", "the", "a", "an", "and", "aur", "of", "at", "each", "for", "to", "my", "his", "her",
        "bought", "ordered", "wants", "took", "liya", "liye", "li", "ne", "se", "kilo", "kg", "bags", "bag", "packets",
        "packet", "pcs", "pieces", "piece", "units", "unit", "rs", "rupees", "rupay", "rupaye", "inr"}


def _money(text: str):
    """Amount paid now, e.g. 'paid ₹200', 'paid 200 rupees', '50 rupay diye', '₹200 advance'."""
    pats = [r"(?:paid|pays|gave|diye|diya|jama|deposited)\s*(?:rs\.?|₹|inr)?\s*(\d+(?:\.\d+)?)",
            r"(?:rs\.?|₹|inr)\s*(\d+(?:\.\d+)?)\s*(?:in\s+)?(?:advance|paid|diye|diya|jama)",
            r"(\d+(?:\.\d+)?)\s*(?:rs|rupees|rupay|rupaye|₹)?\s*(?:upi|cash|card)?\s*(?:se|in|by)?\s*(?:diye|diya|jama|advance)"]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return float(m.group(1))
    return None


def parse_offline(text: str, conn, match_product, find_customer) -> dict:
    t = text.strip()
    low = t.lower()
    method = "upi" if re.search(r"\b(upi|gpay|phonepe|paytm)\b", low) else "card" if "card" in low else "cash"

    # customer: a known customer mentioned anywhere, else the first capitalised word that isn't a product
    customer = None
    for r in conn.execute("SELECT name FROM customers"):
        first = r[0].split()[0]
        if re.search(rf"\b{re.escape(first)}\b", t, re.I):
            customer = r[0]
            break
    if not customer:
        m = re.match(r"\s*([A-Z][a-z]+)", t)
        if m and m.group(1).lower() not in ("supplier", "received", "got", "add"):
            customer = m.group(1)

    # items: "<qty> <words…>" up to the next number/punctuation; resolve words against the catalog.
    # Money expressions are removed first so "₹200 in advance" is never read as 200 units of something.
    t_items = re.sub(r"(?:rs\.?|₹|inr)\s*\d+(?:\.\d+)?", " , ", t, flags=re.I)
    t_items = re.sub(r"\b\d+(?:\.\d+)?\s*(?:rs|rupees|rupay|rupaye|rupee)\b", " , ", t_items, flags=re.I)
    t_items = re.sub(r"\b(?:paid|gave|pays)\s+\d+(?:\.\d+)?", " , ", t_items, flags=re.I)
    items = []
    for m in re.finditer(r"\b(\d+|" + "|".join(NUM_WORDS) + r")\s+([^\d,.;₹]+?)(?=\s+(?:at|for|and|aur|@)\b|[,.;₹]|\s\d|$)",
                         t_items, re.I):
        qty = NUM_WORDS.get(m.group(1).lower()) or int(m.group(1))
        words = [w for w in re.findall(r"[\w\-]+", m.group(2)) if w.lower() not in STOP]
        prod = None
        for n in range(len(words), 0, -1):  # longest phrase first, e.g. "basmati rice" before "rice"
            for i in range(0, len(words) - n + 1):
                prod = match_product(" ".join(words[i:i + n]), conn)
                if prod:
                    break
            if prod:
                break
        if words and not re.match(r"(rs|rupees|rupay|₹)", m.group(2).strip(), re.I):
            items.append({"product": prod["name"] if prod else " ".join(words),
                          "quantity": qty, "stated_unit_price": None})
    items = [i for i in items if i["product"]]

    paid = _money(t)
    if re.search(r"\b(supplier|received|restock|aaya|aaye|arrived|delivered)\b", low) and items:
        intent, customer, paid = "restock", None, None
    elif items:
        intent = "sale"
    elif paid:
        intent = "payment"
    else:
        intent = "unknown"
    # a payment amount is not an item ("paid 200 rupees" must not become 200 units of something)
    return {"intent": intent, "customer_name": customer, "items": items, "payment_amount": paid,
            "payment_method": method, "language": "offline rules"}
