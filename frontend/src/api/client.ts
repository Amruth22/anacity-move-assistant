import type { Community, ConfirmSummary, CopilotAssessment, MoveRequest, Resident } from '../types'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  communities: () => get<Community[]>('/api/communities'),
  residents: (communityId: string) => get<Resident[]>(`/api/communities/${communityId}/residents`),
  requests: (params?: { community_id?: string; status?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString()
    return get<MoveRequest[]>(`/api/requests${qs ? `?${qs}` : ''}`)
  },
  request: (id: string) => get<MoveRequest>(`/api/requests/${id}`),
  residentRequests: (residentId: string) => get<MoveRequest[]>(`/api/residents/${residentId}/requests`),
  adminAction: (id: string, action: string, note: string) =>
    post<MoveRequest>(`/api/requests/${id}/action`, { action, note }),
  copilot: (id: string) => post<CopilotAssessment>(`/api/admin/requests/${id}/copilot`),
  newChatSession: (residentId: string) =>
    post<{ session_id: string }>('/api/chat/session', { resident_id: residentId }),
  uploadDocument: async (reqId: string, docId: string, residentId: string, file: File) => {
    const form = new FormData()
    form.append('resident_id', residentId)
    form.append('file', file)
    const res = await fetch(`/api/requests/${reqId}/documents/${docId}/upload`, {
      method: 'POST',
      body: form,
    })
    if (!res.ok) throw new Error((await res.json()).detail ?? `Upload failed (${res.status})`)
    return res.json() as Promise<MoveRequest>
  },
  verifyDocument: (reqId: string, docId: string) =>
    post<MoveRequest>(`/api/requests/${reqId}/documents/${docId}/verify`),
  completeTask: (reqId: string, itemId: string) =>
    post<MoveRequest>(`/api/requests/${reqId}/tasks/${itemId}/done`),
  confirmRequest: (sessionId: string) =>
    post<{ request_id: string; status: string }>('/api/chat/confirm', { session_id: sessionId }),
  declineRequest: (sessionId: string) =>
    post<{ declined: boolean }>('/api/chat/decline', { session_id: sessionId }),
  documentUrl: (reqId: string, docId: string) => `/api/requests/${reqId}/documents/${docId}/file`,
  docsContent: async () => {
    const res = await fetch('/api/docs-content')
    return res.text()
  },
}

export interface SSEHandlers {
  onText: (delta: string) => void
  onTool: (name: string, label: string) => void
  onConfirm: (summary: ConfirmSummary) => void
  onDone: () => void
  onError: (message: string) => void
}

/** EventSource is GET-only, so we POST with fetch and parse the SSE frames
 *  off the response body ourselves. */
export async function streamChat(sessionId: string, message: string, handlers: SSEHandlers) {
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
    if (!res.ok || !res.body) {
      handlers.onError(`Request failed (${res.status})`)
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const dispatch = (frame: string) => {
      let event = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (!data) return
      const payload = JSON.parse(data)
      if (event === 'text') handlers.onText(payload.delta)
      else if (event === 'tool') handlers.onTool(payload.name, payload.label)
      else if (event === 'confirm') handlers.onConfirm(payload.summary)
      else if (event === 'done') handlers.onDone()
      else if (event === 'error') handlers.onError(payload.message)
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (frame.trim()) dispatch(frame)
      }
    }
  } catch {
    // a dropped connection must never leave the chat input locked
    handlers.onError('The connection dropped mid-reply. Please send that again.')
  }
}
