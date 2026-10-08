# Domain knowledge

Everything here was learned from the firm and from six real case files. None of
it can be derived from the code, and all of it changes how the code should be
written. Read this before making product decisions.

## What the firm actually does

Motor insurance work referred by **Direct Insurance (ביטוח ישיר)**. Not general
civil litigation. The firm is paid by the insurer, and represents the insured.

Every case arrives the same way: an email from the insurer, plus a pile of
documents the lawyer downloads from the insurer's portal (**"הכספת"**). The
email and the documents arrive separately and are uploaded together.

## Two case types — and the email says which

The referral email states the instruction verbatim:

| Email says | Meaning | Who sues whom |
|---|---|---|
| `להגשת הגנה` | **Defence.** Someone sued our insured. | The other side is the plaintiff; our insured is a defendant. |
| `להגשת תביעה` | **Claim (subrogation, שיבוב).** We are going after the other side. | Our insured / the insurer is the plaintiff. |

This single word decides which fields even exist:

- **Defence** cases have a pleading (`כתב תביעה`) already filed in court. Court
  name, city, procedure type, plaintiff details and the claim amount all come
  from it.
- **Claim** cases have not been filed yet. There is no court, no case number and
  no pleading. Those fields stay empty **by design** — an empty court field in a
  claim case is correct, not missing data.

Both types share one field list. Requirements differ by type, enforced at the
submission gate rather than by a flag on the field.

Of six sample cases: four defence, two claim.

## The referral email is the most reliable source in the file

Direct Insurance uses a fixed template. Seven fields come out by pattern match —
no model, no OCR, no ambiguity, no cost:

```
מספר תביעה   מספר פוליסה   מספר רישוי   תאריך אירוע
שם מבוטחנו   שם צד ג'      + the defence/claim instruction
```

All seven parsed correctly from all six sample emails. This is why
`referral_email` holds priority 1 in `document_type_fields`: nothing should ever
outrank it.

**The email always arrives** (confirmed by the firm). If it is missing from an
upload, the lawyer forgot it — that is worth saying out loud in the UI, because
without it seven certain fields become guesses.

If the insurer ever changes the template, the patterns stop matching and the
fields come back **empty rather than wrong**. `test_referral_emails_all_parse_completely`
fails the moment that happens.

## Document authority — who to believe

Established with the firm's lawyer:

| Field | Authoritative source | Why |
|---|---|---|
| Third-party owner details | **`נתוני משרד הרישוי`** (priority 5) | Official registry query. |
| …same, fallback | `רשיון רכב` (priority 20) | A photographed licence can be out of date. |
| Court, parties, claim amount | `כתב תביעה` (priority 10) | The pleading is what was actually filed. |
| Insured identity | `מפרט פוליסה` (priority 10) | |
| Driver, third-party details | `טופס דיווח דיגיטלי` (priority 10) | The insured's own accident report. |
| Amounts paid, deductibles | `פרוט תשלומים לתובע` (priority 10) | |

**Lower priority number wins.** This is stated in three places because reading
it backwards would silently invert every resolution.

## How a pleading bundle is built

Confirmed on three real defence files, and stated by the firm's lawyer:

```
[ אישור פתיחת תיק ]   court case-opening confirmation - sometimes first,
                      sometimes last, sometimes absent entirely
  3-5 pages           the pleading itself (כתב תביעה)
  the rest            נספחים - exhibits
```

The exhibits are **copies of documents already in the case file separately** -
the accident report, the appraiser's report, the payment schedule, photographs.
Reading them again finds nothing new, costs money, and invites the model to
pull a value out of the wrong document (an appraiser's report is full of
amounts that are not the amount claimed).

Real proportions: one 48-page file was 5 pages of content and 43 of exhibits.
Another was 30 pages with 2 of content. **90% of a pleading bundle is noise.**

This is why `extraction.locate_content()` exists: for anything over 8 pages, one
cheap call finds where the content ends before extraction begins.

The case-opening confirmation is **part of the content**, not an exhibit - it
carries the court case number and the filing date, and nothing else does.

## The filing deadline

Asked for by the firm; the rule is in `app/reference/deadlines.py`.

```
תאד"מ  / סדר דין מהיר  (claims up to  85,000 ILS) -> 45 days from service
ת.א.   / סדר דין רגיל  (claims above 85,000 ILS) -> 60 days from service
```

These are two views of one rule: the amount determines the track, the track
determines the days. **The procedure type as actually filed wins over the
amount** — the court has already assigned the track.

The clock starts at **service on the defendant**, which appears as a rubber
`נתקבל` stamp on the pleading.

**That stamp is frequently absent.** It was not on the sample pleading at all -
there is a blank rectangle where it would go. The firm's rule when it is
missing: count from the court's **filing date** instead, taken from the
case-opening confirmation. That lands earlier than the true deadline, which is
the direction of caution, and the field is given lower confidence to say so.

**The day count can also be read rather than derived.** The summons (הזמנה
לדין) on page 2 of the pleading states it outright - "45 days to file a
defence". Reading the number is safer than inferring it from the procedure
type, so `defence_days` is extracted and takes precedence.

