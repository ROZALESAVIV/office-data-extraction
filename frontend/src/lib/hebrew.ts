/** Every string the lawyer reads.
 *
 *  In one file so the wording can be reviewed by the firm without reading the
 *  components, and so no sentence is written twice in two slightly different
 *  ways. Field labels and document-type labels are NOT here: they come from the
 *  database, already in Hebrew, and the firm owns them.
 */

import type {
  AttentionReason,
  BlockerReason,
  BulkSkipReason,
  CaseStatus,
  DocumentStatus,
  FieldStatus,
  WarningCode,
} from "../api/types";

export const app = {
  title: "מערכת הפקת נתונים",
  subtitle: "תיקי ביטוח ישיר",
  signOut: "יציאה",
  loading: "טוען…",
  retry: "נסה שוב",
  cancel: "ביטול",
  save: "שמירה",
  close: "סגירה",
  search: "חיפוש",
};

export const login = {
  heading: "כניסה למערכת",
  email: "דואר אלקטרוני",
  password: "סיסמה",
  submit: "כניסה",
  working: "מתחבר…",
  failed: "הדואר האלקטרוני או הסיסמה שגויים",
};

export const cases = {
  heading: "תיקים",
  create: "תיק חדש",
  creating: "יוצר תיק…",
  empty: "אין עדיין תיקים. פתח תיק חדש כדי להתחיל.",
  number: "מספר תיק",
  status: "סטטוס",
  created: "נפתח",
  documents: "מסמכים",
  open: "פתיחה",
};

export const caseStatus: Record<CaseStatus, string> = {
  intake: "קליטה",
  extracting: "בהפקה",
  ready_for_review: "מוכן לבדיקה",
  in_review: "בבדיקה",
  submitted: "הוגש",
  closed: "סגור",
  failed: "נכשל",
};

// ── upload screen ───────────────────────────────────────────────────────────

export const upload = {
  heading: "העלאת מסמכים",
  dropTitle: "גרור לכאן את מסמכי התיק",
  dropHint: "או לחץ לבחירת קבצים",
  formats: "PDF · DOCX · EML",
  limits: "עד 40 קבצים, 40 מגה-בייט לקובץ",
  button: "העלאה",
  working: "מעלה…",
  done: "ההעלאה הושלמה",
  emailReminder: "מייל ההפניה מהמבטח",
  emailReminderBody:
    "מייל ההפניה תמיד מגיע עם התיק, והוא המקור האמין ביותר בו — שבעה שדות נקראים ממנו במדויק, בלי פענוח ובלי ניחוש. אם הוא לא הועלה, שבעה שדות ודאיים הופכים להשערה.",
  emailFound: "מייל ההפניה נמצא בתיק",
  emailMissing: "מייל ההפניה חסר בתיק",
  documentsHeading: "מסמכי התיק",
  noDocuments: "עדיין לא הועלו מסמכים.",
  duplicate: "כבר קיים בתיק",
  reclassify: "שינוי סיווג",
  unclassified: "לא סווג",
  notExtractable: "אין שדות להפקה",
  notExtractableHelp:
    "צילומים, רישיונות והמחאות נשמרים ומועברים הלאה, אך לא נשלחים למודל — אין בהם שדות להפיק.",
  pages: (n: number) => (n === 1 ? "עמוד אחד" : `${n} עמודים`),
  goToReview: "מעבר לבדיקה",
  extractionRunning: "ההפקה רצה ברקע. המסך מתעדכן מאליו.",
  deleteConfirm: "למחוק את המסמך מהתיק?",
  delete: "מחיקה",
};

export const documentStatus: Record<DocumentStatus, string> = {
  pending: "ממתין",
  extracting: "בהפקה",
  extracted: "הופק",
  partial: "הופק חלקית",
  skipped: "לא נדרשה הפקה",
  failed: "נכשל",
};

// ── review screen ───────────────────────────────────────────────────────────

