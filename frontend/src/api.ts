export type Role = 'system' | 'user' | 'assistant'

/** A PDF uploaded to the backend, sent along with a message. */
export interface Attachment {
  file_id: string
  name: string
}

export interface ChatMessage {
  role: Role
  content: string
  attachments?: Attachment[]
}

/**
 * Send the conversation to the backend and call `onChunk` with each piece of
 * the reply as it streams in.
 */
export async function streamChat(
  messages: ChatMessage[],
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  // Relative URL: the Vite dev server forwards /api to the backend (see vite.config.ts).
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Backend returned ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}

/** Upload a PDF to the backend. The model gets its file_id with the next message. */
export async function uploadPdf(file: File): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/uploads', { method: 'POST', body: form })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail ?? `Upload failed (${response.status})`)
  }
  return response.json()
}
