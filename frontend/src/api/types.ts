/** Mirrors the backend Pydantic schemas. Kept hand-written and narrow on
 *  purpose: a generated client would pull in the whole OpenAPI surface, and
 *  these two screens use a small, stable slice of it. */

export type Uuid = string;

export interface User {
  id: Uuid;
  email: string;
  full_name: string;
  role: "owner" | "lawyer" | "staff";
  tenant_id: Uuid;
}

export type CaseStatus =
  | "intake"
  | "extracting"
  | "ready_for_review"
  | "in_review"
  | "submitted"
  | "closed"
  | "failed";

export interface Case {
  id: Uuid;
  case_number: string;
  status: CaseStatus;
  sender_id: Uuid | null;
  source_email_subject: string | null;
  odcanit_case_number: string | null;
  created_at: string;
  updated_at: string;
}

export type DocumentStatus =
  | "pending"
  | "extracting"
  | "extracted"
  | "partial"
  | "skipped"
  | "failed";

export interface CaseDocument {
  id: Uuid;
  case_id: Uuid;
  file_name: string;
  file_format: "pdf" | "docx" | "eml";
  file_size_bytes: number | null;
  page_count: number | null;
  document_type_id: Uuid | null;
  document_type_key: string | null;
  document_type_label: string | null;
  document_type_source: "ai" | "user" | "filename" | null;
  is_extractable: boolean | null;
  processing_status: DocumentStatus;
  error_message: string | null;
  uploaded_at: string;
  processed_at: string | null;
  /** True when the file was already in the case and no new row was created. */
  duplicate: boolean;
}

export interface DocumentType {
  id: Uuid;
  type_key: string;
  label: string;
  is_extractable: boolean;
}

export type FieldStatus = "pending_review" | "confirmed" | "edited" | "rejected";

export type AttentionReason =
  | "conflict"
  | "low_confidence"
  | "unverified_snippet"
  | "missing_required";

export interface FieldSource {
  document_id: Uuid | null;
  file_name: string | null;
  page: number | null;
  snippet: string | null;
}

export interface ReviewField {
  field_id: Uuid;
  field_key: string;
  label: string;
  data_type: "text" | "number" | "date" | "boolean";
  sort_order: number;
  is_required: boolean;
  required_for_this_case: boolean;
  always_needs_review: boolean;
  value: string | null;
  extracted_value: string | null;
  status: FieldStatus;
  confidence: number | null;
  has_conflict: boolean;
  conflict_count: number;
  conflict_ack_at: string | null;
  candidate_count: number;
  source: FieldSource;
  reviewed_by: Uuid | null;
  reviewed_at: string | null;
  /** The optimistic-locking token. Send it back on every mutation. */
  updated_at: string | null;
  attention_reasons: AttentionReason[];
}

export interface ReviewFields {
  case_id: Uuid;
  case_status: CaseStatus;
  case_type: string | null;
  fields: ReviewField[];
}

export interface Candidate {
  id: Uuid;
  document_id: Uuid;
  file_name: string;
  document_type_label: string | null;
  value: string | null;
  raw_value: string | null;
  confidence: number;
  priority: number;
  source_page: number | null;
  source_snippet: string | null;
  /** null means the page carried no text layer to check against. */
  snippet_verified: boolean | null;
  is_resolved: boolean;
}

export type BulkSkipReason =
  | "no_value"
  | "already_reviewed"
  | "conflict"
  | "always_needs_review"
  | "low_confidence";

export interface BulkConfirmResult {
  confirmed: Uuid[];
  skipped: { field_id: Uuid; field_key: string; reason: BulkSkipReason }[];
  min_confidence: number;
}

export type BlockerReason = "missing" | "unconfirmed" | "rejected" | "unrecognised";

export type WarningCode =
  | "case_type_unknown"
  | "unacknowledged_conflict"
  | "deadline_not_computed"
  | "referral_email_missing";

export interface Readiness {
  case_id: Uuid;
  case_type: string | null;
  is_ready: boolean;
  blockers: { field_id: Uuid; field_key: string; label: string; reason: BlockerReason }[];
  warnings: { code: WarningCode; field_key: string | null; detail: string | null }[];
  confirmed_count: number;
  required_count: number;
}
