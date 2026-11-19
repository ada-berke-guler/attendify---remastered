import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../../shared/api'
import { useToast } from '../../../app/ToastContext'
import { useNow, useSessionEvents } from '../useSessionEvents'
import {
  Users,
  ChevronDown,
  ArrowLeft,
  RefreshCw,
  Play,
  Square,
  Loader2,
  AlertCircle,
  BookOpen,
  Camera,
  UserCheck,
} from 'lucide-react'

const METHOD_LABEL = { face: 'Face + QR', manual: 'Manual', pending_approved: 'Approved request' }

const AVATAR_COLORS = [
  'bg-primary-600', 'bg-pink-500', 'bg-emerald-500', 'bg-violet-500',
  'bg-orange-500', 'bg-rose-500', 'bg-teal-500', 'bg-cyan-500',
  'bg-amber-500', 'bg-indigo-500', 'bg-sky-500', 'bg-fuchsia-500',
]
function avatarColor(id) {
  const n = typeof id === 'number' ? id : String(id).charCodeAt(0)
  return AVATAR_COLORS[n % AVATAR_COLORS.length]
}
function getInitials(name = '') {
  return name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '??'
}

/* ── Real QR from backend (base64 PNG) ──────────────────────── */
function QRCodeDisplay({ imageB64, fading }) {
  if (!imageB64) {
    return (
      <div className="w-56 h-56 bg-white rounded-2xl flex items-center justify-center mx-auto"
        style={{ opacity: fading ? 0 : 1 }}>
        <Loader2 size={32} className="text-slate-300 animate-spin" />
      </div>
    )
  }
  return (
    <div className="w-56 h-56 bg-white rounded-2xl p-3 shadow-inner mx-auto transition-opacity duration-300"
      style={{ opacity: fading ? 0 : 1 }}>
      <img
        src={`data:image/png;base64,${imageB64}`}
        alt="Attendance QR Code"
        className="w-full h-full object-contain"
      />
    </div>
  )
}

function CountdownRing({ seconds, total }) {
  const r = 52
  const circ = 2 * Math.PI * r
  const filled = (seconds / total) * circ
  const color = seconds <= 5 ? '#ef4444' : '#60a5fa'
  return (
    <svg width="120" height="120" viewBox="0 0 120 120" className="absolute -inset-8 pointer-events-none">
      <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="4" />
      <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="4" strokeLinecap="round"
        strokeDasharray={`${filled} ${circ}`} strokeDashoffset={circ / 4}
        className="transition-all duration-1000" />
    </svg>
  )
}

