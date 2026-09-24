# Decisions

Each entry records what was chosen, **why**, and what was rejected. The reason
is the point: without it, a future change can undo a correct decision because
the code alone never explains itself.

Newest last.

---

## 1. The application connects as a dedicated, weak database role

**Chosen:** `DATABASE_URL` points at `ode_app` — not the table owner, no
`SUPERUSER`, no `BYPASSRLS`. A separate `DATABASE_ADMIN_URL` is used only by
Alembic and the startup sweeper.

**Why:** Postgres skips row-level security entirely for a superuser or a
`BYPASSRLS` role. Supabase's default `postgres` role has `rolbypassrls = true`,
so the policies were written, looked correct, and never ran. Demonstrated on the
live database: with identical policies, `postgres` scoped to a non-existent
tenant saw every tenant's rows; `ode_app` saw none.

**Rejected:** `FORCE ROW LEVEL SECURITY` alone. It closes the plain-owner case
and does nothing against a superuser. It is applied as well, but it is not the
control that matters.

**Guarded by:** `test_app_role_cannot_bypass_rls`.

---

## 2. Tenant context is re-applied on every transaction

**Chosen:** `TenantSession` remembers its tenant and an `after_begin` listener
re-issues `set_config` whenever a transaction opens.

**Why:** the setting is transaction-scoped, so the first `commit()` erases it.
The routers commit and then refresh, which ran the refresh with no tenant at
all.

**Rejected:** calling `set_tenant` again by hand after each commit — it relies
on every future developer remembering.

**Guarded by:** `test_tenant_context_survives_commit`.

---

## 3. Explicit `tenant_id` filters *in addition to* RLS

**Chosen:** every query filters by tenant even though the policy already does.

**Why:** defence in depth. RLS is the enforcement; one misconfigured policy
should not equal a disclosure of privileged material across firms.

**Rejected:** relying on RLS alone — which is exactly the state that produced
the original leak.

---

## 4. Extraction is per document type, not per case

**Chosen:** classify each document, then ask only for the fields mapped to that
type (6–12), never the whole list (42).

**Why:** asking a model for a field that is not in the document invites
invention. A focused prompt is markedly more accurate, and cheaper.

**Rejected:** one prompt with every field against every document.

---

## 5. Lower priority number = more authoritative

**Chosen:** `document_type_fields.priority`, 1 is best.

**Why:** an arbitrary convention, but it must be stated loudly — read backwards
it silently inverts every resolution and nothing visibly breaks.

**Documented in:** the column comment, CLAUDE.md, DOMAIN.md, and the seed file.

---

## 6. A candidates layer between extraction and the answer

**Chosen:** `field_candidates` holds one row per (document, field);
`case_field_values` holds the single resolved answer.

**Why:** several documents answer the same question, sometimes differently. With
one row per field, a later document silently overwrites an earlier one — exactly
the disagreement a lawyer must see. The candidates layer makes conflict
visible and lets the review screen show both sources side by side.

**Rejected:** a JSONB blob of alternatives (not queryable per field, and the
review screen needs per-field status and provenance).

---

## 7. `extracted_value` freezes only once a lawyer has touched it

**Chosen:** it may be updated while `status='pending_review' AND reviewed_at IS
NULL`; after confirm/edit/reject it is permanently frozen, enforced by the
`trg_freeze_extracted_value` trigger.

**Why:** the original rule ("written once, never changed") conflicts with
multiple documents — a better source arriving later must still be able to
correct an untouched field. But once a lawyer has decided, the AI's original
output is evidence of what the machine claimed versus what the human chose.

**Rejected:** enforcing this in the router. A trigger cannot be bypassed by a
careless future endpoint.

**Guarded by:** `tests/test_schema_invariants.py`.

---

## 8. The referral email is parsed with a regex, not a model

**Chosen:** `app/services/referral_email.py`, priority 1 for its seven fields.

**Why:** the insurer's template is fixed. A pattern match is exact, free and
cannot hallucinate. Seven of the most important fields, at zero cost and zero
error rate.

**Failure mode chosen deliberately:** if the template changes the patterns
return nothing, so fields come back **empty rather than wrong**. Silence is a
much safer failure than a plausible wrong answer.

**Guarded by:** `test_referral_emails_all_parse_completely` against all six real
emails.

---

## 9. Image-only documents are skipped — for the right reason

**Chosen:** `document_types.is_extractable = false` for photos, licences,
cheques.

**Why:** they contain **no fields worth extracting**. This is *not* because they
are unreadable — Claude reads scans well, and the 48-page scanned pleading is
both unreadable to a text extractor and the single most valuable document in a
defence case.

**Consequence if confused:** skipping "scanned" documents would discard the
pleading and with it twelve of the most important fields.

---

## 10. Locally extracted PDF text is never sent to the model

**Chosen:** the PDF itself goes to the model as a document block; extracted text
is used **only** to verify that a returned quote appears on the claimed page.

**Why:** Hebrew text layers frequently come back in visual (reversed) order
depending on the producing software. Feeding that to the model degrades results.

---

## 11. The storage key is built from UUIDs only

**Chosen:** `{tenant}/{case}/{document}.{ext}`, validated by regex inside the
storage module. The user's filename is stored for display and never reaches the
storage layer.

**Why:** path traversal becomes impossible by construction rather than by
filtering, which can always be bypassed by an encoding nobody thought of.

**Guarded by:** `test_storage_key_is_uuids_only`.

---

## 12. Upload commits only after the bytes are stored

