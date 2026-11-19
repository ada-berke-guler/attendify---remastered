import { Navigate, Route, Routes } from 'react-router-dom'
import AdminLayout from './AdminLayout'
import StudentsPage from './Students/StudentsPage'
import CreateStudentPage from './Students/CreateStudentPage'
import InstructorsPage from './Instructors/InstructorsPage'
import CreateInstructorPage from './Instructors/CreateInstructorPage'
import './admin.css'

export default function AdminApp() {
  return (
    <Routes>
      <Route element={<AdminLayout />}>
        <Route index element={<Navigate to="students" replace />} />
        <Route path="students" element={<StudentsPage />} />
        <Route path="students/new" element={<CreateStudentPage />} />
        <Route path="instructors" element={<InstructorsPage />} />
        <Route path="instructors/new" element={<CreateInstructorPage />} />
        <Route path="*" element={<Navigate to="students" replace />} />
      </Route>
    </Routes>
  )
}
