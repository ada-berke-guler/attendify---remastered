import { createContext, useCallback, useContext, useState } from 'react'
import { AlertCircle, CheckCircle, X } from 'lucide-react'

const ToastContext = createContext(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  return useContext(ToastContext)
}

// Inline styles on purpose: this renders on every route, and Tailwind is only
// loaded with the instructor bundle.
const stack = {
  position: 'fixed', bottom: 20, right: 20, zIndex: 100,
  display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
}
const toastStyle = (type) => ({
  display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', borderRadius: 16,
  boxShadow: '0 10px 25px rgba(0,0,0,.15)', fontSize: 14, fontWeight: 600, pointerEvents: 'auto',
  color: '#fff', background: type === 'success' ? '#059669' : '#ef4444', fontFamily: "'DM Sans', sans-serif",
})
const closeStyle = { marginLeft: 4, opacity: 0.7, background: 'none', border: 0, color: 'inherit', cursor: 'pointer', padding: 0 }

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const removeToast = useCallback((id) => setToasts((prev) => prev.filter((t) => t.id !== id)), [])

  const addToast = useCallback(
    (message, type = 'success') => {
      const id = `${Date.now()}-${Math.random()}`
      setToasts((prev) => [...prev, { id, message, type }])
      setTimeout(() => removeToast(id), 3500)
    },
    [removeToast],
  )

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div style={stack} role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} style={toastStyle(toast.type)}>
            {toast.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
            {toast.message}
            <button onClick={() => removeToast(toast.id)} style={closeStyle} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