**Spelling trap, found as a live bug.** The procedure type appears as `תא"מ`,
`תאד"מ`, `ת.א.` and `ת"א`. Matching on substrings is unsafe: `תא` is contained
in `תא"מ`, so a fast-track claim was being given 60 days instead of 45 -
fifteen days the lawyer does not have, which is the dangerous direction. The
code now strips punctuation and compares whole tokens.

**Not modelled:** court recess (פגרת בתי המשפט) and any extension granted. The
computed date is therefore shown marked *computed — verify*, and the lawyer
confirms it like any other field. When anything is unknown the function returns
nothing rather than guessing: a wrong deadline is a missed filing.

## Court identifiers are two fields, not one

The pleading heading reads `תאד"מ 13051-05-26`. That is **two separate facts**
going to **two different Odcanit fields**:

| Part | Field | Odcanit field |
|---|---|---|
| `תאד"מ` | `court_procedure_type` | `הליך` |
| `13051-05-26` | `court_case_number` | `תיק בימ"ש` |

Only two procedure types matter to this firm: `תאד"מ` and `ת.א.`.

## The claim amount

The pleading states it twice: as a total near the top (`סכום התביעה`) and
itemised near the end (damage / fees / interest). **The total is what matters** -
12,279 rather than the 10,962 principal. The itemisation is not needed.

## What is NOT extractable

- **The claim amount in a subrogation case.** Previously: no document states it
  reliably, deliberately manual. **Revised (2026-09-29):** the firm actually
  extracts it from two documents in Direct Insurance cases - the insurer's own
  payment breakdown (`payments_to_claimant`, already mapped) for the insurer's
  portion, plus a document called **"אישור הפסדים"** (loss confirmation, not
  yet in the document catalogue) for the insured's portion. When no loss
  confirmation exists, the insured's loss can usually be derived by
  cross-referencing the appraiser's report, sometimes also the policy. **Not
  yet implemented** - the exact computation (is it a sum of the two amounts,
  or one or the other depending on circumstance?) needs one more round with
  the firm before this is built; building it from this description alone would
  be guessing.
- **The accident narrative** (`גרסאות מטופסי ההודעה`). Free prose, not a value
  anyone can confirm with a click. Deferred to a later version.

## Parties

- **Plaintiffs: up to 2.** Confirmed still sufficient (2026-09-29).
- **Defendants: up to 3**, confirmed still enough for now, but the firm would
  like room for **4-5** - chain collisions can mean suing every vehicle behind
  our own. Not urgent, but a real future schema change (`defendant_4_name`,
  `defendant_5_name`), not an edge case to dismiss.
- The insured is frequently a **company** (e.g. `אפי ושות 0202 בע"מ`), in which
  case the driver is necessarily someone else. `insured_name` and
  `our_driver_name` are separate fields for this reason.

## Most documents are photographs

Of 39 catalogued types, 22 carry no field data: damage photos, driving licences,
cheques, police confirmations, appraiser photos. They are stored and forwarded
to Odcanit but never sent to the model.

**They are skipped because they contain no fields, not because they are
unreadable.** Claude reads scans perfectly well — the 48-page scanned pleading is
both unreadable to a text extractor and essential to us.

Filtering them roughly halves the per-case cost (~$2.50 -> ~$1.10).

## The catalogue will never be complete

Distinct document names as sample cases arrived:

```
1 case: 18    2: 23    3: 35    4: 47    5: 47    6: 57
```

Case 5 added nothing; case 6 added ten. **40% of types appeared in exactly one
case.** An unknown document is therefore the normal state, not an edge case, and
the design must degrade gracefully rather than treat it as an error.

Filenames are also unreliable: `מפרט פוליסה` and `מפרט לפוליסה` are the same
document. That is why the filename is only a hint and the model decides.

## Odcanit

Not a REST API — direct Microsoft SQL Server access (views to read, stored
procedures to write). See CLAUDE.md for the technical consequences.

**Client model, confirmed by the firm:** the client is the insurance company or
agency, each of which already has a **main case** in Odcanit (Direct Insurance
might be 555, an agency 112 — illustrative numbers). A new referral is opened as
a **sub-case under that main case**.

This means we do **not** create a client entity per case — it already exists.
That is what the existing `senders` table with `odcanit_prefix` represents.

**Main client numbers, confirmed by the firm (2026-09-29):**

```
Direct Insurance (ביטוח ישיר)  555
Lubit (לוביט)                 1152
"האודן"                       1555   — spelling unconfirmed, verify
Reli Insurance (רלי ביטוחים)  1143
```

**Confirmed: Odcanit requires almost nothing to open a case.** Only the main
client (e.g. Direct Insurance) — write the client name or main-folder number,
and Odcanit auto-assigns the next sub-case number under it (main folder `555`,
last case `555/100` → the next is automatically `555/101`). "In principle you
can always complete almost any field in Odcanit later." This means our
"required before submission" list is a **firm workflow standard, not an
Odcanit technical limit** — see DECISIONS 29.

