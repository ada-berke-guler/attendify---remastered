import { clearSession, getToken } from './session'

// Same origin in every environment: Caddy in Docker, the Vite proxy in development.
export const API_BASE = '/api/v1'

export class ApiError extends Error {
  constructor(message, status, retryAfter) {
    super(message)
    this.status = status
    this.retryAfter = retryAfter
  }
}

function errorMessage(body, fallback) {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return detail.map((d) => d.msg).join(', ')
  return fallback
}

async function request(method, path, body, { form = false } = {}) {
  const token = getToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  if (body !== undefined && !form) headers['Content-Type'] = 'application/json'

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: form ? body : body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401 && token) {
    clearSession()
    window.location.assign('/login')
    throw new ApiError('Session expired', 401)
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new ApiError(errorMessage(err, res.statusText || 'Request failed'), res.status, res.headers.get('Retry-After'))
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  patch: (path, body) => request('PATCH', path, body),
  delete: (path) => request('DELETE', path),
  form: (path, formData) => request('POST', path, formData, { form: true }),
  loginForm: (username, password) =>
    request('POST', '/auth/login', new URLSearchParams({ username, password }), { form: true }),
}
