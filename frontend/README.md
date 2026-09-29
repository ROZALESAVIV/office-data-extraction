# Frontend

React + TypeScript (Vite). Two screens: document intake and the review screen.

Hebrew, RTL. The page is RTL by construction — logical CSS properties
throughout, rather than an LTR design mirrored afterwards.

## Running it

The API must be running on port 8000. Vite proxies `/api` to it, so the browser
stays on one origin and the token is never sent cross-site in development.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production bundle
npm run typecheck
```

## Where things are

| Path | What it holds |
|---|---|
| `src/api/types.ts` | Mirrors the backend Pydantic schemas, hand-written and narrow |
| `src/api/client.ts` | The only module that talks to the API |
| `src/lib/hebrew.ts` | **Every string the lawyer reads**, in one file |
| `src/lib/auth.tsx` | Session state and the write-role check |
| `src/styles/tokens.css` | Palette, spacing, type |
| `src/routes/UploadPage.tsx` | Intake screen |
| `src/routes/ReviewPage.tsx` | Review screen |
| `src/components/FieldRow.tsx` | One field: value, provenance, the four decisions |
| `src/components/ConflictDialog.tsx` | What each document said, in resolver order |
| `src/components/ReadinessPanel.tsx` | Blockers and warnings |

## Things that are load-bearing

- **All copy lives in `src/lib/hebrew.ts`.** The firm can review the wording
  without reading a component, and no sentence gets written twice in two
  slightly different ways. Field labels and document-type labels are *not*
  there: they come from the database, already in Hebrew, and the firm owns them.
- **Every field mutation sends `expected_updated_at`.** A 409 means another
  lawyer decided that field while it was on screen; the screen reloads and says
  so rather than retrying over their answer.
- **`case_type` is a dropdown, never a text box.** Every court-field rule
  compares that value exactly, and a near miss would silently stop requiring the
  court fields on a defence case.
- **Latin text inside Hebrew is isolated.** File names use
  `unicode-bidi: plaintext` so a name that mixes scripts is not mangled; case
  numbers and identifiers use `.mono`, which isolates as LTR.
- **The submit button is visible and disabled.** The endpoint does not exist
  yet — the Odcanit contract is still open with the firm. Hiding the last step
  of the flow would be less honest than showing it greyed out with the reason.
