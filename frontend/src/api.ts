export type Role = 'system' | 'user' | 'assistant'

export interface ChatMessage {
  role: Role
  content: string
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
