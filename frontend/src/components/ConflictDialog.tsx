import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { Candidate, ReviewField } from "../api/types";
import { review as t } from "../lib/hebrew";
import { Badge, Confidence, Loading, Notice, Spinner } from "./ui";
import { Modal } from "./ui";

/** Side by side, in the order the resolver ranked them.
 *
 *  Picking one is how a conflict is meant to be resolved: retyping the rival
 *  value by hand would work and would lose the provenance — the answer would
 *  read as the lawyer's invention rather than as the registry extract it is.
 */
export default function ConflictDialog({
  caseId,
  field,
  mayDecide,
  onClose,
  onChosen,
  onOpenDocument,
}: {
  caseId: string;
  field: ReviewField;
  mayDecide: boolean;
  onClose: () => void;
  onChosen: (candidateId: string) => Promise<void>;
  onOpenDocument: (documentId: string, page: number | null) => void;
}) {
  const [rows, setRows] = useState<Candidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCandidates(caseId, field.field_id)
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [caseId, field.field_id]);

  async function choose(candidate: Candidate) {
    setBusyId(candidate.id);
    try {
      await onChosen(candidate.id);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Modal title={`${field.label} — ${t.conflictHeading}`} onClose={onClose}>
      <div className="stack">
        {error && <Notice tone="danger">{error}</Notice>}
        {field.has_conflict && <Notice tone="info" icon="?">{t.conflictExplain}</Notice>}

        {rows === null ? (
          <Loading />
        ) : rows.length === 0 ? (
          <div className="empty">{t.noCandidates}</div>
        ) : (
          <div className="candidates">
            {rows.map((row) => (
              <div
                key={row.id}
                className={row.is_resolved ? "candidate candidate--chosen" : "candidate"}
              >
                <div className="candidate__head">
                  <span className="candidate__value">{row.value ?? "—"}</span>
                  {row.is_resolved && <Badge tone="accent">{t.chosen}</Badge>}
                  {row.snippet_verified === false && (
                    <Badge tone="warn">{t.unverifiedSnippet}</Badge>
                  )}
                </div>

                <div className="candidate__meta">
                  <button
                    className="btn btn--ghost btn--sm"
                    onClick={() => onOpenDocument(row.document_id, row.source_page)}
                  >
                    <span className="bidi-auto">{row.file_name}</span>
                    {row.source_page !== null && ` · ${t.page(row.source_page)}`}
                  </button>
                  {row.document_type_label && <span>{row.document_type_label}</span>}
                  <Confidence value={row.confidence} />
                  {row.snippet_verified === null && (
                    <span className="muted">{t.unverifiableSnippet}</span>
                  )}
                </div>

                {row.source_snippet && (
                  <div className="candidate__snippet">{row.source_snippet}</div>
                )}

                {mayDecide && !row.is_resolved && row.value && (
                  <div className="candidate__foot">
                    <button
                      className="btn btn--sm btn--primary"
                      onClick={() => void choose(row)}
                      disabled={busyId !== null}
                    >
                      {busyId === row.id ? <Spinner /> : null}
                      {t.chooseThis}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
