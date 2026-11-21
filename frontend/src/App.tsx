import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { streamChat } from './api'
import type { ChatMessage } from './api'
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
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(e?: FormEvent) {
    e?.preventDefault()
    const text = input.trim()
    if (!text || isStreaming) return

    const history: ChatMessage[] = [...messages, { role: 'user', content: text }]
    // Show the user's message plus an empty assistant bubble that fills in as the reply streams.
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
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
            {m.content || (isStreaming && i === messages.length - 1 ? '…' : '')}
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      <form className="composer" onSubmit={send}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type your question…"
          rows={2}
        />
        <button type="submit" disabled={isStreaming || !input.trim()}>
          {isStreaming ? 'Thinking…' : 'Send'}
        </button>
      </form>
    </div>
  )
}

export default App
