import { api } from '../../shared/api'

// Admin screens talk to the same API client as everyone else (relative /api/v1,
// logout on 401). Accounts can only be created with an admin token.

export async function getStudents() {
  const data = await api.get('/admin/users')
  return data.filter(u => u.role === 'student')
}

export async function createStudent(form) {
  return api.post('/auth/register/student', {
    email: form.email,
    first_name: form.first_name,
    last_name: form.last_name,
    role: 'student',
    password: form.password,
    student_number: form.student_number || undefined,  // empty: the API generates one
    department: form.department || undefined,
  })
}

export async function editUser(id, payload) {
  return api.patch(`/admin/users/${id}/edit`, payload)
}

export async function deleteStudent(id) {
  return api.delete(`/admin/users/${id}`)
}

export async function getInstructors() {
  const data = await api.get('/admin/users')
  return data.filter(u => u.role === 'instructor')
}

export async function createInstructor(form) {
  return api.post('/auth/register/instructor', {
    email: form.email,
    first_name: form.first_name,
    last_name: form.last_name,
    role: 'instructor',
    password: form.password,
    department: form.department || undefined,
    title: form.title,
  })
}

export async function deleteInstructor(id) {
  return api.delete(`/admin/users/${id}`)
}

export async function toggleUserStatus(id, _type, isActive) {
  const path = isActive
    ? `/admin/users/${id}/activate`
    : `/admin/users/${id}/deactivate`
  return api.patch(path)
}