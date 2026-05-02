import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import UploadZone from '../components/UploadZone'
import type { SelectedFile } from '../components/UploadZone'
import { createCase, uploadDocument } from '../services/api'

const CASE_TYPES = [
  { value: 'car_accident', label: 'תאונת דרכים / Car Accident' },
  { value: 'work_injury', label: 'תאונת עבודה / Work Injury' },
  { value: 'medical_negligence', label: 'רשלנות רפואית / Medical Negligence' },
  { value: 'property_damage', label: 'נזק לרכוש / Property Damage' },
  { value: 'other', label: 'אחר / Other' },
]

// TODO: replace with values from JWT auth once auth slice is implemented
const DEV_OFFICE_ID = '00000000-0000-0000-0000-000000000001'
const DEV_USER_ID = '00000000-0000-0000-0000-000000000002'

export default function UploadPage() {
  const navigate = useNavigate()

  const [caseType, setCaseType] = useState('')
  const [clientName, setClientName] = useState('')
  const [files, setFiles] = useState<SelectedFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validFiles = files.filter((f) => !f.error)
  const canSubmit = caseType && validFiles.length > 0 && !loading

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!canSubmit) return
    setLoading(true)
    setError(null)

    try {
      const { case_id } = await createCase({
        office_id: DEV_OFFICE_ID,
        created_by: DEV_USER_ID,
        case_type: caseType,
        client_name: clientName || undefined,
      })

      await Promise.all(
        validFiles.map((sf) =>
          uploadDocument({
            case_id,
            file: sf.file,
            office_id: DEV_OFFICE_ID,
            uploaded_by: DEV_USER_ID,
            document_type: sf.document_type || undefined,
          }),
        ),
      )

      navigate(`/review/${case_id}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'שגיאה בהעלאה / Upload failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center pt-16 px-4" dir="rtl">
      <div className="w-full max-w-2xl">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">פתיחת תיק חדש</h1>
        <p className="text-gray-500 mb-8">העלה מסמכים ומלא פרטים בסיסיים</p>

        <form onSubmit={handleSubmit} className="space-y-6 bg-white rounded-2xl shadow-sm border border-gray-100 p-8">

          {/* Case type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">סוג תיק *</label>
            <select
              value={caseType}
              onChange={(e) => setCaseType(e.target.value)}
              required
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">בחר סוג תיק...</option>
              {CASE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Client name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">שם לקוח</label>
            <input
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="ישראל ישראלי"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* File upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">מסמכים *</label>
            <UploadZone files={files} onChange={setFiles} />
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white
              hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'מעלה...' : 'העלה ופתח תיק'}
          </button>
        </form>
      </div>
    </div>
  )
}
