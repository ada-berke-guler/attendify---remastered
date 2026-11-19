import { Navigate, Route, Routes } from 'react-router-dom'
import FaceSetup from './pages/FaceSetup'
import Dashboard from './pages/Dashboard'
import QRScan from './pages/QRScan'
import FaceVerify from './pages/FaceVerify'
import Confirmation from './pages/Confirmation'
import Profile from './pages/Profile'
import Schedule from './pages/Schedule'
import Stats from './pages/Stats'

export default function StudentApp() {
  return (
    <Routes>
      <Route index element={<Navigate to="dashboard" replace />} />
      <Route path="face-setup" element={<FaceSetup />} />
      <Route path="dashboard" element={<Dashboard />} />
      <Route path="scan" element={<QRScan />} />
      <Route path="verify" element={<FaceVerify />} />
      <Route path="confirmation" element={<Confirmation />} />
      <Route path="profile" element={<Profile />} />
      <Route path="schedule" element={<Schedule />} />
      <Route path="stats" element={<Stats />} />
      <Route path="*" element={<Navigate to="dashboard" replace />} />
    </Routes>
  )
}