**Duplicate detection is by Odcanit's own case number**, not by us: you
literally cannot reopen `555/100` a second time, because that number is the
identity check. Nothing on our side needs its own dedup logic against Odcanit.

**Documents go into Odcanit too**, into a documents tab that records the
modification date and the file name. The firm does not see a need to keep
documents in our own storage once a case is submitted — "all documents stay in
Odcanit" — which may simplify retention: a deliberate cleanup policy after
submission is worth designing, rather than storing forever by default. Not yet
built.

**Server location, confirmed:** on-prem, physically in the firm's office. An
external backup of all Odcanit data exists. The firm believes outside
connections are possible with no special security in place — this needs a real
security assessment before anything connects to it, not just the firm's own
impression. Technical contact: Ofer (the firm's own IT person).

**Still genuinely unknown, and still blocking the submission stage:** the
actual stored-procedure signatures for opening an entity and a case.

## Measured, not estimated

Full extraction of one real 17-document case, end to end:

| | |
|---|---|
| Cost | **$0.30** |
| Time | ~200 seconds |
| Fields filled | 33 of 45 |
| Candidates | 61 |
| Conflicts surfaced | 7 |

Every field left empty was either a second plaintiff that does not exist or a
second-degree amount. No required field was missed.

Opus 5 is $5 per million input tokens and $25 per million output. The cost
driver is **pages sent**, not model tier - type filtering and content
navigation together cut it by roughly 80%.

## Two known extraction errors

Found on the real run. Both now flagged for a human on the review screen
(DECISIONS 35) - the value is never silently corrected or dropped, only
marked for a second look:

1. **A plate number picked up an ID number.** `third_party_plate_number` came
   back as `56414501`, which is the insured's ID `056414501` without its
   leading zero. An Israeli plate is 7-8 digits and an ID is 9; they look
   alike. Confirmed by the firm as worth flagging: "such a glitch could
   indeed happen."
2. **`total_paid_by_insurer` came back as 0.00** at confidence 0.5, probably
   an empty column in a table. Confirmed by the firm: a zero amount is
   "necessarily a mistake" in a claim case, "a sign of an error" in a defence
   case - flagged unconditionally, not only when a payment document exists.

## Claim (subrogation) party mapping

**Legal question answered and mapping written (2026-09-29); not yet verified
against a real extraction run.** Only a defence case has been run end to end
so far - the two claim cases in the samples have not.

- **Plaintiff:** `plaintiff_1_name` is the referring insurer - computed
  directly from the case's sender (`cases.sender_id`), never extracted from a
  document. It is known with certainty the moment the case is created, so
  re-deriving it by reading a letter would only add risk. See
  `extraction._populate_subrogation_plaintiff`, DECISIONS 38. When the suit is
  also brought in the insured's own name, the insured is `plaintiff_2` -
  extracted from `subrogation_letter`, since that is conditional on the
  letter's actual content, not a fixed fact.
- **Defendant, in priority order:** if there is no doubt the other side's
  insurer covers the accident, that insurer alone is the defendant. If it is
  not clear the other insurer covers it, the other driver is added too. If the
  driver's details are not available, the vehicle's owner is added instead.
  When suing more than one, the order is **driver, then owner, then the
  insurer last**. `defendant_1_name`/`defendant_2_name` are mapped to
  `subrogation_letter`, read as whoever the letter is actually addressed to -
  the firm's own choice already reflected in the letter's text. **Not
  automated as a rule**: which of these paths applies depends on the firm's
  own judgement about insurance coverage, which no document states as a fact
  - see DECISIONS 38 for why that was deliberately left to the letter's own
  wording rather than guessed at.
- Confirmed separately: each main case is one accident. Our own vehicle's
  plate is constant within one case; the other side can have several vehicles
  (a chain collision), which can produce one main case plus additional
  sub-cases, one per claimant, each naming a different vehicle on the other
  side.

Still to do: run this against a real subrogation case end to end and see what
the model actually returns for `defendant_1_name`/`defendant_2_name` from a
real demand letter - the mapping is written, but untested against a real
document.

## Open questions

Tracked in **QUESTIONS.md**, with the assumption each one is currently running
on. Answered as of 2026-09-29: who the parties are in a subrogation case,
required fields before submission, the reject/clear workflow, court-recess
handling (skip it for now), the filing-date deadline fallback, the plate/ID
validation, party counts, case volume and SLA. Still open:

- The exact Odcanit stored-procedure contract - the one remaining hard blocker
  on the submission stage.
- The exact claim-amount computation for a subrogation case (see "What is NOT
  extractable" above) - description given, not yet precise enough to build.
- Whether investigation reports (`דוחות חקירה`) may be sent to the model at
  all - the firm flagged "a certain confidentiality obligation" without
  specifying its source or scope.
- Three document types the firm judged irrelevant for now: `תביעות-אאה`,
  `גוף-תשובה ממעתיק ת`, `דוח לוי יצחק` - not yet re-confirmed.
- Exact spelling of the third main client number ("האודן", 1555) - came through
  garbled in the original answer.
- Whether the `staff` role should be able to confirm field values - the firm
  said a clerk does the confirming, and today only `owner`/`lawyer` can.
