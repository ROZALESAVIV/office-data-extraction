import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/client";
import type { Case } from "../api/types";
import { canDecide, useAuth } from "../lib/auth";
import { app, caseStatus, cases as t } from "../lib/hebrew";
import { formatDate } from "../lib/format";
import { Badge, Loading, Notice, Spinner, Toast } from "../components/ui";

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
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listCases()
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function create() {
    setCreating(true);
    try {
      const created = await api.createCase({});
      navigate(`/cases/${created.id}/documents`);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>{t.heading}</h1>
          <p className="page__sub">{app.subtitle}</p>
        </div>
        {canDecide(user) && (
          <div className="page__actions">
            <button className="btn btn--primary" onClick={create} disabled={creating}>
              {creating ? <Spinner /> : null}
              {creating ? t.creating : t.create}
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
                <th>{t.status}</th>
                <th>{t.created}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.case_number}</td>
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

      {toast && <Toast message={toast} tone="danger" onDone={() => setToast(null)} />}
    </div>
  );
}
