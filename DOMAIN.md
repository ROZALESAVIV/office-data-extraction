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
`נתקבל` stamp on the pleading. It is often missing or illegible.

**Not modelled:** court recess (פגרת בתי המשפט) and any extension granted. The
computed date is therefore shown marked *computed — verify*, and the lawyer
confirms it like any other field. When anything is unknown the function returns
nothing rather than guessing: a wrong deadline is a missed filing.

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

Of 41 catalogued types, 23 carry no field data: damage photos, driving licences,
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

## Open questions

- The exact Odcanit stored-procedure contract.
- Whether court recess should be modelled in the deadline calculation.
- Three document types the firm judged irrelevant for now: `תביעות-אאה`,
  `גוף-תשובה ממעתיק ת`, `דוח לוי יצחק`.
