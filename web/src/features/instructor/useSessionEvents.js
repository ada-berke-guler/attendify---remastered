import { useEffect, useRef, useState } from 'react'
import { api, API_BASE } from '../../shared/api'

const EVENT_TYPES = ['attendance.created', 'attendance.removed', 'pending.created', 'pending.resolved', 'qr.rotated']
const BACKOFF_MS = [1000, 2000, 5000, 10000]
// If the SSE "hello" has not arrived by then, a proxy is buffering the stream
// (Cloudflare quick tunnels do), so switch to the WebSocket endpoint.
const SSE_HELLO_TIMEOUT_MS = 5000

// Remembered per tab, so after one fallback we do not wait 5 s on every reconnect.
let preferredTransport = 'sse'

function wsUrl(path) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${API_BASE}${path}`
}

/**
 * Live session events: Server-Sent Events, with a WebSocket fallback.
 *
 * Neither EventSource nor WebSocket can send an Authorization header, so we first
 * trade the access token for a 60 s events token. On every (re)connect `onSync` runs
 * once so the caller can reload the full list: events published while we were
 * disconnected are not replayed.
 */
export function useSessionEvents(sessionId, { onEvent, onSync }) {
  const [status, setStatus] = useState('connecting') // connecting | live | reconnecting
  const handlers = useRef({ onEvent, onSync })
  useEffect(() => {
    handlers.current = { onEvent, onSync }
  })

  useEffect(() => {
    if (!sessionId) return undefined
    let conn = null // { close() }
    let retryTimer = null
    let helloTimer = null
    let attempt = 0
    let closed = false

    function handle(raw) {
      let event
      try {
        event = JSON.parse(raw)
      } catch {
        return
      }
      if (event.type === 'hello') {
        clearTimeout(helloTimer)
        attempt = 0
        setStatus('live')
        handlers.current.onSync?.()
      } else if (EVENT_TYPES.includes(event.type)) {
        handlers.current.onEvent?.(event)
      }
    }

    function openSse(token) {
      const source = new EventSource(`${API_BASE}/sessions/${sessionId}/events?token=${encodeURIComponent(token)}`)
      for (const type of ['hello', ...EVENT_TYPES]) {
        source.addEventListener(type, (e) => handle(e.data))
      }
      source.onerror = () => fail()
      helloTimer = setTimeout(() => {
        preferredTransport = 'ws'
        source.close()
        conn = null
        connect()
      }, SSE_HELLO_TIMEOUT_MS)
      return { close: () => source.close() }
    }

    function openWs(token) {
      const socket = new WebSocket(wsUrl(`/sessions/${sessionId}/ws?token=${encodeURIComponent(token)}`))
      socket.onmessage = (e) => handle(e.data)
      socket.onclose = () => fail()
      return {
        close: () => {
          socket.onclose = null
          socket.close()
        },
      }
    }

    async function connect() {
      if (closed) return
      try {
        const { token } = await api.post(`/sessions/${sessionId}/events-token`)
        if (closed) return
        conn = preferredTransport === 'ws' ? openWs(token) : openSse(token)
      } catch {
        scheduleReconnect()
      }
    }

    function fail() {
      clearTimeout(helloTimer)
      conn?.close()
      conn = null
      scheduleReconnect()
    }

    function scheduleReconnect() {
      if (closed) return
      setStatus('reconnecting')
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
      attempt += 1
      clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, delay)
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      clearTimeout(helloTimer)
      conn?.close()
    }
  }, [sessionId])

  return status
}

/** Re-render every `ms` (clock display). Chained timeouts, no interval. */
export function useNow(ms = 1000, enabled = true) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return undefined
    let timer
    const tick = () => {
      setNow(Date.now())
      timer = setTimeout(tick, ms - (Date.now() % ms))
    }
    timer = setTimeout(tick, ms - (Date.now() % ms))
    return () => clearTimeout(timer)
  }, [ms, enabled])
  return now
}
