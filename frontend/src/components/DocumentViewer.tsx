import { useEffect, useState } from "react";
import * as api from "../api/client";
import { Loading, Modal, Notice } from "./ui";
import { review as t } from "../lib/hebrew";

/** The signed URL is short-lived and fetched per open, so a stale link is never
 *  left sitting in the DOM. The storage key itself never reaches the browser. */
export default function DocumentViewer({
  documentId,
  page,
  onClose,
}: {
  documentId: string;
  page: number | null;
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .documentUrl(documentId)
      .then((r) => !cancelled && setUrl(r.url))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  // #page= is honoured by the browser's built-in PDF viewer, which lands the
  // lawyer on the page the value was quoted from rather than on page one.
  const src = url && page ? `${url}#page=${page}` : url;

  return (
    <Modal title={t.viewDocument} onClose={onClose} wide flush>
      {error ? (
        <div style={{ padding: 24 }}>
          <Notice tone="danger">{error}</Notice>
        </div>
      ) : src ? (
        <iframe src={src} title={t.viewDocument} />
      ) : (
        <Loading />
      )}
    </Modal>
  );
}