export const review = {
  heading: "בדיקת נתונים",
  backToUpload: "חזרה למסמכים",
  fieldsHeading: "שדות",
  all: "הכל",
  needsAttention: "דורש תשומת לב",
  remaining: "ממתין להכרעה",
  decided: "הוכרע",
  bulkConfirm: "אישור מרוכז",
  bulkWorking: "מאשר…",
  bulkExplain:
    "מאשר בבת אחת את השדות בביטחון גבוה. לא נוגע בשדות שיש בהם מחלוקת, ולא בשדות שמזינים את מועד ההגשה.",
  bulkResult: (n: number) => `${n} שדות אושרו`,
  bulkNothing: "לא נמצאו שדות לאישור מרוכז",
  bulkSkipped: "שדות שדולגו",
  confirm: "אישור",
  edit: "עריכה",
  reject: "סימון כשגוי",
  rejectReason: "סיבה (לא חובה)",
  saveEdit: "שמירת הערך",
  source: "מקור",
  page: (n: number) => `עמוד ${n}`,
  noSource: "אין מסמך מקור",
  // One empty state, and it states a fact. "Manual entry" was a guess about
  // why a field is empty, and it was wrong for every field that was simply not
  // found.
  noValue: "לא נמצא ערך",
  computedVerify: "מחושב — לאימות",
  alwaysNeedsReview: "מחייב אישור",
  requiredHere: "חובה",
  confidence: "ביטחון",
  viewDocument: "פתיחת המסמך",
  conflictHeading: "מסמכים חלוקים",
  conflictExplain: "בחר את המסמך שיש להאמין לו. הערך יילקח ממנו, ויירשם ממי הגיע.",
  chooseThis: "בחר ערך זה",
  chosen: "הערך הנוכחי",
  candidates: "מה אמר כל מסמך",
  noCandidates: "אף מסמך לא החזיר ערך לשדה הזה.",
  unverifiedSnippet: "הציטוט לא אומת מול העמוד",
  unverifiableSnippet: "לא ניתן לאמת — בעמוד אין שכבת טקסט",
  conflictStale:
    "השדה השתנה מאז שטענת את המסך — ייתכן שעורך דין אחר הכריע בו. המסך נטען מחדש.",
  savedJustNow: "נשמר",
  emptyList: "אין שדות בקטגוריה הזו.",
};

export const fieldStatus: Record<FieldStatus, string> = {
  pending_review: "ממתין",
  confirmed: "אושר",
  edited: "נערך",
  rejected: "סומן כשגוי",
};

export const attention: Record<AttentionReason, string> = {
  conflict: "מחלוקת בין מסמכים",
  low_confidence: "ביטחון נמוך",
  unverified_snippet: "ציטוט לא אומת",
  missing_required: "שדה חובה ריק",
};

// ── readiness ───────────────────────────────────────────────────────────────

export const readiness = {
  heading: "מוכנות להגשה",
  ready: "כל שדות החובה הוכרעו",
  notReady: "התיק עדיין לא מוכן להגשה",
  blockers: "חוסם הגשה",
  warnings: "שווה לשים לב",
  progress: (done: number, total: number) => `${done} מתוך ${total} שדות חובה`,
  submit: "הגשה למערכת Odcanit",
  submitDisabled: "ההגשה טרם נבנתה — ממתינה לחוזה מול Odcanit ולאישור המשרד.",
};

export const blockerReason: Record<BlockerReason, string> = {
  missing: "אין ערך",
  unconfirmed: "יש ערך, אך איש לא אישר אותו",
  rejected: "סומן כשגוי, ולא הוזן ערך חלופי",
  unrecognised: "הערך אינו אחד משני סוגי התיק",
};

export const warningText: Record<WarningCode, string> = {
  case_type_unknown:
    "סוג התיק אינו ידוע, ולכן שדות בית המשפט אינם נדרשים כרגע. בתיק הגנה הם כן נדרשים.",
  unacknowledged_conflict: "שני מסמכים חלוקים על השדה הזה, ואיש עוד לא הכריע.",
  deadline_not_computed:
    "לא נמצא תאריך מסירה ולא תאריך פתיחת תיק, ולכן לא חושב מועד להגשת כתב הגנה.",
  referral_email_missing:
    "לא נמצא מייל הפניה בתיק. שבעה שדות שנקראים ממנו במדויק מבוססים כאן על מקורות פחות ודאיים.",
};

export const bulkSkip: Record<BulkSkipReason, string> = {
  no_value: "אין ערך לאשר",
  already_reviewed: "כבר הוכרע",
  conflict: "יש מחלוקת בין מסמכים",
  always_needs_review: "מחייב אישור אישי",
  low_confidence: "ביטחון נמוך מדי",
};

export const caseType = {
  defence: "הגנה",
  claim: "תביעה",
  label: (value: string | null) =>
    value === "הגנה" ? "תיק הגנה" : value === "תביעה" ? "תיק שיבוב" : "סוג התיק לא ידוע",
};
