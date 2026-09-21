"""The fields extracted from a motor-claim referral, and where each comes from.

Derived from the firm's own list, grouped by the source document that is most
authoritative for each field.

PRIORITY: LOWER WINS. 1 is the most authoritative source for a field. The
referral email is priority 1 wherever it carries the field, because it is a
fixed template parsed by regex - no OCR and no ambiguity - so nothing should
ever outrank it.
"""

# (field_key, label_he, data_type, is_required, sort_order)
CASE_FIELDS = [
    # case type - stated verbatim in the referral email ("להגשת הגנה" / "להגשת תביעה").
    # Defence cases have a pleading to read; claim cases do not exist in court yet,
    # so the court fields below stay empty for them by design.
    ("case_type",                 "סוג התיק",                 "text",   True,  1),
    # court
    # Required in defence cases only; enforced per case type by the review
    # readiness gate, not by this flag.
    ("court_name",                "שם בית משפט",              "text",   False, 10),
    ("court_city",                "עיר בית משפט",             "text",   False, 20),
    ("court_procedure_type",      "סוג הליך",                 "text",   False, 30),
    ("claim_amount",              "סכום התביעה",              "number", False, 40),
    # Stamped "נתקבל" on the pleading. Often absent or illegible - the lawyer
    # computes the filing deadline from it, so an empty box is a real answer.
    ("service_date",              "תאריך מסירת כתב התביעה",   "date",   False, 45),
    # COMPUTED, not extracted - see app/reference/deadlines.py. Shown to the
    # lawyer marked as computed, and confirmed like any other field. Court
    # recess is not accounted for.
    ("defence_deadline",          "מועד להגשת כתב הגנה",      "date",   False, 46),
    # plaintiffs (max 2 for now)
    ("plaintiff_1_name",          "שם תובע 1",                "text",   False, 50),
    ("plaintiff_1_id",            "ת.ז. / ח.פ. תובע 1",       "text",   False, 60),
    ("plaintiff_1_address",       "כתובת תובע 1",             "text",   False, 70),
    ("plaintiff_1_phone",         "טלפון תובע 1",             "text",   False, 80),
    ("plaintiff_2_name",          "שם תובע 2",                "text",   False, 90),
    ("plaintiff_2_id",            "ת.ז. / ח.פ. תובע 2",       "text",   False, 100),
    ("plaintiff_2_address",       "כתובת תובע 2",             "text",   False, 110),
    ("plaintiff_2_phone",         "טלפון תובע 2",             "text",   False, 120),
    # Named defendants. In practice some subset of the insured, the driver and
    # the insurer - only the pleading says which, so extract the names.
    ("defendant_1_name",          "שם נתבע 1",                "text",   False, 121),
    ("defendant_2_name",          "שם נתבע 2",                "text",   False, 122),
    ("defendant_3_name",          "שם נתבע 3",                "text",   False, 123),
    # insurer references
    ("direct_claim_number",       "מס' תביעה בישיר",          "text",   True,  130),
    ("direct_policy_number",      "מס' פוליסה בישיר",         "text",   True,  140),
    ("accident_date",             "תאריך התאונה",             "date",   True,  150),
    # our side
    ("insured_plate_number",      "מספר רישוי המבוטח",        "text",   True,  160),
    ("insured_name",              "שם המבוטח שלנו",           "text",   True,  170),
    ("insured_id",                "ת.ז. / ח.פ. המבוטח",       "text",   True,  180),
    ("insured_address",           "כתובת המבוטח",             "text",   False, 190),
    ("insured_phone",             "טלפון המבוטח",             "text",   False, 200),
    ("our_driver_name",           "שם הנהג שלנו",             "text",   True,  210),
    ("our_driver_id",             "ת.ז. הנהג שלנו",           "text",   False, 220),
    ("our_driver_phone",          "טלפון הנהג שלנו",          "text",   False, 230),
    # third party
    ("third_party_plate_number",  "מספר רישוי רכב צד ג'",     "text",   True,  240),
    ("third_party_insurer",       "חברת הביטוח של צד ג'",     "text",   False, 250),
    ("third_party_driver_name",   "שם הנהג של צד ג'",         "text",   False, 260),
    ("third_party_driver_id",     "ת.ז. הנהג של צד ג'",       "text",   False, 270),
    ("third_party_driver_phone",  "טלפון הנהג של צד ג'",      "text",   False, 280),
    ("third_party_owner_name",    "שם הבעלים של רכב צד ג'",   "text",   False, 290),
    ("third_party_owner_id",      "ת.ז. הבעלים של צד ג'",     "text",   False, 300),
    ("third_party_owner_address", "כתובת הבעלים של צד ג'",    "text",   False, 310),
    # amounts (second priority for the firm)
    ("total_paid_by_insurer",     "סה\"כ ששילמה חברת הביטוח", "number", False, 320),
    ("deductible_damage",         "השתתפות עצמית בנזק",       "number", False, 330),
    ("deductible_depreciation",   "השתתפות עצמית בירידת ערך", "number", False, 340),
    ("reinstatement",             "כינון",                    "number", False, 350),
    ("premium_loss",              "הפסד פרמיה",               "number", False, 360),
]

