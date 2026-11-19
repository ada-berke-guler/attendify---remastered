// Where the logged-in user lives. "Remember me" -> localStorage, otherwise sessionStorage
// (survives reloads in the same tab, gone when the tab closes).
const KEY = 'attendify_session'

function read(storage) {
  try {
    return JSON.parse(storage.getItem(KEY))
  } catch {
    return null
  }
}

export function getSession() {
  return read(sessionStorage) || read(localStorage)
}

export function saveSession(session, remember) {
  try {
    clearSession()
    ;(remember ? localStorage : sessionStorage).setItem(KEY, JSON.stringify(session))
  } catch {
    // storage blocked (private mode): the in-memory React state still works for this page
  }
}

export function updateSession(patch) {
  const current = getSession()
  if (!current) return null
  const next = { ...current, ...patch }
  try {
    const remember = read(localStorage) !== null
    ;(remember ? localStorage : sessionStorage).setItem(KEY, JSON.stringify(next))
  } catch {
    // ignore
  }
  return next
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY)
    sessionStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}

export function getToken() {
  return getSession()?.token ?? null
}

export const HOME_BY_ROLE = {
  admin: '/admin/students',
  instructor: '/instructor/dashboard',
  student: '/student/dashboard',
}

export function homeFor(session) {
  if (!session) return '/login'
  if (session.role === 'student' && !session.face_enrolled) return '/student/face-setup'
  return HOME_BY_ROLE[session.role] ?? '/login'
}
