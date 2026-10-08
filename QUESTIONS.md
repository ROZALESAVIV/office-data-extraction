# Open questions for the firm

Questions that **cannot be answered from the code, the documents, or by
reasoning**. Each one needs a person at the firm — usually the lawyer — to
decide. Until then the code carries an assumption, and that assumption is named
here so nobody mistakes it for a fact.

Answering one means: write the answer in, move the entry to **Answered**, and
update `DOMAIN.md` / `DECISIONS.md` with the reasoning. The question itself
stays in the file; a decision without its question is how the reasoning gets
lost.

Status: 🔴 blocking work · 🟡 an assumption is live in the code · ⚪ can wait

---

## 🔴 1. What does Odcanit actually require, technically, to open a case?

**Why it matters:** blocks the submission service entirely. Narrowed on
2026-09-29 — the *business* minimum is answered (see Answered #2), this is
purely the technical contract.

**Ask:** the exact **stored procedure** signatures for opening an entity and a
case, and whether a cloud backend can reach the on-prem server at all given
what the firm described as no special security on the connection (needs a real
assessment, not an impression).

---

## 🟡 2. The exact claim-amount computation for a subrogation case

**Why it matters:** this field was believed unextractable and left manual; the
firm's 2026-09-29 answer says otherwise, but not precisely enough to build.

**Ask:** is `claim_amount` the **sum** of the insurer's payment breakdown
amount and the insured's loss-confirmation amount, or one or the other
depending on circumstance? When there is no "אישור הפסדים" and the appraiser's
report is used instead, what exactly gets read from it?

**Current state:** not implemented. See DOMAIN.md, "What is NOT extractable."

---

## 🟡 3. May investigation reports be sent to the external AI model at all?

**Why it matters:** every extractable document currently goes to Claude. If
this document type carries a confidentiality obligation that forbids that, it
needs to be excluded, not just handled carefully.

**Ask:** what is the source of the confidentiality obligation on `דוחות חקירה`
(statute, professional ethics rule, or firm policy), and does it mean the
document type must never reach the model, or just that it needs careful
handling once there?

**Current state:** sent to the model like any other extractable type today.
No exclusion built.

---

## 🟡 4. Should `staff` be able to confirm field values?

**Why it matters:** DECISIONS 16 restricts confirming values to
`owner`/`lawyer`. The firm says a clerk does the confirming in practice.

**Ask:** does the clerk who confirms values get the `lawyer` role in the
system, or does `staff` need confirm permission too?

**Current state:** only `owner`/`lawyer` can confirm, edit, or reject a field.

---

## ⚪ 5. Exact spelling of the third main client number

**Why it matters:** low stakes, but a wrong sender name is a wrong Odcanit
prefix later.

**Ask:** confirm the spelling of "האודן" (main case 1555) — came through
garbled in the original answer.

---

## ⚪ 6. Three document types the firm set aside

`תביעות-אאה`, `גוף-תשובה ממעתיק ת`, `דוח לוי יצחק` were judged irrelevant for
now. Not yet re-confirmed in the 2026-09-29 round — still worth a one-line
check, and whether any document type is missing from the catalogue entirely.

---

## Answered

### 1. Who are the parties in a subrogation case? — 2026-09-29

**Plaintiff:** Direct Insurance is `plaintiff_1` — the recurring main client.
When the suit is also brought in the insured's name, the insured becomes
`plaintiff_2`.

**Defendant, in priority order:** if there is no doubt the other side's
insurer covers the accident, the insurer alone is `defendant_1`. If unsure, the
other driver is added. If the driver's details are missing, the vehicle's
owner is added instead. When suing more than one, the order is driver, then
owner, then the insurer last.

**Implemented 2026-09-30** — `plaintiff_1_name` computed from the case's
sender, `plaintiff_2_name`/`defendant_1_name`/`defendant_2_name` mapped to
`subrogation_letter`. See DECISIONS 38, DOMAIN.md "Claim (subrogation) party
mapping." Not yet verified against a real subrogation case's actual documents.

### 2. What does Odcanit require, as a business minimum, to open a case? — 2026-09-29

Almost nothing — only the main client. Odcanit auto-assigns the next sub-case
number under it. "In principle you can always complete almost any field in
Odcanit later." The "required before submission" list is a **firm workflow
standard**, not an Odcanit technical limit. See DECISIONS 29, DOMAIN.md
"Odcanit."

### 3. Which fields must be filled before a case may be submitted? — 2026-09-29

Confirmed: court name through claim amount, all required in a defence case.
Plaintiff name and full details required too, "unless missing from the
material, in which case we try to complete it" manually. `DEFENCE_ONLY_REQUIRED`
in `app/reference/review.py` confirmed correct, including `plaintiff_1_name`.

### 4. What should "rejected" mean to a lawyer? — 2026-09-29

Confirmed: the real workflow is binary — type the correct value, or clear it
and leave it blank until someone knows the answer. No written reason involved.
Matches the existing `edit`/`reject` design; the reason field was removed
(DECISIONS 37).

### 5. Must a lawyer confirm every required field by hand? — 2026-09-29

Confirmed, with one exclusion: every field needs explicit confirmation
**except** the 7 fields from the referral email — those are trusted outright.
A clerk does the confirming, not necessarily a lawyer (see open question #4
above for the permission-model follow-up this raises).

### 6. Should court recess be modelled in the deadline? — 2026-09-29

Not now. Compute ignoring recess; an optional future "flagged with an
asterisk, or which recess was detected" is nice-to-have, not required.

### 7. Should a plate number be validated against IDs in the case? — 2026-09-29

Confirmed safe: "wouldn't hurt at all, such a glitch could indeed happen."
Built as an attention flag, not an auto-correction — see DECISIONS 35.
