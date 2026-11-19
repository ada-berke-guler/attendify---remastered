import { useEffect, useRef, useState } from 'react'
import { api, API_BASE } from '../../shared/api'

const EVENT_TYPES = ['attendance.created', 'attendance.removed', 'pending.created', 'pending.resolved', 'qr.rotated']
const BACKOFF_MS = [1000, 2000, 5000, 10000]

/**
 * Live session events over Server-Sent Events.
 *
 * EventSource cannot send an Authorization header, so we first trade the access token
 * for a 60 s events token. On every (re)connect `onSync` runs once so the caller can
 * reload the full list: anything published while we were disconnected is not replayed.
 */
export function useSessionEvents(sessionId, { onEvent, onSync }) {
  const [status, setStatus] = useState('connecting') // connecting | live | reconnecting
  const handlers = useRef({ onEvent, onSync })
  useEffect(() => {
    handlers.current = { onEvent, onSync }
  })

  useEffect(() => {
    if (!sessionId) return undefined
    let source = null
    let retryTimer = null
    let attempt = 0
    let closed = false

    async function connect() {
      if (closed) return
      try {
        const { token } = await api.post(`/sessions/${sessionId}/events-token`)
        if (closed) return
        source = new EventSource(`${API_BASE}/sessions/${sessionId}/events?token=${encodeURIComponent(token)}`)
      } catch {
        scheduleReconnect()
        return
      }
      source.addEventListener('hello', () => {
        attempt = 0
        setStatus('live')
        handlers.current.onSync?.()
      })
      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (e) => {
          try {
            handlers.current.onEvent?.(JSON.parse(e.data))
          } catch {
            // ignore malformed frames
          }
        })
      }
      source.onerror = () => {
        source?.close()
        source = null
        scheduleReconnect()
      }
    }

    function scheduleReconnect() {
      if (closed) return
      setStatus('reconnecting')
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
      attempt += 1
      retryTimer = setTimeout(connect, delay)
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      source?.close()
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
