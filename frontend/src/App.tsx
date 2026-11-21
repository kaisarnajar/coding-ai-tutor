import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { streamChat } from './api'
import './App.css'

/**
 * Single question → single answer. No conversation history is kept:
 * each question is sent to the model on its own and replaces the previous one.
 */
function App() {
  const [input, setInput] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)

  async function send(e?: FormEvent) {
    e?.preventDefault()
    const text = input.trim()
    if (!text || isStreaming) return

    setQuestion(text)
    setAnswer('')
    setInput('')
    setIsStreaming(true)

    const appendToAnswer = (chunk: string) => setAnswer((prev) => prev + chunk)

    try {
      // Only the current question is sent; the model sees no earlier messages.
      await streamChat([{ role: 'user', content: text }], appendToAnswer)
    } catch (err) {
      appendToAnswer(`\n\n[Could not reach the backend: ${(err as Error).message}]`)
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
        {!question && <p className="empty">Ask a coding question to get started.</p>}
        {question && <div className="message user">{question}</div>}
        {question && (
          <div className="message assistant">{answer || (isStreaming ? '…' : '')}</div>
        )}
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
