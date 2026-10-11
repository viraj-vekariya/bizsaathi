"""Build i18n.json: pre-translated static UI strings for every non-English language.

Collects every string that reaches T() in app.py, translates the missing ones with Sarvam Translate
(core.translate_many, temp SQLite cache), validates, and merges into i18n.json. Rerunnable: only
missing keys (or keys whose value still equals the English source) are translated.

    .venv/bin/python build_i18n.py
"""
import ast
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402

OUT = os.path.join(HERE, "i18n.json")
BRANDS = ["BizSaathi", "Sarvam-105B", "Saaras", "Bulbul", "UPI", "₹"]
# Strings that are legitimately identical in every language (brand-only).
BRAND_ONLY = re.compile(r"^[\s\W\d]*(BizSaathi|Sarvam-105B|Saaras|Bulbul|UPI|₹)?[\s\W\d]*$")


def collect() -> list[str]:
    src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    found: list[str] = []
    # (a) literal T("...") / T('...') args, incl. implicit concatenation of adjacent literals
    lit = r"""(?:[rRuU]?"(?:\\.|[^"\\\n])*"|[rRuU]?'(?:\\.|[^'\\\n])*')"""
    for m in re.finditer(r"\bT\(\s*(" + lit + r"(?:\s*" + lit + r")*)\s*\)", src):
        found.append(ast.literal_eval("(" + m.group(1) + ")"))
    # (g) tuples iterated by T(k) / T(m) etc.: `for k in ("a", "b", ...)` inside a T(...) comprehension
    for m in re.finditer(r"T\((\w+)\)\s*\)?\s*for\s+(\w+)\s+in\s+(\((?:[^()]|\([^()]*\))*\))", src, re.S):
        if m.group(1) == m.group(2):
            try:
                val = ast.literal_eval(m.group(3))
            except Exception:
                continue
            found.extend(v for v in val if isinstance(v, str))
    # (c) PAGES
    pm = re.search(r"^PAGES\s*=\s*(\[.*?\])\s*$", src, re.S | re.M)
    if pm:
        found.extend(p for p, _ in ast.literal_eval(pm.group(1)))
    # (b) modules, (d) sample labels, (e) intents, (f) stock-move reasons
    found += list(core.MODULES)
    found += ["Sale with advance", "Payment against dues", "Not enough stock", "Hinglish", "Hindi", "Bengali"]
    found += ["Sale", "Payment received", "Stock received"]
    found += ["sale", "restock", "manual adjustment"]
    return [s for s in dict.fromkeys(found) if s.strip()]


def brands_ok(src: str, dst: str) -> bool:
    return all(b in dst for b in BRANDS if b in src)


def translate_lang(lang: str, texts: list[str], db: str) -> dict:
    import sqlite3
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False, timeout=60)  # own conn per thread
    out = core.translate_many(texts, lang, conn)
    res = {}
    for s, t in zip(texts, out):
        t = (t or "").strip()
        if not t:
            continue
        if not brands_ok(s, t):  # one more single-string try, else keep source
            t2 = core.translate_many([s + " "], lang, conn)[0].strip()
            t = t2 if t2 and brands_ok(s, t2) else s
        res[s] = t
    conn.close()
    return res


def main():
    keys = collect()
    print(f"collected {len(keys)} strings")
    data = {}
    if os.path.exists(OUT):
        data = json.load(open(OUT, encoding="utf-8"))
    langs = [l for l in core.LANGUAGES if l != "en-IN"]

    tmp = tempfile.mkdtemp(prefix="i18n_")
    core.DB_PATH = os.path.join(tmp, "i18n.db")
    core.init_db(reset=True)

    todo = {}
    for lang in langs:
        have = data.setdefault(lang, {})
        todo[lang] = [k for k in keys if not have.get(k) or (have[k] == k and not BRAND_ONLY.match(k))]
    print("to translate:", {l: len(v) for l, v in todo.items()})

    with ThreadPoolExecutor(max_workers=len(langs)) as ex:
        futs = {l: ex.submit(translate_lang, l, todo[l], core.DB_PATH) for l in langs if todo[l]}
        for l, f in futs.items():
            try:
                data[l].update(f.result())
            except Exception as e:
                print(f"[FAIL] {l}: {e!r}")

    # validate
    ok = True
    for lang in langs:
        d = data[lang]
        missing = [k for k in keys if k not in d]
        empty = [k for k in keys if k in d and not d[k].strip()]
        same = [k for k in keys if d.get(k) == k and not BRAND_ONLY.match(k)]
        badbrand = [k for k in keys if k in d and not brands_ok(k, d[k])]
        if missing or empty or badbrand:
            ok = False
        print(f"{lang}: {len(d)} keys, missing={len(missing)} empty={len(empty)} "
              f"same-as-source={len(same)} brand-dropped={len(badbrand)}"
              + (f"  same: {same[:8]}" if same else ""))
    # don't ship untranslated copies: drop same-as-source (non-brand) so a rerun retries them
    for lang in langs:
        for k in [k for k, v in data[lang].items() if v == k and not BRAND_ONLY.match(k)]:
            del data[lang][k]

    import random
    random.seed(1)
    for lang in ("hi-IN", "bn-IN"):
        print(f"--- spot check {lang}")
        for k in random.sample(keys, min(5, len(keys))):
            print(f"  {k!r} -> {data[lang].get(k)!r}")

    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {OUT} ({'all valid' if ok else 'WITH GAPS - rerun to retry'})")


if __name__ == "__main__":
    main()
