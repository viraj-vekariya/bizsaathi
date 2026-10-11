# BizSaathi

**One configurable AI operations assistant for local shops.** The owner says what happened, in plain English (Hindi, Hinglish and Bengali also work), and BizSaathi turns it into a checked order, bill, payment record and stock update. Nothing is saved until the owner confirms.

> "Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance."
> → Order ₹400 · Bill INV-… · Payment ₹200 · **₹200 outstanding** · Water Bottle stock 60 → 50

## Why it's different
- **One instruction, many workflows.** A single sentence updates orders, invoices, payments and inventory together, in one database transaction.
- **The owner picks the capabilities.** Orders, Invoices, Payments, Inventory, Customers, Follow-ups and Insights can each be switched on or off. A module that's switched off never runs.
- **The AI never handles money.** Sarvam-105B only *extracts* who bought what and how much they paid. Prices, totals, balances and stock are computed in Python from the shop's own catalog.
- **Safe by design.** An editable preview comes first, then confirmation. The app rejects unknown products, insufficient stock, invalid quantities and overpayments. A one-time request ID blocks duplicate submissions, and if anything fails, the whole save is undone.

## Sarvam APIs used
| What | Model |
|---|---|
| Instruction → structured transaction (JSON schema) | **Sarvam-105B** chat completions |
| Voice instructions, with product and customer names as key terms | **Saaras v4** speech-to-text (falls back to v3) |

## Run locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "SARVAM_API_KEY=your_key" > .env
streamlit run app.py
```
Tests: `python test_core.py` (11 offline business-logic checks).

Stack: Python · Streamlit · SQLite · Sarvam AI SDK. The bill is a simple receipt, not a GST tax invoice, and the app doesn't process online payments.
