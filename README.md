# BizSaathi

**Tell your shop's books what happened, in your own language. BizSaathi records the order, bill, payment and stock in one confirmed step.**

**Live app:** https://bizsaathi-kgp.streamlit.app
**Code:** https://github.com/viraj-vekariya/bizsaathi
Built by Viraj Vekariya, IIT Kharagpur, for Sarvam Campus x IIT Kharagpur '26.

BizSaathi is a configurable AI operations assistant for small local shops: kirana stores, bakeries, medical stores, hardware shops, stationers, or any shop with its own catalog. The owner types or speaks one sentence. Sarvam-105B reads it, BizSaathi checks it against the shop's catalog and stock, the owner reviews and confirms, and everything is saved together.

## The one flow

One user (the shop owner), one task (record what just happened at the counter), end to end.

1. **Say it.** Type or speak: *"Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance."*
2. **AI extracts it.** Sarvam-105B returns structured JSON: customer, items, quantities, amount paid. It does not set prices.
3. **Review.** An editable preview shows exactly what will change: order ₹400, bill, payment ₹200, **₹200 outstanding**, Water Bottle stock 60 → 50. Anything that a disabled module would have done is listed as "Skipped".
4. **Confirm.** The owner clicks *Confirm & save*. Order, bill, payment and stock update are written in **one SQLite transaction**. If any part fails, nothing is saved.
5. **See it.** The bill is shown immediately, and the dashboard, dues and inventory reflect the new numbers.

If the AI or the network is unavailable, **Manual entry** opens the same preview with empty fields, and the same checks apply.

## Built for Bharat

- **Full UI in 11 languages:** English, Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi and Odia, translated with Sarvam Translate.
- **Spoken confirmations** in the owner's chosen language, using Bulbul v3 text-to-speech.
- **Voice input** with Saaras v4 speech-to-text. The shop's product and customer names are passed as key terms, so "Parle-G" or "Sunita Devi" come through correctly.
- **Mixed-language instructions** work: English, Hindi, Hinglish and Bengali product names are matched through per-product aliases (for example "paani ki bottle", "doodh", "দুধ").
- **Payment reminders** in the chosen language, with a *Listen* button to hear them read aloud.

## Sarvam models used

| Model | What it does in BizSaathi |
|---|---|
| **Sarvam-105B** (chat completions, JSON schema) | Turns the owner's sentence into a structured transaction: intent, customer, items, quantities, amount paid |
| **Saaras v4** (speech-to-text) | Transcribes spoken instructions, with catalog and customer names as key terms (falls back to v3) |
| **Sarvam Translate** (`sarvam-translate:v1`) | Translates the whole interface and payment reminders into the owner's language |
| **Bulbul v3** (text-to-speech) | Reads confirmations and payment reminders aloud in the owner's language |

## Safety guarantees

- **The AI never sets prices.** Prices, totals, balances and stock are computed in Python from the shop's own catalog. The model only extracts who, what, how many and how much was paid.
- **Nothing is saved without confirmation.** Every instruction goes through an editable preview first.
- **Checks before saving:** unknown products, insufficient stock, invalid quantities and overpayment (paying more than the bill) are rejected with a clear error, and the Confirm button stays disabled.
- **No double billing.** Each preview carries a one-time request ID. Submitting the same preview twice is refused by the database.
- **All or nothing.** Order, bill, payment and stock are written in a single transaction. A failure rolls everything back.
- **Keys stay private.** The Sarvam API key is read from the `SARVAM_API_KEY` environment variable (`.env` locally, a hosting secret in production). `.env` is git-ignored and the key is never in the repository.

## Capabilities

Seven modules, each switched on or off from the sidebar. A module that is off never runs, and the preview says what was skipped.

| Module | What it does |
|---|---|
| Orders | Records sales and keeps the order history |
| Invoices | Generates a bill for each sale |
| Payments | Records advance and later payments, tracks outstanding dues |
| Inventory | Deducts stock on sale, adds on restock, flags low stock |
| Customer Management | Customer list, contact numbers and dues |
| Follow-ups | Customers with pending dues and payment reminders |
| Business Insights | Sales and product summaries |

**Business templates:** Kirana / General store, Bakery & sweets, Medical store, Hardware & paint, Stationery, or Custom (start empty). The catalog is editable, so the same app works for any shop.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo "SARVAM_API_KEY=your_key_here" > .env
streamlit run app.py
```

Without a key, the app still runs and Manual entry works; AI extraction, voice, translation and speech need the key.

## Tests

```bash
python test_core.py
```

11 offline checks of the business logic (no API calls): the Rahul example end to end, duplicate submission, insufficient stock, rollback when stock changes between preview and confirm, unknown products and invalid quantities, disabled modules, overpayment, restock, and Hindi/Bengali/Hinglish product matching.

## Honest limits

- The bill is a **simple receipt, not a GST tax invoice**.
- The live demo uses **shared demo data on free hosting**. Anyone using the link sees the same shop, and the data resets when the app restarts.
- **No payment processing.** BizSaathi records payments the owner received; it does not collect money.
- Built for one shop and one owner at a time. There are no user accounts or multi-shop support.
- Translation and speech quality depend on the Sarvam APIs and the network; if they fail, the app falls back to English text and Manual entry.

## Stack

Python, Streamlit, SQLite, Sarvam AI Python SDK.
