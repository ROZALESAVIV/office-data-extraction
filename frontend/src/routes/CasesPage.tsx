import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/client";
import type { Case, Sender } from "../api/types";
import { canDecide, useAuth } from "../lib/auth";
import { app, caseStatus, cases as t } from "../lib/hebrew";
import { formatDate } from "../lib/format";
import { Badge, Loading, Modal, Notice, Spinner, Toast } from "../components/ui";

const TONE: Record<string, "neutral" | "ok" | "warn" | "danger" | "accent"> = {
  intake: "neutral",
  extracting: "accent",
  ready_for_review: "warn",
  in_review: "accent",
  submitted: "ok",
  closed: "neutral",
  failed: "danger",
};

export default function CasesPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Case[] | null>(null);
  const [senders, setSenders] = useState<Sender[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listCases()
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    api.listSenders().then(setSenders).catch(() => setSenders([]));
  }, []);

  // Senders map by id so the list can show a name, not a bare uuid.
  const senderName = (id: string | null) => senders?.find((s) => s.id === id)?.name ?? "—";

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>{t.heading}</h1>
          <p className="page__sub">{app.subtitle}</p>
        </div>
        {canDecide(user) && (
          <div className="page__actions">
            <button className="btn btn--primary" onClick={() => setShowCreate(true)}>
              {t.create}
            </button>
          </div>
        )}
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="card">
        {rows === null ? (
          <Loading />
        ) : rows.length === 0 ? (
          <div className="empty">{t.empty}</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>{t.number}</th>
                <th>{t.sender}</th>
                <th>{t.status}</th>
                <th>{t.created}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.case_number}</td>
                  <td>{senderName(row.sender_id)}</td>
                  <td>
                    <Badge tone={TONE[row.status] ?? "neutral"} dot>
                      {caseStatus[row.status]}
                    </Badge>
                  </td>
                  <td className="muted">{formatDate(row.created_at)}</td>
                  <td style={{ textAlign: "end" }}>
                    <button
                      className="btn btn--sm"
                      onClick={() => navigate(`/cases/${row.id}/documents`)}
                    >
                      {t.open}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateCaseDialog
          senders={senders}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => navigate(`/cases/${id}/documents`)}
          onError={(msg) => setToast(msg)}
        />
      )}

      {toast && <Toast message={toast} tone="danger" onDone={() => setToast(null)} />}
    </div>
  );
}

/** A case's sender is where the Odcanit main-client prefix comes from later -
 *  skipping it here is how a case reaches submission with nowhere to attach. */
function CreateCaseDialog({
  senders,
  onClose,
  onCreated,
  onError,
}: {
  senders: Sender[] | null;
  onClose: () => void;
  onCreated: (caseId: string) => void;
  onError: (message: string) => void;
}) {
  const [senderId, setSenderId] = useState("");
  const [busy, setBusy] = useState(false);
  const active = (senders ?? []).filter((s) => s.is_active);

  async function submit() {
    if (!senderId) return;
    setBusy(true);
    try {
      const created = await api.createCase({ sender_id: senderId });
      onCreated(created.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Modal title={t.newCaseTitle} onClose={onClose}>
      <div className="stack">
        {senders === null ? (
          <Loading />
        ) : active.length === 0 ? (
          <Notice tone="warn">{t.noSenders}</Notice>
        ) : (
          <div className="field">
            <label htmlFor="sender">{t.senderLabel}</label>
            <select
              id="sender"
              className="select"
              value={senderId}
              onChange={(e) => setSenderId(e.target.value)}
              autoFocus
            >
              <option value="">{t.senderPlaceholder}</option>
              {active.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="row">
          <button
            className="btn btn--primary"
            onClick={() => void submit()}
            disabled={busy || !senderId}
            title={!senderId ? t.senderRequired : undefined}
          >
            {busy ? <Spinner /> : null}
            {busy ? t.creating : t.create}
          </button>
          <button className="btn btn--ghost" onClick={onClose}>
            {app.cancel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
