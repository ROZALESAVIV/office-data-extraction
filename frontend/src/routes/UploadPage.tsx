import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";
import type { Case, CaseDocument, DocumentType } from "../api/types";
import { canDecide, useAuth } from "../lib/auth";
import { app, caseStatus, documentStatus, upload as t } from "../lib/hebrew";
import { formatBytes, formatDateTime } from "../lib/format";
import { Badge, Loading, Modal, Notice, Spinner, Toast } from "../components/ui";

const STATUS_TONE: Record<string, "neutral" | "ok" | "warn" | "danger" | "accent"> = {
  pending: "neutral",
  extracting: "accent",
  extracted: "ok",
  partial: "warn",
  skipped: "neutral",
  failed: "danger",
};

/** The insurer's referral email. Seven fields are read from it by pattern
 *  match, so its absence changes how much of the case can be trusted. */
const REFERRAL_EMAIL_KEY = "referral_email";

export default function UploadPage() {
  const { caseId = "" } = useParams();
  const { user } = useAuth();
  const mayDecide = canDecide(user);

  const [kase, setKase] = useState<Case | null>(null);
  const [docs, setDocs] = useState<CaseDocument[] | null>(null);
  const [types, setTypes] = useState<DocumentType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [reclassifying, setReclassifying] = useState<CaseDocument | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const [c, d] = await Promise.all([api.getCase(caseId), api.listDocuments(caseId)]);
    setKase(c);
    setDocs(d);
  }, [caseId]);

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    api.listDocumentTypes().then(setTypes).catch(() => undefined);
  }, [refresh]);

  // Extraction runs in the background on the server, so the screen has to ask.
  // It stops asking the moment nothing is in flight.
  const working = useMemo(
    () => (docs ?? []).some((d) => d.processing_status === "pending" || d.processing_status === "extracting"),
    [docs],
  );

  useEffect(() => {
    if (!working) return;
    const timer = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [working, refresh]);

  const hasReferralEmail = useMemo(
    () => (docs ?? []).some((d) => d.document_type_key === REFERRAL_EMAIL_KEY),
    [docs],
  );

  const send = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      setBusy(true);
      try {
        const result = await api.uploadDocuments(caseId, files);
        const duplicates = result.filter((r) => r.duplicate).length;
        setToast({
          text: duplicates
            ? `${t.done} · ${duplicates} ${t.duplicate}`
            : t.done,
        });
        await refresh();
      } catch (e) {
        setToast({ text: e instanceof Error ? e.message : String(e), bad: true });
      } finally {
        setBusy(false);
      }
    },
    [caseId, refresh],
  );

  async function remove(doc: CaseDocument) {
    if (!window.confirm(t.deleteConfirm)) return;
    try {
      await api.deleteDocument(doc.id);
      await refresh();
    } catch (e) {
      setToast({ text: e instanceof Error ? e.message : String(e), bad: true });
    }
  }

  if (error) return <div className="page"><Notice tone="danger">{error}</Notice></div>;
  if (!kase || docs === null) return <div className="page"><Loading /></div>;

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>
            {t.heading} · <span className="mono">{kase.case_number}</span>
          </h1>
          <p className="page__sub">
            <Badge dot tone={kase.status === "failed" ? "danger" : "accent"}>
              {caseStatus[kase.status]}
            </Badge>
          </p>
        </div>
        <div className="page__actions">
          <Link className="btn btn--primary" to={`/cases/${caseId}/review`}>
            {t.goToReview}
          </Link>
        </div>
      </div>

      <div className="stack">
        {/* The firm confirmed the email always arrives. Saying so before the
            lawyer starts reviewing is cheaper than discovering it later. */}
        {docs.length > 0 && (
          <Notice tone={hasReferralEmail ? "ok" : "warn"} icon={hasReferralEmail ? "✓" : "!"}>
            <strong>{hasReferralEmail ? t.emailFound : t.emailMissing}</strong>
            {!hasReferralEmail && <div style={{ marginBlockStart: 4 }}>{t.emailReminderBody}</div>}
          </Notice>
        )}

        <div
          className={
            "dropzone" +
            (dragging ? " dropzone--active" : "") +
            (busy ? " dropzone--busy" : "")
          }
          onClick={() => !busy && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!busy) void send(Array.from(e.dataTransfer.files));
          }}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            accept=".pdf,.docx,.eml"
            onChange={(e) => {
              void send(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
          {busy ? (
            <div className="row" style={{ justifyContent: "center" }}>
              <Spinner />
              <span>{t.working}</span>
            </div>
          ) : (
            <>
              <div className="dropzone__title">{t.dropTitle}</div>
              <div className="dropzone__hint">{t.dropHint}</div>
              <div className="dropzone__formats">
                <div className="ltr">{t.formats}</div>
                <div>{t.limits}</div>
              </div>
            </>
          )}
        </div>

        {working && <Notice tone="info" icon="⟳">{t.extractionRunning}</Notice>}

        <div className="card">
          <div className="card__head">
            <h2>{t.documentsHeading}</h2>
            <Badge>{docs.length}</Badge>
          </div>
          {docs.length === 0 ? (
            <div className="empty">{t.noDocuments}</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>קובץ</th>
                  <th>סיווג</th>
                  <th>סטטוס</th>
                  <th>הועלה</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      <div className="doc-row__name">
                        <span className="bidi-auto">{doc.file_name}</span>
                      </div>
                      <div className="doc-row__meta bidi-auto">
                        {formatBytes(doc.file_size_bytes)}
                        {doc.page_count !== null && ` · ${t.pages(doc.page_count)}`}
                      </div>
                    </td>
                    <td>
                      {doc.document_type_label ? (
                        <>
                          <div>{doc.document_type_label}</div>
                          {doc.is_extractable === false && (
                            <div className="doc-row__meta" title={t.notExtractableHelp}>
                              {t.notExtractable}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="muted">{t.unclassified}</span>
                      )}
                    </td>
                    <td>
                      <Badge tone={STATUS_TONE[doc.processing_status] ?? "neutral"} dot>
                        {documentStatus[doc.processing_status]}
                      </Badge>
                      {doc.error_message && (
                        <div className="doc-row__meta" title={doc.error_message}>
                          {doc.error_message.slice(0, 60)}
                        </div>
                      )}
                    </td>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>
                      {formatDateTime(doc.uploaded_at)}
                    </td>
                    <td style={{ textAlign: "end", whiteSpace: "nowrap" }}>
                      {mayDecide && (
                        <>
                          <button
                            className="btn btn--ghost btn--sm"
                            onClick={() => setReclassifying(doc)}
                          >
                            {t.reclassify}
                          </button>
                          <button
                            className="btn btn--danger-ghost btn--sm"
                            onClick={() => void remove(doc)}
                          >
                            {t.delete}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {reclassifying && (
        <ReclassifyDialog
          doc={reclassifying}
          types={types}
          onClose={() => setReclassifying(null)}
          onDone={async () => {
            setReclassifying(null);
            await refresh();
          }}
        />
      )}

      {toast && (
        <Toast
          message={toast.text}
          tone={toast.bad ? "danger" : "neutral"}
          onDone={() => setToast(null)}
        />
      )}
    </div>
  );
}

/** The model decides the type; the lawyer overrides it and their choice is
 *  final. Re-classifying re-queues the document for extraction. */
function ReclassifyDialog({
  doc,
  types,
  onClose,
  onDone,
}: {
  doc: CaseDocument;
  types: DocumentType[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [selected, setSelected] = useState(doc.document_type_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await api.reclassifyDocument(doc.id, selected);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Modal title={upload_reclassifyTitle(doc)} onClose={onClose}>
      <div className="stack">
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="field">
          <label htmlFor="type">{t.reclassify}</label>
          <select
            id="type"
            className="select"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">{t.unclassified}</option>
            {types.map((type) => (
              <option key={type.id} value={type.id}>
                {type.label}
                {!type.is_extractable ? ` — ${t.notExtractable}` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="row">
          <button className="btn btn--primary" onClick={() => void save()} disabled={busy || !selected}>
            {busy ? <Spinner /> : null}
            {app.save}
          </button>
          <button className="btn btn--ghost" onClick={onClose}>
            {app.cancel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function upload_reclassifyTitle(doc: CaseDocument): string {
  return `${t.reclassify} — ${doc.file_name}`;
}
