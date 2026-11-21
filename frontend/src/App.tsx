import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import { streamChat, uploadPdf } from './api'
import type { Attachment, ChatMessage } from './api'
import './App.css'

/**
 * Chat page. The conversation is kept in browser memory (React state) only:
 * every question is sent together with all earlier messages so the model has
 * context. A page refresh clears it.
 */
function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  // PDFs uploaded but not sent yet; they go out with the next message.
  const [pending, setPending] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(e?: FormEvent) {
    e?.preventDefault()
    const text = input.trim() || (pending.length ? 'Save this PDF.' : '')
    if (!text || isStreaming || uploading) return

    const userMessage: ChatMessage = { role: 'user', content: text }
    if (pending.length) userMessage.attachments = pending
    const history: ChatMessage[] = [...messages, userMessage]
    // Show the user's message plus an empty assistant bubble that fills in as the reply streams.
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
    setPending([])
    setIsStreaming(true)

    const appendToReply = (chunk: string) =>
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        next[next.length - 1] = { ...last, content: last.content + chunk }
        return next
      })

    try {
      await streamChat(history, appendToReply)
    } catch (err) {
      appendToReply(`\n\n[Could not reach the backend: ${(err as Error).message}]`)
    } finally {
      setIsStreaming(false)
    }
  }

  async function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // so picking the same file again still triggers onChange
    if (!file) return
    setUploadError('')
    setUploading(true)
    try {
      const attachment = await uploadPdf(file)
      setPending((prev) => [...prev, attachment])
    } catch (err) {
      setUploadError((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a new line.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Coding AI Tutor</h1>
      </header>

      <main className="messages">
        {messages.length === 0 && (
          <p className="empty">Ask a coding question to get started.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            {m.attachments?.map((a) => (
              <div key={a.file_id} className="file-chip">📄 {a.name}</div>
            ))}
            {m.content || (isStreaming && i === messages.length - 1 ? '…' : '')}
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      {(pending.length > 0 || uploading || uploadError) && (
        <div className="attachments">
          {pending.map((a) => (
            <span key={a.file_id} className="file-chip">
              📄 {a.name}
              <button
                type="button"
                aria-label={`Remove ${a.name}`}
                onClick={() => setPending((prev) => prev.filter((p) => p.file_id !== a.file_id))}
              >
                ✕
              </button>
            </span>
          ))}
          {uploading && <span className="file-chip">Uploading…</span>}
          {uploadError && <span className="upload-error">{uploadError}</span>}
        </div>
      )}

      <form className="composer" onSubmit={send}>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={onPickFile}
        />
        <button
          type="button"
          className="attach"
          title="Attach a PDF"
          aria-label="Attach a PDF"
          disabled={isStreaming || uploading}
          onClick={() => fileRef.current?.click()}
        >
          📎
        </button>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type your question…"
          rows={2}
        />
        <button
          type="submit"
          disabled={isStreaming || uploading || (!input.trim() && pending.length === 0)}
        >
          {isStreaming ? 'Thinking…' : 'Send'}
        </button>
      </form>
    </div>
  )
}

export default App
