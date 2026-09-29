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

- **The claim amount in a subrogation case.** There is no pleading, and no
  document states it in a form worth trusting. Deliberately left to manual
  entry — this was the firm's decision, not an oversight.
- **The accident narrative** (`גרסאות מטופסי ההודעה`). Free prose, not a value
  anyone can confirm with a click. Deferred to a later version.

## Parties

- **Plaintiffs: up to 2.** The firm chose this limit; more is a future problem.
- **Defendants: up to 3**, in practice some subset of the insured, the driver
  and the insurer — but which subset varies, so the names are extracted from the
  pleading rather than assumed.
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

Still unknown, and still blocking the submission stage: the actual stored
procedure signatures and what Odcanit requires as a minimum to open a case.

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

Found on the real run, not yet fixed:

1. **A plate number picked up an ID number.** `third_party_plate_number` came
   back as `56414501`, which is the insured's ID `056414501` without its
   leading zero. An Israeli plate is 7-8 digits and an ID is 9; they look
   alike. The conflict detector flagged it, but a validation rule would be
   better - a plate must not equal an ID in the same case.
2. **`total_paid_by_insurer` came back as 0.00** at confidence 0.5, probably
   an empty column in a table. A zero amount is suspicious when payment
   documents exist in the case.

## Claim (subrogation) cases are only half mapped

**Verified by analysis, not yet by a real extraction run.** Only a defence case
has been run end to end; the two claim cases in the samples have not.

A claim case can currently reach **27 of 45 fields**. None of the missing ones
is required, and most are missing correctly:

- **Court fields, the case number and the whole deadline chain (9 fields).**
  The case has not been filed yet, so there is no court, no case number and no
  deadline. Empty is the right answer, not missing data.
- **The claim amount.** The firm's decision: no document states it in a form
  worth trusting, so it stays manual.

**But eight party fields are missing for the wrong reason.** In a defence case
the plaintiff's address and phone and the defendants' names all come from the
pleading. A claim case has no pleading, and `subrogation_letter` is mapped only
to the plaintiff's name and company number.

The information exists - it is being extracted under third-party names:

```
third_party_owner_name      -> would be the defendant
third_party_owner_address   -> address for service
third_party_driver_name     -> possibly a second defendant
```

**What is blocked is a legal decision, not an engineering one.** In a
subrogation case:

- Is the plaintiff the insured, or the insurer? Both `insured_name` and
  `plaintiff_1_name` exist; which one carries which?
- Is the defendant the vehicle's owner, the driver, or the third party's
  insurer?

Getting this wrong would open every subrogation case in Odcanit with the wrong
parties, so it must be answered by the firm before the mapping is written.

## Open questions

Tracked in **QUESTIONS.md**, with the assumption each one is currently running
on. Summary:

- The exact Odcanit stored-procedure contract.
- Whether court recess should be modelled in the deadline calculation.
- Three document types the firm judged irrelevant for now: `תביעות-אאה`,
  `גוף-תשובה ממעתיק ת`, `דוח לוי יצחק`.
- **Who the parties are in a subrogation case** (see the section above). Blocks
  eight field mappings and an end-to-end run on a claim case.
- Whether a plate number should be validated against the IDs in the same case;
  one real extraction put an ID into the plate field.
