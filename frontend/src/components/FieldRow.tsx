import { useState } from "react";
import type { ReviewField } from "../api/types";
import { attention, caseType, fieldStatus, review as t } from "../lib/hebrew";
import { Badge, Confidence, Spinner } from "./ui";

/** Computed, never extracted: the deadline ignores court recess and granted
 *  extensions, so it is always presented as something to verify. */
const COMPUTED_FIELDS = new Set(["defence_deadline"]);
const CASE_TYPE_FIELD = "case_type";

export interface FieldRowProps {
  field: ReviewField;
  mayDecide: boolean;
  busy: boolean;
  onConfirm: (field: ReviewField) => void;
  onEdit: (field: ReviewField, value: string) => void;
  onReject: (field: ReviewField) => void;
  onOpenConflict: (field: ReviewField) => void;
  onOpenDocument: (documentId: string, page: number | null) => void;
}

export default function FieldRow({
  field,
  mayDecide,
  busy,
  onConfirm,
  onEdit,
  onReject,
  onOpenConflict,
  onOpenDocument,
}: FieldRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(field.value ?? "");

  const decided = field.status !== "pending_review";
  const blocking =
    field.required_for_this_case && (!field.value || field.status === "rejected");
  const attentive = field.attention_reasons.length > 0;

  const rowClass =
    "field-row" +
    (blocking
      ? " field-row--blocking"
      : attentive
        ? " field-row--attention"
        : decided
          ? " field-row--decided"
          : "");

  function startEdit() {
    setDraft(field.value ?? "");
    setEditing(true);
  }

  function commitEdit() {
    const value = draft.trim();
    if (!value) return;
    onEdit(field, value);
    setEditing(false);
  }

  return (
    <div className={rowClass}>
      <div className="field-row__label">
        <span className="field-row__label-text">{field.label}</span>
        <span className="field-row__key ltr">{field.field_key}</span>
        <span className="field-row__tags">
          {field.required_for_this_case && <Badge tone="accent">{t.requiredHere}</Badge>}
          {field.always_needs_review && <Badge tone="warn">{t.alwaysNeedsReview}</Badge>}
          {COMPUTED_FIELDS.has(field.field_key) && <Badge tone="warn">{t.computedVerify}</Badge>}
          {decided && (
            <Badge tone={field.status === "rejected" ? "danger" : "ok"}>
              {fieldStatus[field.status]}
            </Badge>
          )}
        </span>
      </div>

      <div className="field-row__value">
        {editing ? (
          <div className="field-row__edit">
            {field.field_key === CASE_TYPE_FIELD ? (
              // Closed choice, not free text: every court-field rule compares
              // this value exactly, and a near miss would silently switch them off.
              <select
                className="select"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                autoFocus
                style={{ width: "auto", minWidth: 180 }}
              >
                <option value="">—</option>
                <option value={caseType.defence}>{caseType.defence}</option>
                <option value={caseType.claim}>{caseType.claim}</option>
              </select>
            ) : (
              <input
                className={
                  field.data_type === "text" ? "input" : "input input--mono"
                }
                value={draft}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitEdit();
                  if (e.key === "Escape") setEditing(false);
                }}
              />
            )}
            <button className="btn btn--primary btn--sm" onClick={commitEdit} disabled={!draft.trim()}>
              {t.saveEdit}
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setEditing(false)}>
              ביטול
            </button>
          </div>
        ) : (
          <>
            <div
              className={
                field.value
                  ? "field-row__value-text"
                  : "field-row__value-text field-row__value-text--empty"
              }
            >
              {field.value ?? t.noValue}
            </div>

            <div className="field-row__source">
              {field.confidence !== null && <Confidence value={field.confidence} />}
              {field.source.file_name ? (
                <button
                  className="btn btn--ghost btn--sm"
                  onClick={() =>
                    field.source.document_id &&
                    onOpenDocument(field.source.document_id, field.source.page)
                  }
                >
                  <span className="bidi-auto">{field.source.file_name}</span>
                  {field.source.page !== null && ` · ${t.page(field.source.page)}`}
                </button>
              ) : (
                field.value && <span className="muted">{t.noSource}</span>
              )}
              {field.candidate_count > 1 && (
                <button
                  className="btn btn--sm"
                  onClick={() => onOpenConflict(field)}
                >
                  {t.candidates} ({field.candidate_count})
                </button>
              )}
            </div>

            {field.attention_reasons.length > 0 && (
              <span className="field-row__tags" style={{ marginBlockStart: 6 }}>
                {field.attention_reasons.map((reasonKey) => (
                  <Badge
                    key={reasonKey}
                    tone={reasonKey === "missing_required" ? "danger" : "warn"}
                  >
                    {attention[reasonKey]}
                  </Badge>
                ))}
              </span>
            )}

            {field.source.snippet && (
              <div className="field-row__snippet">{field.source.snippet}</div>
            )}

          </>
        )}
      </div>

      {mayDecide && !editing && (
        <div className="field-row__actions">
          {busy && <Spinner />}
          {field.value && field.status === "pending_review" && (
            <button
              className="btn btn--ok btn--sm"
              onClick={() => onConfirm(field)}
              disabled={busy}
            >
              {t.confirm}
            </button>
          )}
          <button className="btn btn--sm" onClick={startEdit} disabled={busy}>
            {t.edit}
          </button>
          {field.extracted_value !== null && field.status !== "rejected" && (
            // Confirmed with the firm: no written reason, just clear the value.
            // A native confirm, same as deleting a document elsewhere in the app.
            <button
              className="btn btn--danger-ghost btn--sm"
              onClick={() => window.confirm(t.rejectConfirm) && onReject(field)}
              disabled={busy}
            >
              {t.reject}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