/* ── Setup Screen ─────────────────────────────────────────────── */
function SetupScreen({ courses, loadingCourses, onStart }) {
  const [courseId,   setCourseId]   = useState('')
  const [starting,   setStarting]   = useState(false)
  const [error,      setError]      = useState('')

  const selectedCourseId = courseId || (courses[0] ? String(courses[0].id) : '')

  async function handleStart() {
    if (!selectedCourseId) { setError('Please select a course.'); return }
    setError('')
    setStarting(true)
    try {
      await onStart({ course_id: Number(selectedCourseId) })
    } catch (err) {
      setError(err.message || 'Failed to start session.')
    } finally {
      setStarting(false)
    }
  }

  const inputCls = 'w-full px-3.5 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary-600'

  return (
    <div className="fade-in max-w-md mx-auto mt-8">
      <div className="card p-8 space-y-6">
        <div className="text-center">
          <div className="w-16 h-16 bg-primary-50 dark:bg-primary-900/30 rounded-3xl flex items-center justify-center mx-auto mb-4">
            <Play size={28} className="text-primary-600" />
          </div>
          <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">Start a New Session</h2>
          <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">Choose a course and begin taking attendance</p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1.5">Course *</label>
            {loadingCourses ? (
              <div className="flex items-center gap-2 text-sm text-slate-400 py-2"><Loader2 size={14} className="animate-spin" /> Loading courses…</div>
            ) : (
              <div className="relative">
                <select
                  value={selectedCourseId}
                  onChange={e => setCourseId(e.target.value)}
                  className={`${inputCls} appearance-none pr-9 cursor-pointer`}
                >
                  {courses.length === 0 && <option value="">No courses — create one first</option>}
                  {courses.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.course_code ?? c.code} – {c.name ?? c.course_name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              </div>
            )}
          </div>

        </div>

        {error && (
          <div className="flex items-center gap-2 text-sm px-3 py-2 rounded-xl" style={{ background: '#fff1f2', color: '#f43f5e' }}>
            <AlertCircle size={14} /> {error}
          </div>
        )}

        <button
          onClick={handleStart}
          disabled={starting || courses.length === 0}
          className="btn-primary w-full justify-center py-3 text-base disabled:opacity-60"
        >
          {starting
            ? <><Loader2 size={16} className="animate-spin" /> Starting…</>
            : <><Play size={16} /> Start Session</>
          }
        </button>
      </div>
    </div>
  )
}

/* ── Find a student by photo (1:N pgvector search) ───────────── */
function IdentifyCard({ sessionId }) {
  const { addToast } = useToast()
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [marking, setMarking] = useState(null)

  async function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setBusy(true)
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('image', file)
      setResult(await api.form(`/sessions/${sessionId}/identify`, fd))
    } catch (err) {
      addToast(err.message || 'Could not search by photo.', 'error')
    } finally {
      setBusy(false)
    }
  }

  async function markPresent(c) {
    setMarking(c.student_id)
    try {
      // The live feed updates itself from the attendance.created event.
      await api.post(`/sessions/${sessionId}/mark-present`, { student_id: c.student_id })
      addToast(`${c.full_name} marked present.`)
      setResult(null)
    } catch (err) {
      addToast(err.message || 'Could not mark present.', 'error')
    } finally {
      setMarking(null)
    }
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
          <UserCheck size={15} className="text-primary-600" /> Manual Attendance
        </h2>
      </div>
      <p className="text-xs text-slate-400 dark:text-slate-500 mb-3">
        Student&apos;s phone not working? Take their photo and pick them from the closest matches in this course.
      </p>
      <input ref={inputRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={handleFile} />
      <button onClick={() => inputRef.current?.click()} disabled={busy}
        className="btn-primary w-full justify-center text-sm disabled:opacity-60">
        {busy ? <><Loader2 size={14} className="animate-spin" /> Searching…</> : <><Camera size={14} /> Find by photo</>}
      </button>
      {result && (
        <div className="mt-3 space-y-2">
          {result.candidates.length === 0 && (
            <p className="text-xs text-slate-400 text-center py-2">No enrolled student has face data yet.</p>
          )}
          {result.candidates.map((c) => (
            <div key={c.student_id} className="flex items-center gap-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl p-2.5">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 truncate">{c.full_name}</p>
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  {c.student_number} · distance {c.distance.toFixed(2)}{c.is_match ? ' · match' : ' · not a match'}
                </p>
              </div>
              {c.already_present ? (
                <span className="text-xs font-semibold text-emerald-600">Present</span>
              ) : (
                <button onClick={() => markPresent(c)} disabled={marking === c.student_id}
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg text-white disabled:opacity-50 ${c.is_match ? 'bg-emerald-600' : 'bg-slate-400'}`}>
                  {marking === c.student_id ? '…' : 'Mark present'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function toFeedEntry(e) {
  const name = e.full_name || `#${e.student_id}`
  return {
    id: e.student_id,
    name,
    method: METHOD_LABEL[e.verification_method] ?? 'Face + QR',
    submittedAt: e.submitted_at ? new Date(e.submitted_at) : new Date(),
    color: avatarColor(e.student_id),
    initials: getInitials(name),
  }
}

/* ── Active Session Screen ────────────────────────────────────── */
export default function LiveSession() {
  const navigate = useNavigate()
  const { id: routeId } = useParams()
  const { addToast } = useToast()

  const [phase,        setPhase]        = useState('loading')   // 'loading' | 'setup' | 'active'
  const [courses,      setCourses]      = useState([])
  const [loadingC,     setLoadingC]     = useState(true)
  const [session,      setSession]      = useState(null)
  const [qr,           setQr]           = useState(null)        // { image_base64, expiresAt, rotate_seconds }
  const [qrGeneration, setQrGeneration] = useState(1)
  const [fading,       setFading]       = useState(false)
  const [feed,         setFeed]         = useState([])          // newest first, one entry per student
  const [ending,       setEnding]       = useState(false)
  const [pendingList,  setPendingList]  = useState([])
  const [resolving,    setResolving]    = useState({})

  const sessionId = session?.id
  const now = useNow(1000, phase === 'active')

  /* ── courses ── */
  useEffect(() => {
    api.get('/courses')
      .then(d => setCourses(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => setLoadingC(false))
  }, [])

  /* ── which session: the one in the URL, else the running one, else setup ── */
  useEffect(() => {
    let cancelled = false
    async function resolve() {
      try {
        let live = null
        if (routeId) {
          live = await api.get(`/sessions/${routeId}`)
          if (live.status !== 'active') {
            addToast('That session is already closed.', 'error')
            live = null
          }
        } else {
          const list = await api.get('/sessions?status=active')
          live = list[0] ?? null
        }
        if (cancelled) return
        if (live) {
          setSession(live)
          setPhase('active')
          if (!routeId) navigate(`/instructor/sessions/${live.id}/live`, { replace: true })
        } else {
          setPhase('setup')
          if (routeId) navigate('/instructor/sessions/live', { replace: true })
        }
      } catch {
        if (!cancelled) setPhase('setup')
      }
    }
    resolve()
    return () => { cancelled = true }
  }, [routeId]) // eslint-disable-line react-hooks/exhaustive-deps

  /* ── QR: fetched on start and on every qr.rotated event ── */
  const loadQr = useCallback(async () => {
    if (!sessionId) return
    setFading(true)
    try {
      const data = await api.get(`/sessions/${sessionId}/qr`)
      setQr({ ...data, expiresAt: Date.now() + data.expires_in * 1000 })
      setQrGeneration(g => g + 1)
    } catch {
      // session closed elsewhere; the next sync will notice
    } finally {
      setTimeout(() => setFading(false), 300)
    }
  }, [sessionId])

  /* ── full reload: on connect and after every reconnect ── */
  const syncAll = useCallback(async () => {
    if (!sessionId) return
    loadQr()
    try {
      const [att, pending] = await Promise.all([
        api.get(`/sessions/${sessionId}/attendance`),
        api.get(`/sessions/${sessionId}/pending`),
      ])
      const entries = (att?.records ?? []).map(r => toFeedEntry({
        student_id: r.student_id,
        full_name: `${r.student?.user?.first_name ?? ''} ${r.student?.user?.last_name ?? ''}`.trim(),
        verification_method: r.verification_method,
        submitted_at: r.submitted_at,
      }))
      entries.sort((a, b) => b.submittedAt - a.submittedAt)
      setFeed(entries)
      setPendingList(Array.isArray(pending) ? pending : [])
    } catch {
      // keep what we have
    }
  }, [sessionId, loadQr])

  const handleEvent = useCallback((event) => {
    const data = event.data ?? {}
    switch (event.type) {
      case 'attendance.created':
        setFeed(list => [toFeedEntry(data), ...list.filter(e => e.id !== data.student_id)])
        setPendingList(list => list.filter(p => p.student_id !== data.student_id))
        break
      case 'attendance.removed':
        setFeed(list => list.filter(e => e.id !== data.student_id))
        break
      case 'pending.created':
        setPendingList(list => [...list.filter(p => p.id !== data.id), data])
        break
      case 'pending.resolved':
        setPendingList(list => list.filter(p => p.id !== data.pending_id))
        break
      case 'qr.rotated':
        loadQr()
        break
      default:
        break
    }
  }, [loadQr])

  const streamStatus = useSessionEvents(phase === 'active' ? sessionId : null, { onEvent: handleEvent, onSync: syncAll })

  /* ── safety net: if a rotation event is missed, the QR endpoint rotates lazily ── */
  const qrCountdown = qr ? Math.max(0, Math.ceil((qr.expiresAt - now) / 1000)) : 0
  const overdue = Boolean(qr) && now - qr.expiresAt > 3000
  useEffect(() => {
    if (overdue) loadQr()
  }, [overdue, loadQr])

  /* ── start session ── */
  const handleStart = useCallback(async ({ course_id }) => {
    const created = await api.post('/sessions', { course_id })
    setSession(created)
    setQr({
      image_base64: created.qr_image_base64,
      rotate_seconds: created.rotate_seconds,
      expiresAt: Date.now() + created.qr_expires_in * 1000,
    })
    setFeed([])
    setPendingList([])
    setPhase('active')
    navigate(`/instructor/sessions/${created.id}/live`, { replace: true })
  }, [navigate])

  /* ── resolve pending ── */
  const handleResolve = async (pendingId, action) => {
    if (!sessionId) return
    setResolving(r => ({ ...r, [pendingId]: true }))
    try {
      await api.patch(`/sessions/${sessionId}/pending/${pendingId}`, { action })
      setPendingList(list => list.filter(p => p.id !== pendingId))
      addToast(action === 'approve' ? 'Student marked present.' : 'Request declined.')
    } catch (err) {
      addToast(err.message || 'Could not resolve request.', 'error')
    } finally {
      setResolving(r => ({ ...r, [pendingId]: false }))
    }
  }

  /* ── end session ── */
  const handleEnd = async () => {
    if (!sessionId) { setPhase('setup'); return }
    setEnding(true)
    try {
      await api.post(`/sessions/${sessionId}/close`)
      addToast('Session ended. Attendance recorded.')
    } catch (err) {
      addToast(err.message || 'Session closed.', 'error')
    } finally {
      setEnding(false)
      setSession(null)
      setQr(null)
      setPhase('setup')
      navigate('/instructor/sessions/live', { replace: true })
    }
  }

  const rotateSeconds = qr?.rotate_seconds ?? 15
  const qrImage = qr?.image_base64 ?? null
  const attendeeCount = feed.length
  const liveUsers = feed.slice(0, 8).map(e => ({
    ...e,
    time: e.submittedAt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
  }))
  const elapsedSec = session?.started_at
    ? Math.max(0, Math.floor((now - new Date(session.started_at).getTime()) / 1000))
    : 0

  /* ── helpers ── */
  const hh = String(Math.floor(elapsedSec / 3600)).padStart(2, '0')
  const mm = String(Math.floor((elapsedSec % 3600) / 60)).padStart(2, '0')
  const ss = String(elapsedSec % 60).padStart(2, '0')

  const activeCourse = courses.find(c => c.id === session?.course_id)
  const courseCode = session?.course_code ?? activeCourse?.code
  const courseName = session?.course_name ?? activeCourse?.name

  return (
    <div className="fade-in">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-slate-400 dark:text-slate-500 mb-6">
        <button onClick={() => navigate('/instructor/dashboard')}
          className="hover:text-primary-600 transition-colors flex items-center gap-1">
          <ArrowLeft size={14} /> Overview
        </button>
        <span>/</span>
        <span className="text-slate-600 dark:text-slate-300 font-medium">Live Session</span>
      </div>

      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-6">Live Session Control</h1>

      {phase === 'loading' && (
        <div className="flex items-center justify-center gap-2 text-sm text-slate-400 py-16">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {/* ── Setup ── */}
      {phase === 'setup' && (
        <SetupScreen courses={courses} loadingCourses={loadingC} onStart={handleStart} />
      )}

      {/* ── Active ── */}
      {phase === 'active' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Panel */}
          <div className="space-y-4">
            {/* Session Status */}
            <div className="card p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-bold text-slate-700 dark:text-slate-200">Session Status</h2>
                <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 px-2.5 py-1 rounded-full">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 blink" /> ACTIVE
                </span>
              </div>
              <div className="text-center mb-4">
                <p className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1">Session Duration</p>
                <p className="font-mono text-4xl font-bold text-slate-800 dark:text-slate-100 tracking-tight">
                  {hh}:{mm}:{ss}
                </p>
                <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Session open until you end it</p>
              </div>
              <div className={`rounded-xl p-3 flex items-center gap-3 transition-colors ${
                qrCountdown <= 5 ? 'bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800' : 'bg-primary-50 dark:bg-primary-900/20'
              }`}>
                <RefreshCw size={16}
                  className={`flex-shrink-0 transition-colors ${qrCountdown <= 5 ? 'text-red-500' : 'text-primary-600'}`}
                  style={{ animation: fading ? 'spin 0.3s linear' : undefined }} />
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-semibold ${qrCountdown <= 5 ? 'text-red-600' : 'text-primary-600'}`}>
                    QR refreshes in <span className="font-mono font-bold">{qrCountdown}s</span>
                  </p>
                  <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                    Generation #{qrGeneration} · Every {rotateSeconds}s · rotated by the server
                  </p>
                </div>
                <div className="w-12 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden flex-shrink-0">
                  <div
                    className={`h-full rounded-full transition-all duration-1000 ${qrCountdown <= 5 ? 'bg-red-500' : 'bg-primary-600'}`}
                    style={{ width: `${(qrCountdown / rotateSeconds) * 100}%` }} />
                </div>
              </div>
            </div>

            {/* Session Details */}
            <div className="card p-5">
              <h2 className="font-bold text-slate-700 dark:text-slate-200 mb-3">Session Details</h2>
              {courseCode && (
                <div className="flex items-center gap-3 p-3 bg-primary-50 dark:bg-primary-900/20 rounded-xl mb-3">
                  <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center flex-shrink-0">
                    <BookOpen size={14} className="text-white" />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-slate-800 dark:text-slate-100">{courseCode}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">{courseName}</p>
                  </div>
                </div>
              )}
              {session?.title && (
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">{session.title}</p>
              )}
            </div>

            {/* Live Feed */}
            <div className="card p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red-500 blink" /> Live Feed
                </h2>
                <span className="text-xs font-semibold text-slate-400 dark:text-slate-500 flex items-center gap-2">
                  <span title={streamStatus === 'live' ? 'Live updates connected' : 'Reconnecting…'}
                    className={`w-1.5 h-1.5 rounded-full ${streamStatus === 'live' ? 'bg-emerald-500' : 'bg-amber-400'}`} />
                  Total: <span className="text-slate-700 dark:text-slate-200">{attendeeCount}</span>
                </span>
              </div>
              {liveUsers.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-4">Waiting for students to check in…</p>
              ) : (
                <div className="space-y-2.5">
                  {liveUsers.map((u, i) => (
                    <div key={`${u.id}-${i}`} className="flex items-center gap-3">
                      <div className={`w-8 h-8 ${u.color} rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0`}>
                        {u.initials}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 leading-tight truncate">{u.name}</p>
                        <p className="text-xs text-slate-400 dark:text-slate-500">{u.method}</p>
                      </div>
                      <span className={`text-xs font-medium flex-shrink-0 ${i === 0 ? 'text-emerald-600' : 'text-slate-400 dark:text-slate-500'}`}>
                        {u.time}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pending Requests */}
            {pendingList.length > 0 && (
              <div className="card p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                    <AlertCircle size={15} className="text-amber-500" /> Pending Requests
                  </h2>
                  <span className="text-xs font-bold text-amber-600 bg-amber-50 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">
                    {pendingList.length}
                  </span>
                </div>
                <div className="space-y-3">
                  {pendingList.map(p => (
                    <div key={p.id} className="bg-slate-50 dark:bg-slate-800/50 rounded-xl p-3">
                      <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 truncate">
                        {p.student_name ?? `Student #${p.student_id}`}
                      </p>
                      <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
                        {p.student_number && `${p.student_number} · `}{p.reason?.replace('_', ' ')}
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleResolve(p.id, 'approve')}
                          disabled={resolving[p.id]}
                          className="flex-1 py-1.5 rounded-lg text-xs font-bold text-white transition-opacity disabled:opacity-50"
                          style={{ background: 'linear-gradient(135deg,#047857,#059669)' }}
                        >
                          {resolving[p.id] ? '…' : 'Approve'}
                        </button>
                        <button
                          onClick={() => handleResolve(p.id, 'decline')}
                          disabled={resolving[p.id]}
                          className="flex-1 py-1.5 rounded-lg text-xs font-bold text-white transition-opacity disabled:opacity-50"
                          style={{ background: 'linear-gradient(135deg,#dc2626,#b91c1c)' }}
                        >
                          {resolving[p.id] ? '…' : 'Decline'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <IdentifyCard sessionId={sessionId} />

            {/* End Session */}
            <button
              onClick={handleEnd}
              disabled={ending}
              className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-2xl text-sm font-bold text-white transition-all disabled:opacity-60"
              style={{ background: 'linear-gradient(135deg,#dc2626,#b91c1c)', boxShadow: '0 4px 16px rgba(220,38,38,.35)' }}
            >
              {ending
                ? <><Loader2 size={15} className="animate-spin" /> Ending…</>
                : <><Square size={15} /> End Session</>
              }
            </button>
          </div>

          {/* QR Panel */}
          <div className="lg:col-span-2 card p-8 flex flex-col items-center justify-center gap-6 min-h-[560px]"
            style={{ background: 'linear-gradient(135deg,#3730a3,#4f46e5)' }}>

            <QRCodeDisplay imageB64={qrImage} fading={fading} />

            <div className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-colors ${
              qrCountdown <= 5 ? 'bg-red-400/30 text-red-100' : 'bg-white/10 text-indigo-200'
            }`}>
              <RefreshCw size={13} className={fading ? 'animate-spin' : ''} />
              {fading ? 'Generating new QR…' : `New QR in ${qrCountdown}s`}
            </div>

            <div className="flex items-center gap-2 bg-white/10 rounded-full px-4 py-2">
              <Users size={14} className="text-indigo-200" />
              <span className="text-white text-sm font-semibold">{attendeeCount} students checked in</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}