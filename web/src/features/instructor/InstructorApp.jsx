import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import Dashboard from './pages/Dashboard'
import Courses from './pages/Courses'
import Sessions from './pages/Sessions'
import LiveSession from './pages/LiveSession'
import Schedule from './pages/Schedule'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import './instructor.css'

export default function InstructorApp() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="courses" element={<Courses />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="sessions/live" element={<LiveSession />} />
        <Route path="sessions/:id/live" element={<LiveSession />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="dashboard" replace />} />
      </Route>
    </Routes>
  )
}
