import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import RequireRole from './RequireRole'
import { useAuth } from './AuthContext'
import { useTheme } from './ThemeContext'
import { homeFor } from '../shared/session'
import '../shared/base.css'

// One chunk per role: a student's phone never downloads the admin or instructor bundles.
const Login = lazy(() => import('../features/auth/Login'))
const ForgotPassword = lazy(() => import('../features/auth/ForgotPassword'))
const AdminApp = lazy(() => import('../features/admin/AdminApp'))
const InstructorApp = lazy(() => import('../features/instructor/InstructorApp'))
const StudentApp = lazy(() => import('../features/student/StudentApp'))

function Loading() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 14 }}>
      Loading…
    </div>
  )
}

/** Mobile-first frame used by the auth and student screens. */
function PhoneFrame({ children }) {
  const { theme } = useTheme()
  useEffect(() => {
    document.body.style.background = theme.bg
    return () => {
      document.body.style.background = ''
    }
  }, [theme.bg])
  return <div className="phone-frame">{children}</div>
}

function Home() {
  const { user } = useAuth()
  return <Navigate to={homeFor(user)} replace />
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<PhoneFrame><Login /></PhoneFrame>} />
        <Route path="/forgot-password" element={<PhoneFrame><ForgotPassword /></PhoneFrame>} />
        <Route path="/admin/*" element={<RequireRole role="admin"><AdminApp /></RequireRole>} />
        <Route path="/instructor/*" element={<RequireRole role="instructor"><InstructorApp /></RequireRole>} />
        <Route path="/student/*" element={<RequireRole role="student"><PhoneFrame><StudentApp /></PhoneFrame></RequireRole>} />
        <Route path="*" element={<Home />} />
      </Routes>
    </Suspense>
  )
}
