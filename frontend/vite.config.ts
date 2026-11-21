import type { IncomingMessage } from 'node:http'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import type { ProxyOptions } from 'vite'

const time = () => new Date().toTimeString().slice(0, 8)
const log = (msg: string) => console.log(`${time()} [frontend] ${msg}`)

/** Return the full text on its own lines, indented under the log line. */
function block(text: string): string {
  return text.split(/\r?\n/).map((line) => `\n      ${line}`).join('')
}

/** Collect a stream's text without consuming it (the proxy still pipes it on). */
function tap(stream: IncomingMessage, onEnd: (text: string) => void) {
  const chunks: Buffer[] = []
  stream.on('data', (c: Buffer) => chunks.push(c))
  stream.on('end', () => onEnd(Buffer.concat(chunks).toString('utf8')))
}

/** Log every /api call that the page makes, with the full question and reply. */
function logApiCalls(): ProxyOptions['configure'] {
  return (proxy) => {
    proxy.on('proxyReq', (_proxyReq, req) => {
      const started = Date.now()
      ;(req as IncomingMessage & { started?: number }).started = started
      tap(req, (body) => {
        let detail = ''
        try {
          const msgs = JSON.parse(body).messages as { content: string }[]
          detail = ` messages=${msgs.length} question:${block(msgs[msgs.length - 1]?.content ?? '')}`
        } catch {
          /* not a chat body */
        }
        log(`→ ${req.method} ${req.url}${detail}`)
      })
    })

    proxy.on('proxyRes', (proxyRes, req) => {
      const started = (req as IncomingMessage & { started?: number }).started ?? Date.now()
      tap(proxyRes, (body) => {
        const secs = ((Date.now() - started) / 1000).toFixed(1)
        log(`← ${req.method} ${req.url} ${proxyRes.statusCode} (${secs}s):${block(body)}`)
      })
    })

    proxy.on('error', (err, req) => {
      log(`✗ ${req.method} ${req.url} backend unreachable: ${err.message}`)
    })
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      // The page calls /api/...; Vite forwards it to the backend and logs it here.
      proxy: {
        '/api': { target: backendUrl, changeOrigin: true, configure: logApiCalls() },
      },
    },
  }
})
