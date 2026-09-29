import type { Readiness } from "../api/types";
import { blockerReason, readiness as t, warningText } from "../lib/hebrew";
import { Badge, Notice } from "./ui";

/** What still stands between this case and submission.
 *
 *  Blockers and warnings are kept visibly apart: a warning that looked like a
 *  blocker would have lawyers hunting for a problem that is not theirs to fix.
 */
export default function ReadinessPanel({
  data,
  onJumpToField,
}: {
  data: Readiness | null;
  onJumpToField: (fieldId: string) => void;
}) {
  if (!data) return null;

  const done = data.confirmed_count;
  const total = data.required_count;
  const percent = total === 0 ? 100 : Math.round((done / total) * 100);

  return (
    <div className="card">
      <div className="card__head">
        <h2>{t.heading}</h2>
        <Badge tone={data.is_ready ? "ok" : "warn"} dot>
          {data.is_ready ? t.ready : t.notReady}
        </Badge>
      </div>
      <div className="card__body">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="muted">{t.progress(done, total)}</span>
          <span className="mono">{percent}%</span>
        </div>
        <div className="readiness__bar">
          <div
            className={data.is_ready ? "readiness__fill readiness__fill--ready" : "readiness__fill"}
            style={{ inlineSize: `${percent}%` }}
          />
        </div>

        {data.blockers.length > 0 && (
          <>
            <div className="readiness__section-title">{t.blockers}</div>
            <ul className="readiness__list">
              {data.blockers.map((b) => (
                <li key={b.field_id}>
                  <button className="readiness__item" onClick={() => onJumpToField(b.field_id)}>
                    <span className="readiness__item-label">{b.label}</span>
                    <span className="readiness__item-reason">{blockerReason[b.reason]}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {data.warnings.length > 0 && (
          <>
            <div className="readiness__section-title">{t.warnings}</div>
            <ul className="readiness__list">
              {data.warnings.map((w, i) => (
                <li key={`${w.code}-${w.field_key ?? i}`} className="readiness__item">
                  <span className="readiness__item-reason">{warningText[w.code]}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        <div style={{ marginBlockStart: 16 }}>
          {/* The endpoint does not exist yet: the Odcanit contract is still
              open with the firm. Showing the button disabled is more honest
              than hiding the last step of the flow. */}
          <button className="btn btn--primary" style={{ width: "100%" }} disabled>
            {t.submit}
          </button>
          <div style={{ marginBlockStart: 8 }}>
            <Notice tone="info">{t.submitDisabled}</Notice>
          </div>
        </div>
      </div>
    </div>
  );
}
