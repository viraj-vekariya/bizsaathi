# BizSaathi demo guide

Live: https://bizsaathi-kgp.streamlit.app · Code: https://github.com/viraj-vekariya/bizsaathi

**Before you go on stage**
- Open the live app 5 minutes early so it is awake. Free hosting sleeps when idle, and waking it can take a minute.
- Settings → Business type "Kirana / General store" → tick the confirmation → *Set up shop*. This gives a clean shop: Water Bottle 1L at ₹40, stock 60.
- Make sure all 7 capability toggles are ON and the language is English.
- Laptop sound on. Keep a local copy running (`streamlit run app.py`) as a fallback.

---

## (a) 90-second live demo

| Time | Click / action | Say |
|---|---|---|
| 0:00 | Assistant page, sidebar visible | "This is BizSaathi, an operations assistant for a local shop. A kirana owner records sales in a notebook. Here they just say what happened." |
| 0:08 | Point at the **Capabilities** toggles in the sidebar | "The owner picks what their shop needs: orders, bills, payments, stock, customers, follow-ups, insights. Seven modules, each on or off." |
| 0:15 | Type in the box: *Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance.* → **Understand** | "One sentence. Sarvam-105B pulls out the customer, item, quantity and payment as structured data." |
| 0:25 | Preview appears. Point at the total, payment, balance and stock line | "Before anything is saved, the owner sees exactly what will change: ₹400 order, ₹200 paid, ₹200 outstanding, stock 60 to 50. The price comes from the shop's catalog, not from the AI." |
| 0:38 | **Confirm & save** | "Confirm. Order, bill, payment and stock are written together in one transaction. Either all of it saves or none of it does." |
| 0:43 | Bill expander opens | "Here is the bill." |
| 0:47 | Sidebar → **Dashboard** | "And the dashboard already shows the sale and Rahul's ₹200 due." |
| 0:53 | Switch language to **Hindi** (or Bengali) | "Most shop owners don't run their business in English. The whole interface switches to any of 11 Indian languages using Sarvam Translate." |
| 1:00 | Back to Assistant, run the Rahul sentence again (or a Hindi one), confirm, play the spoken confirmation | "And the confirmation is read out in Hindi with Bulbul, so the owner hears what was saved without reading the screen." |
| 1:12 | Switch **Inventory** OFF in the sidebar, run a sale, show the preview | "If a shop doesn't track stock, turn Inventory off. The preview now says 'Skipped: stock not changed'. A module that is off never runs." |
| 1:22 | Point at the steps strip | "One owner, one task, end to end, in their own language. That's BizSaathi." |
| 1:30 | Stop | |

Notes:
- If time is short, skip the second sale in Hindi and only show the translated UI and spoken confirmation.
- Turn Inventory back ON after the demo so the next judge sees a normal shop.
- Optional 10-second extra, only if asked: open "Safety check: submit the exact same command again" and click *Re-submit same command* to show it is blocked.

---

## (b) 30-second backup (wifi or API down)

| Click / action | Say |
|---|---|
| Assistant → **Manual entry** | "If the network or the AI is down, the shop still works. Manual entry opens the same preview with empty fields." |
| Fill customer *Rahul*, product *Water Bottle 1L*, quantity *10*, paid *200* | "The owner fills it in by hand." |
| Point at the preview: ₹400, ₹200 outstanding, stock 60 → 50 | "Same checks, same numbers: price from the catalog, stock checked, overpayment rejected." |
| **Confirm & save**, show the bill | "Same single transaction, same bill. The AI makes it faster, but the shop never depends on it." |

If the hosted app itself will not load, run the local copy (`streamlit run app.py`). Manual entry works without an API key.

---

## (c) Likely judge questions

**1. What if the AI gets the price or quantity wrong?**
The AI never sets the price. It only extracts who, what, how many and how much was paid. Prices and totals come from the catalog in Python, and the owner sees an editable preview before anything is saved.

**2. What stops a double tap from billing a customer twice?**
Each preview carries a one-time request ID. A second submit with the same ID is refused by the database. You can try it in the app with "Re-submit same command".

**3. How does it handle Indian languages, really?**
The interface is translated into 11 languages with Sarvam Translate, confirmations and payment reminders are spoken with Bulbul v3, and voice input uses Saaras v4 with the shop's product and customer names as key terms. Product matching also uses aliases in Hindi, Hinglish and Bengali. Instruction understanding is strongest in English, Hindi, Hinglish and Bengali, which is what we tested most.

**4. Does it work for shops other than kirana?**
Yes. There are templates for bakery, medical, hardware and stationery shops, plus a custom empty shop, and the catalog is editable. The seven modules can be switched on or off to match how the shop works.

**5. Is this a GST invoice? Does it take payments?**
No to both. The bill is a simple receipt, and BizSaathi records payments the owner received; it does not process payments. GST invoicing would be a next step.

**6. What happens to data on the live link?**
The live link is a shared demo shop on free hosting, so everyone sees the same data, and it resets when the app restarts. A real deployment would give each shop its own database. The API key is kept in a hosting secret and is not in the code.

---

## (d) Submission text

**Name:** BizSaathi

**Campus:** IIT Kharagpur (Viraj Vekariya)

**Description:**
BizSaathi is an AI operations assistant for local shops that works in the owner's language. The owner types or speaks one sentence, such as "Rahul ordered 10 bottles at ₹40 each. He paid ₹200 in advance." Sarvam-105B extracts it as structured data, the owner reviews an editable preview, and on confirmation BizSaathi records the order, bill, payment (₹200 outstanding) and stock update in one database transaction. The AI never sets prices; totals come from the shop's catalog. Unknown products, insufficient stock, overpayment and duplicate submissions are rejected. Seven modules can be switched on or off, and templates cover kirana, bakery, medical, hardware and stationery shops. The full interface works in 11 Indian languages via Sarvam Translate, with Saaras v4 voice input and Bulbul v3 spoken confirmations and payment reminders.

**Links:**
- Live app: https://bizsaathi-kgp.streamlit.app
- GitHub: https://github.com/viraj-vekariya/bizsaathi