**Chosen:** `flush()` to get the id, upload to storage, then `commit()`. A
storage failure rolls back; a commit failure deletes the stored object.

**Why:** a row pointing at an object that does not exist is worse than an
error — it looks like a successful upload and fails later, during extraction,
far from the cause.

**Guarded by:** `test_storage_failure_leaves_no_orphan_row`.

---

## 13. Deletion is soft, and the app role has no `DELETE` grant

**Chosen:** `deleted_at` on cases and documents; the stored object is kept. The
database refuses a hard delete to the application role entirely.

**Why:** a case file is evidence. The grant makes it structural rather than a
convention.

---

## 14. Defence deadline: compute, but refuse to guess

**Chosen:** implement the 45/60-day rule, return `None` whenever anything is
unknown, and display the result marked *computed — verify*.

**Why:** the rule ignores court recess and granted extensions, so it cannot be
presented as authoritative. A wrong deadline is a missed filing.

**Rejected:** leaving it out entirely (the firm's lawyer asked for it), and
presenting it as a plain fact (unsafe).

---

## 15. One field list for both case types

**Chosen:** defence and claim cases share all 42 fields; court and claim-amount
fields simply stay empty in claim cases. Per-type requirements move to the
submission gate.

**Why:** the firm's choice, and it keeps one review screen and one mapping. An
empty court field in a claim case is a correct answer, not missing data.

**Rejected:** two separate field lists (most accurate, most work).

---

## 16. Staff may upload; only owner and lawyer may confirm or reclassify

**Chosen:** upload requires only tenant membership. Reclassifying, deleting and
confirming values require `owner`/`lawyer`.

**Why:** uploading is clerical. Deciding what a document *is*, or that a value
is correct, is legal judgment.

**Note:** the router originally had this wrong (blocking staff from uploading);
the documented model was correct and the code was fixed to match.

---

## 17. Classification reads three pages, not one

**Chosen:** `CLASSIFY_PAGES = 3`.

**Why:** found as a live bug on a real file. A 48-page pleading was labelled
`correspondence` at 0.55 confidence and skipped entirely, losing twelve fields -
because page 1 is the court's case-opening confirmation, not the pleading. The
document's real heading is on page 2. Reading three pages fixed it outright:
`statement_of_claim` at 0.97.

**Cost:** two extra pages on the cheapest call in the pipeline.

---

## 18. Long documents get a navigation pass before extraction

**Chosen:** over 8 pages, one cheap low-effort call (`locate_content`) finds the
page range holding the document's own content; extraction runs only on that.

**Why:** a pleading bundle is 3-5 pages of claim followed by 40+ pages of
exhibits that already exist in the case file separately. On the real 48-page
file this cut extraction from 48 pages to 5 - and, more importantly, stopped the
model reading an appraiser's report full of amounts while being asked for the
amount claimed.

**When unsure it widens, not narrows:** below the confidence threshold it falls
back to a capped prefix. Cutting off real content loses fields; reading two
extra pages costs a fraction of a cent.

**Guarded by:** `test_long_documents_are_navigated_then_narrowed`,
`test_unsure_navigation_falls_back_to_a_capped_prefix`.

---

## 19. A hard page cap, independent of navigation

**Chosen:** `MAX_EXTRACT_PAGES = 40`, applied even when navigation is confident.

**Why:** one real sample is a 186-page PDF of damage photographs. A single
misclassification of a file that size is $1.67 spent on pictures of a bumper.
The cap makes the worst case bounded rather than trusting two judgement calls
in a row.

---

## 20. Some fields always need a lawyer, whatever the confidence

**Chosen:** `case_fields.always_needs_review`, set on `court_procedure_type`,
`claim_amount`, `service_date`, `court_filing_date`, `defence_days` and
`defence_deadline`.

**Why:** these feed the filing-deadline calculation. A wrong deadline is a
missed filing, not a correctable mistake, and no confidence score is high enough
to skip a human on that. A column rather than a hard-coded list because the firm
expects to relax it once extraction has been measured in practice.

---

## 21. Near-duplicate document types are a bug, not a nicety

**Chosen:** merged `insurance_history` and `past_claims_status` into
`claims_status`; gave `repair_invoice` the field mapping its `is_extractable`
flag already implied.

**Why:** the classifier was splitting between two names for the same document
and half those extractions were lost. A type that is extractable but has no
fields mapped is a contradiction that costs a classification call and then
silently skips.

**Guarded by:** `test_no_extractable_type_is_left_with_nothing_to_extract`,
`test_document_type_keys_are_unique_in_meaning`.

---

## 22. The procedure type is matched as a token, never a substring

**Chosen:** strip punctuation, compare whole tokens against a set.

**Why:** `"תא" in 'תא"מ'` is true, so a fast-track claim matched the regular
track and got 60 days instead of 45. The failure was silent and in the
dangerous direction - a lawyer believing they had fifteen more days than they
did.

**Guarded by:** `test_fast_track_is_not_mistaken_for_regular`, plus every real
spelling seen on a document.

---

## 23. The deadline prefers what is written over what is derived

**Chosen, in order:** service date + days stated in the summons; then service
date + days derived from procedure type or amount; then, with no service date,
the court's filing date + days; otherwise nothing.

**Why:** the `נתקבל` stamp is often simply not there. Counting from the filing
date lands earlier than the true deadline - the safe direction - and the result
carries lower confidence to mark it as an assumption.

**Never:** a computed deadline presented as a fact. It ignores court recess and
granted extensions, so it is always shown as *computed - verify*.