# document_type_key -> [(field_key, priority, hint)]
DOCUMENT_TYPE_FIELDS = {
    # Parsed from a fixed template. Nothing outranks it.
    "referral_email": [
        ("direct_claim_number",  1, None),
        ("direct_policy_number", 1, None),
        ("accident_date",        1, None),
        ("insured_plate_number", 1, None),
        ("insured_name",         1, None),
        ("third_party_insurer",  1, None),
        ("case_type",            1, "המייל אומר במפורש 'להגשת הגנה' או 'להגשת תביעה'"),
    ],
    "statement_of_claim": [
        ("court_name",           10, "בית המשפט מופיע בכותרת העמוד הראשון"),
        ("court_city",           10, "העיר מופיעה לצד שם בית המשפט בכותרת"),
        ("court_procedure_type", 10, "לרוב ת.א. או תאד\"מ, בכותרת ליד מספר התיק"),
        ("claim_amount",         10, "סכום הקרן הנתבע, ללא ריבית והוצאות"),
        ("plaintiff_1_name",     10, "התובע הראשון בכותרת. שים לב: המבוטח שלנו הוא הנתבע, לא התובע"),
        ("plaintiff_1_id",       10, "ת.ז. או ח.פ. לצד שם התובע"),
        ("plaintiff_1_address",  10, None),
        ("plaintiff_1_phone",    10, None),
        ("plaintiff_2_name",     10, "רק אם יש תובע שני"),
        ("plaintiff_2_id",       10, None),
        ("plaintiff_2_address",  10, None),
        ("plaintiff_2_phone",    10, None),
        ("defendant_1_name",     10, "הנתבעים בכותרת. לרוב המבוטח, הנהג וחברת הביטוח - אך לא תמיד כולם"),
        ("defendant_2_name",     10, None),
        ("defendant_3_name",     10, None),
        ("service_date",         10, "חותמת 'נתקבל' על העמוד הראשון. לרוב חותמת גומי, לפעמים חסרה או מטושטשת"),
    ],
    "policy_schedule": [
        ("insured_name",           50, None),
        ("insured_id",             10, None),
        ("insured_address",        10, None),
        ("insured_phone",          10, None),
        ("insured_plate_number",   50, None),
        ("direct_policy_number",   50, None),
        ("premium_loss",           20, None),
    ],
    "digital_report_form": [
        ("accident_date",            50, None),
        ("our_driver_name",          10, "הנהג בפועל, שאינו בהכרח המבוטח - במיוחד כשהמבוטח הוא חברה"),
        ("our_driver_id",            10, None),
        ("our_driver_phone",         10, None),
        ("third_party_plate_number", 10, None),
        ("third_party_driver_name",  10, None),
        ("third_party_driver_id",    10, None),
        ("third_party_driver_phone", 10, None),
    ],
    "payments_to_claimant": [
        ("total_paid_by_insurer",   10, "הסכום הכולל ששולם"),
        ("deductible_damage",       10, "יכול להיות 0 - 0 אינו כמו 'לא נמצא'"),
        ("deductible_depreciation", 10, "יכול להיות 0"),
        ("reinstatement",           10, "יכול להיות 0"),
    ],
    # The registry query outranks a photographed licence, which can be out of date.
    "vehicle_registry_data": [
        ("third_party_owner_name",    5, "שאילתה רשמית - המקור הסמכותי לבעלות"),
        ("third_party_owner_id",      5, None),
        ("third_party_owner_address", 5, None),
        ("third_party_plate_number",  5, None),
    ],
    "vehicle_licence": [
        ("third_party_owner_name",    20, "הבעלים הרשום ברשיון. עלול להיות לא מעודכן"),
        ("third_party_owner_id",      20, None),
        ("third_party_owner_address", 20, None),
        ("third_party_plate_number",  20, None),
    ],
    # Claim (subrogation) cases have no pleading. These carry the party details
    # instead. The amount claimed is deliberately NOT mapped - it is not stated
    # in a form the model can read reliably, so it stays a manual entry.
    "subrogation_letter": [
        ("plaintiff_1_name",         20, "בתיק שיבוב התובע הוא המבוטח שלנו או חברת הביטוח"),
        ("plaintiff_1_id",           20, None),
        ("third_party_owner_name",   30, None),
        ("third_party_insurer",      30, None),
    ],
    "loss_claim_for_signature": [
        ("insured_name",    30, None),
        ("insured_id",      30, None),
        ("insured_address", 30, None),
    ],
    "loss_confirmation": [
        ("insured_name", 40, None),
        ("insured_id",   40, None),
    ],
    "appraiser_report": [
        ("third_party_plate_number", 60, None),
        ("accident_date",            60, None),
    ],
    "claims_status": [
        ("direct_claim_number",  40, None),
        ("direct_policy_number", 40, None),
        ("accident_date",        40, None),
    ],
    "events_detail": [
        ("direct_claim_number", 40, None),
        ("accident_date",       40, None),
    ],
}
