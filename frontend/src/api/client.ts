/** The one place that talks to the API.
 *
 *  Two things are deliberate:
 *  - 409 becomes a typed ConflictError rather than a generic failure. The review
 *    screen has to tell "somebody else changed this field" apart from "the
 *    server is down", because only the first one has a useful next step.
 *  - The token lives in sessionStorage, not localStorage: a case file is
 *    privileged material, and a closed tab should end the session.
 */

import type {
  BulkConfirmResult,
  Candidate,
  Case,
  CaseDocument,
  DocumentType,
  Readiness,
  ReviewField,
  ReviewFields,
  Sender,
  User,
  Uuid,
} from "./types";

const BASE = "/api";
const TOKEN_KEY = "ode.token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Somebody changed this field between the read and the write. */
export class ConflictError extends ApiError {}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token === null) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private mode: the session simply does not survive a reload */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "אין תקשורת עם השרת");
  }

  if (response.status === 401) {
    setToken(null);
    throw new ApiError(401, "פג תוקף ההתחברות");
  }
  if (!response.ok) {
    const message = await errorMessage(response);
    if (response.status === 409) throw new ConflictError(409, message);
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors arrive as a list of objects.
    if (Array.isArray(detail) && detail.length) return detail[0]?.msg ?? "בקשה שגויה";
  } catch {
    /* not JSON */
  }
  return `שגיאת שרת (${response.status})`;
}

// ── auth ────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  const response = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const body = (await response.json()) as { access_token: string };
  setToken(body.access_token);
}

export const me = () => request<User>("/auth/me");

// ── cases ───────────────────────────────────────────────────────────────────

export const listCases = () => request<Case[]>("/cases");
export const getCase = (id: Uuid) => request<Case>(`/cases/${id}`);

export const createCase = (body: {
  sender_id?: Uuid | null;
  source_email_subject?: string | null;
}) => request<Case>("/cases", { method: "POST", body: JSON.stringify(body) });

// ── senders ─────────────────────────────────────────────────────────────────

export const listSenders = () => request<Sender[]>("/senders");

// ── documents ───────────────────────────────────────────────────────────────

export const listDocuments = (caseId: Uuid) =>
  request<CaseDocument[]>(`/cases/${caseId}/documents`);

export const listDocumentTypes = () => request<DocumentType[]>("/document-types");

export function uploadDocuments(caseId: Uuid, files: File[]): Promise<CaseDocument[]> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return request<CaseDocument[]>(`/cases/${caseId}/documents`, {
    method: "POST",
    body: form,
  });
}

export const documentUrl = (documentId: Uuid) =>
  request<{ url: string; expires_in_seconds: number }>(`/documents/${documentId}/url`);

export const reclassifyDocument = (documentId: Uuid, documentTypeId: Uuid) =>
  request<CaseDocument>(`/documents/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify({ document_type_id: documentTypeId }),
  });

export const deleteDocument = (documentId: Uuid) =>
  request<void>(`/documents/${documentId}`, { method: "DELETE" });

// ── review ──────────────────────────────────────────────────────────────────

export const listFields = (caseId: Uuid) => request<ReviewFields>(`/cases/${caseId}/fields`);

export const listCandidates = (caseId: Uuid, fieldId: Uuid) =>
  request<Candidate[]>(`/cases/${caseId}/fields/${fieldId}/candidates`);

export const readiness = (caseId: Uuid) => request<Readiness>(`/cases/${caseId}/readiness`);

/** Every single-field mutation carries the token it was loaded with. */
export const confirmField = (caseId: Uuid, fieldId: Uuid, expected: string | null) =>
  request<ReviewField>(`/cases/${caseId}/fields/${fieldId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ expected_updated_at: expected }),
  });

export const editField = (
  caseId: Uuid,
  fieldId: Uuid,
  value: string,
  expected: string | null,
) =>
  request<ReviewField>(`/cases/${caseId}/fields/${fieldId}`, {
    method: "PATCH",
    body: JSON.stringify({ value, expected_updated_at: expected }),
  });

// No reason field: confirmed with the firm that the workflow is either type
// the correct value, or clear this one and leave it blank - no separate
// written explanation is part of that.
export const rejectField = (caseId: Uuid, fieldId: Uuid, expected: string | null) =>
  request<ReviewField>(`/cases/${caseId}/fields/${fieldId}/reject`, {
    method: "POST",
    body: JSON.stringify({ expected_updated_at: expected }),
  });

export const selectCandidate = (
  caseId: Uuid,
  fieldId: Uuid,
  candidateId: Uuid,
  expected: string | null,
) =>
  request<ReviewField>(`/cases/${caseId}/fields/${fieldId}/select-candidate`, {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId, expected_updated_at: expected }),
  });

export const bulkConfirm = (caseId: Uuid, minConfidence?: number) =>
  request<BulkConfirmResult>(`/cases/${caseId}/fields/bulk-confirm`, {
    method: "POST",
    body: JSON.stringify({ min_confidence: minConfidence ?? null }),
  });
