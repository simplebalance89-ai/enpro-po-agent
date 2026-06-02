# EnPro PO Agent — User Guide for Brittany

**Hi Brittany!** This guide is written just for you. No tech jargon. Just "here's what to click."

---

## What This Tool Does

Purchase Orders (POs) come into EnPro from customers via email. This tool:
1. Reads the email and attachment automatically
2. Figures out which customer it's from
3. Matches the parts they ordered to our P21 item numbers
4. Gives the PO a color: **Green**, **Yellow**, or **Red**
5. Lets you review and approve the ones that need eyes on them

**Green = you're done. Yellow = quick check. Red = needs fixing.**

---

## Getting Started

### 1. Open the Tool
Go to: `http://localhost:8000` (local) or the URL your IT team gives you.

You'll see a dark screen with tabs at the top.

### 2. Log In as Admin (if you need admin tabs)
- Click **Operator** in the top-right corner
- Enter the admin passphrase (ask IT)
- Now you can see: Crosswalk, CISM Schema, Pipeline, Outbound Sync

**For daily PO review, you don't need admin mode.**

---

## The Main Screen: Review Queue

### Left Side — The List of POs

```
┌─ Needs Review (3) ─┐
│ • PO 4098053       │  ← Red dot, "customer unmapped"
│ • PO 4500867075    │  ← Yellow dot, "1 unmapped item"
├─ Ready to Approve ─┤
│ • PO 4500819454    │  ← Green dot, all good
│ • PO 4500822311    │  ← Green dot
└────────────────────┘
```

**Filter buttons at the top:** All / Green / Yellow / Red — click to show only those.

**Colors mean:**
| Color | What It Means | What You Do |
|-------|--------------|-------------|
| 🟢 Green | Customer matched, all items matched, confidence is high | Nothing! It auto-approves. Or click **Bulk Approve Greens** |
| 🟡 Yellow | Customer matched, but one or more items need checking | Click it, review, approve or edit |
| 🔴 Red | Customer not matched, or major issues | Click it, use **Edit PO** to fix the mapping, then approve |

### Right Side — PO Details

When you click a PO on the left, the right panel fills with:
- **PO number** and confidence badge
- **Customer name** and match score
- **Ship-to address**
- **Line items** with match scores

**Buttons:**
| Button | When to Use |
|--------|-------------|
| **Edit PO** | Customer is wrong, or items are wrong, or quantities need changing |
| **Approve** | Everything looks correct — generates CISM file |
| **Reject** | This PO is junk, duplicate, or unfixable |

---

## How to Edit a PO

Click **Edit PO**. You'll see:

### Step 1: Fix the Customer
- In the **Customer Search** box, type part of the customer name
- A dropdown appears with matches
- Click the right one
- It auto-fills: Customer ID, Customer Name, Ship-To

### Step 2: Fix the Items
- For each line, type in the **Item Search** box
- It shows parts this customer has ordered before
- Click the right one
- It auto-fills: Description, Quantity, Price, UOM

### Step 3: Adjust if Needed
- Change quantities or prices directly in the input boxes
- Add notes in the **Notes** box

### Step 4: Save
- Click **Save Changes**
- The system re-scores the PO
- If it turns **Green**, it auto-approves!
- If still **Yellow/Red**, keep editing or approve manually

**Keyboard shortcuts:**
- **Enter** = Approve the selected PO (when you're not typing in a box)
- **Escape** = Cancel Edit and go back to the detail view

---

## How to Approve (the Easy Way)

### Single PO:
1. Click the PO in the left list
2. Review the details on the right
3. Click **Approve**
4. Done! A toast notification confirms it.

### Bulk Approve (all greens at once):
1. Make sure the **Green** filter is active
2. Click **Bulk Approve Greens** at the top
3. All green POs are approved in one shot

---

## What Happens After I Approve?

Behind the scenes:
1. A **CISM SO file** is generated (CSV format for P21)
2. The PO is added to the **CISM Batch**
3. The system **learns** from what you approved (so next time it matches faster)

You don't need to do anything else. P21 will pick up the batch file.

---

## CISM Batch Tab

This shows all the POs you've approved, ready for P21 import.

- **Counter:** "5 POs in batch, 12 line items"
- **Download Header CSV** — download the header file
- **Download Lines CSV** — download the line items file
- **Clear Batch** — archives the old batch and starts fresh

**When to use:** When you have a batch ready, download both CSVs and give them to IT for P21 import.

---

## Processed Tab

Shows every PO that has ever been approved, with:
- PO number
- Import set number (for P21 tracking)
- Download links for per-PO CISM files

Use this if you need to re-download a file or check history.

---

## P21 Payloads Tab

For advanced use — lets you:
- Select multiple POs with checkboxes
- Run **Batch Preflight** to validate them
- Download a **ZIP** with all P21 JSON payloads

IT might ask you for these files.

---

## If Something Goes Wrong

| Problem | What to Do |
|---------|-----------|
| "No customers found" when searching | Type at least 2 letters. If still nothing, the crosswalks might be empty — tell IT. |
| "No items found" when searching | Make sure a customer is selected first. Items are filtered to that customer's history. |
| PO stays Red after editing | The customer or items still aren't matching well. Check the ship-to address and part numbers. |
| "Disk usage: 85%" banner appears | Tell IT — the server is running out of space. |
| Page won't load | Check if the server is running (ask IT). Try refreshing. |
| I approved by accident | There is no "un-approve" button yet. Tell IT — they can fix it in P21 directly. |

---

## Tips for Speed

1. **Bulk approve greens first thing** — clears the easy ones instantly
2. **Use keyboard shortcuts** — Enter to approve, Escape to go back
3. **Trust the suggestions** — the system learns from every approval
4. **Keep notes** — the Notes box is saved with the PO for future reference

---

## Need Help?

**For this tool:** Ask Peter or check the Pipeline tab (Tab 8) for a visual walkthrough.

**For P21 issues:** Contact EnPro IT / P21 administrator.

**For credentials/login issues:** Contact EnPro IT.

---

*You're doing great. The system gets smarter every time you approve a PO.*
