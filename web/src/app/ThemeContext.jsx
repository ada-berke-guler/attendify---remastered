import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { darkTheme, lightTheme } from '../shared/tokens'

const ThemeContext = createContext(null)
const KEY = 'attendify_theme'

function initialDark() {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved) return saved === 'dark'
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  } catch {
    return false
  }
}

/**
 * One theme for every role.
 *  - Instructor pages use Tailwind's `dark` class and { isDark, toggle }.
 *  - Student pages use inline style tokens { theme, toggleTheme }.
 */
export function ThemeProvider({ children }) {
  const [isDark, setIsDark] = useState(initialDark)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    document.documentElement.style.colorScheme = isDark ? 'dark' : 'light'
    try {
      localStorage.setItem(KEY, isDark ? 'dark' : 'light')
    } catch {
      // ignore
    }
  }, [isDark])

  const value = useMemo(() => {
    const toggle = () => setIsDark((v) => !v)
    return { isDark, toggle, toggleTheme: toggle, theme: isDark ? darkTheme : lightTheme }
  }, [isDark])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(ThemeContext)
