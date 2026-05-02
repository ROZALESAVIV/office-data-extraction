import { useCallback, useRef, useState } from 'react'

const MAX_FILES = 7
const MAX_MB = 20
const MAX_BYTES = MAX_MB * 1024 * 1024

const DOCUMENT_TYPES = [
  { value: 'insurance', label: 'ביטוח / Insurance' },
  { value: 'police_report', label: 'דוח משטרה / Police Report' },
  { value: 'medical_report', label: 'דוח רפואי / Medical Report' },
  { value: 'court_document', label: 'מסמך משפטי / Court Document' },
  { value: 'id_document', label: 'תעודת זהות / ID Document' },
  { value: 'other', label: 'אחר / Other' },
]

export interface SelectedFile {
  file: File
  document_type: string
  error?: string
}

interface Props {
  files: SelectedFile[]
  onChange: (files: SelectedFile[]) => void
}

export default function UploadZone({ files, onChange }: Props) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return
      const next = [...files]

      for (const f of Array.from(incoming)) {
        if (next.length >= MAX_FILES) break

        let error: string | undefined
        if (f.type !== 'application/pdf') error = 'קובץ PDF בלבד / PDF files only'
        else if (f.size > MAX_BYTES) error = `גודל מקסימלי ${MAX_MB}MB`

        next.push({ file: f, document_type: '', error })
      }
      onChange(next)
    },
    [files, onChange],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      addFiles(e.dataTransfer.files)
    },
    [addFiles],
  )

  const removeFile = (idx: number) => {
    onChange(files.filter((_, i) => i !== idx))
  }

  const setDocType = (idx: number, value: string) => {
    const next = [...files]
    next[idx] = { ...next[idx], document_type: value }
    onChange(next)
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`
          cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition-colors
          ${dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'}
          ${files.length >= MAX_FILES ? 'pointer-events-none opacity-50' : ''}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
        <p className="text-3xl mb-2">📄</p>
        <p className="font-semibold text-gray-700">גרור קבצים לכאן או לחץ לבחירה</p>
        <p className="text-sm text-gray-400 mt-1">
          PDF בלבד · עד {MAX_MB}MB לקובץ · עד {MAX_FILES} קבצים
        </p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((sf, idx) => (
            <li
              key={idx}
              className={`flex items-center gap-3 rounded-lg border p-3 text-sm
                ${sf.error ? 'border-red-300 bg-red-50' : 'border-gray-200 bg-white'}`}
            >
              <span className="text-lg">📄</span>
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-gray-800">{sf.file.name}</p>
                {sf.error
                  ? <p className="text-red-500 text-xs mt-0.5">{sf.error}</p>
                  : <p className="text-gray-400 text-xs">{(sf.file.size / 1024 / 1024).toFixed(2)} MB</p>
                }
              </div>

              {!sf.error && (
                <select
                  value={sf.document_type}
                  onChange={(e) => setDocType(idx, e.target.value)}
                  className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-700 bg-white"
                >
                  <option value="">-- סוג מסמך --</option>
                  {DOCUMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              )}

              <button
                type="button"
                onClick={() => removeFile(idx)}
                className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
