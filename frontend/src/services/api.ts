import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
})

export interface CreateCasePayload {
  office_id: string
  created_by: string
  case_type: string
  client_name?: string
}

export interface CreateCaseResponse {
  case_id: string
  status: string
}

export interface UploadDocumentPayload {
  case_id: string
  file: File
  office_id: string
  uploaded_by: string
  document_type?: string
}

export interface UploadDocumentResponse {
  document_id: string
  case_id: string
  original_filename: string
  document_type: string | null
  storage_path: string
  file_url: string
  status: string
}

export async function createCase(payload: CreateCasePayload): Promise<CreateCaseResponse> {
  const form = new FormData()
  form.append('office_id', payload.office_id)
  form.append('created_by', payload.created_by)
  form.append('case_type', payload.case_type)
  if (payload.client_name) form.append('client_name', payload.client_name)

  const { data } = await api.post<CreateCaseResponse>('/cases', form)
  return data
}

export async function uploadDocument(payload: UploadDocumentPayload): Promise<UploadDocumentResponse> {
  const form = new FormData()
  form.append('file', payload.file)
  form.append('office_id', payload.office_id)
  form.append('uploaded_by', payload.uploaded_by)
  if (payload.document_type) form.append('document_type', payload.document_type)

  const { data } = await api.post<UploadDocumentResponse>(`/upload/${payload.case_id}`, form)
  return data
}
