import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";
import { ConflictError } from "../api/client";
import type {
  BulkConfirmResult,
  BulkSkipReason,
  Readiness,
  ReviewField,
  ReviewFields,
} from "../api/types";
import { canDecide, useAuth } from "../lib/auth";
import { bulkSkip, caseStatus, caseType, review as t, upload as tu } from "../lib/hebrew";
import ConflictDialog from "../components/ConflictDialog";
import DocumentViewer from "../components/DocumentViewer";
import FieldRow from "../components/FieldRow";
import ReadinessPanel from "../components/ReadinessPanel";
import { Badge, Loading, Notice, Spinner, Toast } from "../components/ui";

type Tab = "attention" | "remaining" | "decided" | "all";

export default function ReviewPage() {
  const { caseId = "" } = useParams();
  const { user } = useAuth();
  const mayDecide = canDecide(user);

  const [data, setData] = useState<ReviewFields | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("attention");
  const [busyField, setBusyField] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkConfirmResult | null>(null);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);
  const [conflictField, setConflictField] = useState<ReviewField | null>(null);
  const [viewing, setViewing] = useState<{ documentId: string; page: number | null } | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const load = useCallback(async () => {
    const [fields, readiness] = await Promise.all([
      api.listFields(caseId),
      api.readiness(caseId),
    ]);
    setData(fields);
    setReady(readiness);
    return fields;
  }, [caseId]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  /** Every mutation funnels through here.
   *
   *  A 409 is not a failure to report and forget: it means another lawyer
   *  decided this field while it was on screen. The right response is to show
   *  their answer, not to retry over it. */
  const mutate = useCallback(
    async (field: ReviewField, action: () => Promise<unknown>) => {
      setBusyField(field.field_id);
      try {
        await action();
        await load();
        setToast({ text: `${field.label} · ${t.savedJustNow}` });
      } catch (e) {
        if (e instanceof ConflictError) {
          await load().catch(() => undefined);
          setToast({ text: t.conflictStale, bad: true });
        } else {
          setToast({ text: e instanceof Error ? e.message : String(e), bad: true });
        }
      } finally {
        setBusyField(null);
      }
    },
    [load],
  );

  const onConfirm = (field: ReviewField) =>
    void mutate(field, () => api.confirmField(caseId, field.field_id, field.updated_at));

  const onEdit = (field: ReviewField, value: string) =>
    void mutate(field, () => api.editField(caseId, field.field_id, value, field.updated_at));

  const onReject = (field: ReviewField) =>
    void mutate(field, () => api.rejectField(caseId, field.field_id, field.updated_at));

  const onChooseCandidate = async (candidateId: string) => {
    const field = conflictField;
    if (!field) return;
    await mutate(field, () =>
      api.selectCandidate(caseId, field.field_id, candidateId, field.updated_at),
    );
    setConflictField(null);
  };

  async function runBulkConfirm() {
    setBulkBusy(true);
    try {
      const result = await api.bulkConfirm(caseId);
      await load();
      // The server reports a reason for every field it declined to touch, and
      // a silent skip is how a required field gets forgotten. Show them.
      setBulkResult(result);
      setToast({
        text: result.confirmed.length ? t.bulkResult(result.confirmed.length) : t.bulkNothing,
      });
    } catch (e) {
      setToast({ text: e instanceof Error ? e.message : String(e), bad: true });
    } finally {
      setBulkBusy(false);
    }
  }

  const fields = data?.fields ?? [];

  const groups = useMemo(() => {
    const attention = fields.filter((f) => f.attention_reasons.length > 0);
    const remaining = fields.filter(
      (f) => f.status === "pending_review" && f.attention_reasons.length === 0,
    );
    const decided = fields.filter((f) => f.status !== "pending_review");
    return { attention, remaining, decided, all: fields };
  }, [fields]);

  const shown = groups[tab];

  function jumpToField(fieldId: string) {
    setTab("all");
    // The row must exist before it can be scrolled to, and switching tab
    // re-renders the list.
    window.setTimeout(() => {
      rowRefs.current[fieldId]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 60);
  }

  if (error) {
    return (
      <div className="page">
        <Notice tone="danger">{error}</Notice>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page">
        <Loading />
      </div>
    );
  }

  return (
    <div className="review">
      <div className="stack">
        <div className="page__head" style={{ marginBlockEnd: 0 }}>
          <div>
            <h1>{t.heading}</h1>
            <p className="page__sub row" style={{ gap: 8 }}>
              <Badge tone="accent" dot>
                {caseStatus[data.case_status]}
              </Badge>
              <Badge tone={data.case_type ? "neutral" : "warn"}>
                {caseType.label(data.case_type)}
              </Badge>
            </p>
          </div>
          <div className="page__actions">
            <Link className="btn" to={`/cases/${caseId}/documents`}>
              {t.backToUpload}
            </Link>
            {mayDecide && (
              <button
                className="btn btn--primary"
                onClick={() => void runBulkConfirm()}
                disabled={bulkBusy}
                title={t.bulkExplain}
              >
                {bulkBusy ? <Spinner /> : null}
                {bulkBusy ? t.bulkWorking : t.bulkConfirm}
              </button>
            )}
          </div>
        </div>

        {bulkResult && bulkResult.skipped.length > 0 && (
          <Notice tone="info" icon="i">
            <strong>
              {bulkResult.confirmed.length ? t.bulkResult(bulkResult.confirmed.length) : t.bulkNothing}
              {" · "}
              {t.bulkSkipped}:
            </strong>
            <ul style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>
              {summariseSkips(bulkResult).map(([reason, count]) => (
                <li key={reason}>
                  {bulkSkip[reason]} — {count}
                </li>
              ))}
            </ul>
          </Notice>
        )}

        <div className="card">
          <div className="tabs">
            <TabButton id="attention" tab={tab} setTab={setTab} label={t.needsAttention} count={groups.attention.length} />
            <TabButton id="remaining" tab={tab} setTab={setTab} label={t.remaining} count={groups.remaining.length} />
            <TabButton id="decided" tab={tab} setTab={setTab} label={t.decided} count={groups.decided.length} />
            <TabButton id="all" tab={tab} setTab={setTab} label={t.all} count={groups.all.length} />
          </div>

          {shown.length === 0 ? (
            <div className="empty">{t.emptyList}</div>
          ) : (
            <div className="field-list">
              {shown.map((field) => (
                <div
                  key={field.field_id}
                  ref={(el) => {
                    rowRefs.current[field.field_id] = el;
                  }}
                >
                  <FieldRow
                    field={field}
                    mayDecide={mayDecide}
                    busy={busyField === field.field_id}
                    onConfirm={onConfirm}
                    onEdit={onEdit}
                    onReject={onReject}
                    onOpenConflict={setConflictField}
                    onOpenDocument={(documentId, page) => setViewing({ documentId, page })}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <aside className="review__aside">
        <ReadinessPanel data={ready} onJumpToField={jumpToField} />
        {mayDecide && (
          <div className="card">
            <div className="card__body">
              <Notice tone="info" icon="i">
                {t.bulkExplain}
              </Notice>
            </div>
          </div>
        )}
        <Link className="btn" to={`/cases/${caseId}/documents`}>
          {tu.documentsHeading}
        </Link>
      </aside>

      {conflictField && (
        <ConflictDialog
          caseId={caseId}
          field={conflictField}
          mayDecide={mayDecide}
          onClose={() => setConflictField(null)}
          onChosen={onChooseCandidate}
          onOpenDocument={(documentId, page) => setViewing({ documentId, page })}
        />
      )}

      {viewing && (
        <DocumentViewer
          documentId={viewing.documentId}
          page={viewing.page}
          onClose={() => setViewing(null)}
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

/** Forty-five fields make a per-field list unreadable; grouped by reason it is
 *  four lines that say exactly what was left behind and why. */
function summariseSkips(result: BulkConfirmResult): [BulkSkipReason, number][] {
  const counts = new Map<BulkSkipReason, number>();
  for (const skip of result.skipped) {
    counts.set(skip.reason, (counts.get(skip.reason) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function TabButton({
  id,
  tab,
  setTab,
  label,
  count,
}: {
  id: Tab;
  tab: Tab;
  setTab: (t: Tab) => void;
  label: string;
  count: number;
}) {
  return (
    <button
      className={tab === id ? "tab tab--active" : "tab"}
      onClick={() => setTab(id)}
      aria-pressed={tab === id}
    >
      {label}
      <span className="tab__count">{count}</span>
    </button>
  );
}
