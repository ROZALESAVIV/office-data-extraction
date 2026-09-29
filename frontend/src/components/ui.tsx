/** Small presentational pieces shared by both screens. */

import type { ReactNode } from "react";
import { useEffect } from "react";
import { formatConfidence, LOW_CONFIDENCE } from "../lib/format";
import { app } from "../lib/hebrew";

type Tone = "neutral" | "ok" | "warn" | "danger" | "accent";

export function Badge({
  tone = "neutral",
  dot = false,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  children: ReactNode;
}) {
  const cls = tone === "neutral" ? "badge" : `badge badge--${tone}`;
  return (
    <span className={cls}>
      {dot && <span className="badge__dot" />}
      {children}
    </span>
  );
}

export function Notice({
  tone = "info",
  icon,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok";
  icon?: string;
  children: ReactNode;
}) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      {icon && (
        <span className="notice__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <div>{children}</div>
    </div>
  );
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function Loading({ label = app.loading }: { label?: string }) {
  return (
    <div className="empty">
      <div className="row" style={{ justifyContent: "center" }}>
        <Spinner />
        <span>{label}</span>
      </div>
    </div>
  );
}

/** A bar plus the number. Scanning forty-five rows, the bar is what the eye
 *  uses; the number is there for the one row that matters. */
export function Confidence({ value }: { value: number | null }) {
  if (value === null) return <span className="muted">—</span>;
  const low = value < LOW_CONFIDENCE;
  return (
    <span className="confidence" title={`${app.loading ? "" : ""}${formatConfidence(value)}`}>
      <span className="confidence__track">
        <span
          className={low ? "confidence__fill confidence__fill--low" : "confidence__fill"}
          style={{ inlineSize: `${Math.round(value * 100)}%` }}
        />
      </span>
      {formatConfidence(value)}
    </span>
  );
}

export function Modal({
  title,
  onClose,
  wide = false,
  flush = false,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  flush?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={wide ? "modal modal--wide" : "modal"}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal__head">
          <h2>{title}</h2>
          <button className="btn btn--ghost btn--sm" onClick={onClose}>
            {app.close}
          </button>
        </div>
        <div className={flush ? "modal__body modal__body--flush" : "modal__body"}>{children}</div>
        {footer && <div className="modal__head" style={{ borderBlock: "none" }}>{footer}</div>}
      </div>
    </div>
  );
}

export function Toast({
  message,
  tone = "neutral",
  onDone,
}: {
  message: string;
  tone?: "neutral" | "danger";
  onDone: () => void;
}) {
  useEffect(() => {
    // Errors stay longer: they usually ask the reader to do something.
    const timer = window.setTimeout(onDone, tone === "danger" ? 7000 : 3000);
    return () => window.clearTimeout(timer);
  }, [message, tone, onDone]);

  return (
    <div className={tone === "danger" ? "toast toast--danger" : "toast"} role="status">
      {message}
    </div>
  );
}
