import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { clearSession, getSession, saveSession, updateSession } from '../shared/session'

const AuthContext = createContext(null)

function initials(name) {
  return (name || '')
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

/** Turn the /auth/login response into the session object every page reads. */
function sessionFromToken(data, email) {
  return {
    token: data.access_token,
    user_id: data.user_id,
    role: data.role,
    full_name: data.full_name,
    name: data.full_name,
    initials: initials(data.full_name),
    email,
    student_number: data.student_number ?? null,
    department: data.department ?? null,
    face_enrolled: data.face_enrolled ?? null,
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(getSession)

  const login = useCallback((data, email, remember) => {
    const session = sessionFromToken(data, email)
    saveSession(session, remember)
    setUser(session)
    return session
  }, [])

  const updateUser = useCallback((patch) => {
    setUser((prev) => {
      const next = { ...prev, ...patch }
      if (patch.full_name) {
        next.name = patch.full_name
        next.initials = initials(patch.full_name)
      }
      updateSession(next)
      return next
    })
  }, [])

  // Full page load on logout: drops role-specific CSS/JS chunks and in-memory state.
  const logout = useCallback(() => {
    clearSession()
    window.location.assign('/login')
  }, [])

  const value = useMemo(
    () => ({ user, token: user?.token ?? null, role: user?.role ?? null, isAuthenticated: !!user, login, logout, updateUser }),
    [user, login, logout, updateUser],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}
