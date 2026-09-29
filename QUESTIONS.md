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

## 🔴 1. Who are the parties in a subrogation case?

**Why it matters:** blocks eight field mappings and the whole submission of a
claim case. Getting it wrong would open every subrogation case in Odcanit with
the wrong parties.

**Ask:**
- In a claim (`להגשת תביעה`) case, is the **plaintiff** our insured, or the
  insurance company? Both `insured_name` and `plaintiff_1_name` exist — which
  one carries which?
- Is the **defendant** the third party's vehicle owner, the driver, or the
  third party's insurer? If more than one, in what order?

**Current state:** the information is already extracted, under third-party
names (`third_party_owner_name`, `third_party_owner_address`,
`third_party_driver_name`). Nothing maps it to the party fields, so it is not
lost, just not placed.

---

## 🔴 2. What does Odcanit actually require to open a case?

**Why it matters:** blocks the submission service entirely.

**Ask:**
- The exact **stored procedure** signatures for opening an entity and a case.
- Which fields are the **minimum** Odcanit will accept, and which it rejects.
- Where does the SQL Server live, and can a cloud backend reach it at all? (If
  not, the fallback is a file export.)

---

## 🟡 3. Which fields must be filled before a case may be submitted?

**Why it matters:** the list is currently **my inference from DOMAIN.md, not the
firm's answer.** Too strict and lawyers get stuck on fields nobody needs; too
loose and incomplete cases reach Odcanit.

**Ask:**
- In a **defence** case, must all of these be filled?
  `court_name`, `court_city`, `court_procedure_type`, `court_case_number`,
  `claim_amount`, `plaintiff_1_name`
- **`plaintiff_1_name` especially** — I assumed a defence case cannot be opened
  without naming who sued. Is that right?
- Is there anything in the shared required list that is in practice *optional*?

**Assumption live in the code:** `app/reference/review.DEFENCE_ONLY_REQUIRED`,
recorded as DECISIONS 29.

---

## 🟡 4. What should "rejected" mean to a lawyer?

**Why it matters:** decides whether a rejected required field still blocks
submission.

**Ask:** when a lawyer marks a field as wrong, do they mean
- *"the value is wrong and I have no replacement"* — the field is still needed,
  the case is not ready; or
- *"this field does not apply to this case"* — the case can go ahead without it?

**Assumption live in the code:** the first. `rejected` blocks. Recorded as
DECISIONS 27, decided for consistency and **not** stated by the lawyer.

---

## 🟡 5. Must a lawyer confirm every required field by hand?

**Why it matters:** it is 13–19 clicks per case. Correct in principle — a value
no human looked at is not a decision — but the cost is real and falls on every
case.

**Ask:**
- Is clicking through every required field acceptable, or should a
  high-confidence value count as confirmed unless the lawyer says otherwise?
- The bulk-confirm button never touches conflicts or the deadline fields. Is
  that the right line?

**Assumption live in the code:** every required field must be decided
explicitly. Worth re-asking after the first real case is reviewed end to end.

---

## ⚪ 6. Should court recess (פגרת בתי המשפט) be modelled in the deadline?

**Why it matters:** the computed deadline is already shown as *computed —
verify* precisely because recess and granted extensions are not modelled.
Modelling recess would make it more accurate but still not authoritative.

**Ask:** is it worth it, or does the lawyer check the calendar anyway?

---

## ⚪ 7. Should a plate number be validated against the ID numbers in the case?

**Why it matters:** one real extraction put the insured's ID `056414501` into
`third_party_plate_number` as `56414501`. An Israeli plate is 7–8 digits, an ID
is 9; they look alike. The conflict detector caught it, but a rule would be
better.

**Ask:** confirm the rule — a plate number must never equal an ID appearing
elsewhere in the same case. Any exceptions?

---

## ⚪ 8. Three document types the firm set aside

`תביעות-אאה`, `גוף-תשובה ממעתיק ת`, `דוח לוי יצחק` were judged irrelevant for
now. Confirm they stay out, or say what they are for.

---

## Answered

*(nothing yet)*
