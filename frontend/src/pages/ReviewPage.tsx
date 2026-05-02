import { useParams } from 'react-router-dom'

export default function ReviewPage() {
  const { caseId } = useParams()
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center" dir="rtl">
      <div className="text-center">
        <p className="text-2xl mb-2">✅</p>
        <h1 className="text-xl font-bold text-gray-800">המסמכים הועלו בהצלחה</h1>
        <p className="text-sm text-gray-400 mt-1">תיק: {caseId}</p>
        <p className="text-sm text-gray-500 mt-4">עמוד הסקירה יפותח בסלייס 5</p>
      </div>
    </div>
  )
}
