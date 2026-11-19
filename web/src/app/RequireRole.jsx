import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { HOME_BY_ROLE } from '../shared/session'

/** Logged out -> /login. Wrong role -> that user's own home. */
export default function RequireRole({ role, children }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  if (user.role !== role) {
    return <Navigate to={HOME_BY_ROLE[user.role] ?? '/login'} replace />
  }
  return children
}
