import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

import {
  api,
  clearToken,
  getToken,
  setSession,
  ssoLogoutUrl,
  SSO_SESSION_KEY,
  UNAUTHORIZED_EVENT,
} from './api'
import { clearNotebookDrafts } from './notebookDrafts'
import type { User } from './types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string, gate?: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      setUser(await api.me())
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUser()
  }, [loadUser])

  useEffect(() => {
    const handler = () => setUser(null)
    window.addEventListener(UNAUTHORIZED_EVENT, handler)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler)
  }, [])

  const login = useCallback(async (email: string, password: string, gate?: string) => {
    const token = await api.login(email, password, gate)
    setSession(token)
    setUser(await api.me())
  }, [])

  const logout = useCallback(() => {
    // Bersihkan sesi di SERVER memakai token yang masih berlaku: hentikan kernel
    // dulu, lalu hapus session_token (logout sungguhan), BARU buang token lokal.
    void (async () => {
      try {
        await api.shutdownMyInteractiveSessions()
      } catch {
        /* abaikan */
      }
      try {
        await api.logout()
      } catch {
        /* abaikan */
      }
      clearToken()
      clearNotebookDrafts()
      setUser(null)
      // Terakhir: akhiri sesi di server SSO juga, lalu ia memulangkan kita ke
      // /welcome. Kalau tidak, sesi SSO tetap hidup dan pemakai berikutnya di
      // komputer yang sama akan ikut masuk sebagai akun ini.
      const masukLewatSso = sessionStorage.getItem(SSO_SESSION_KEY) === '1'
      sessionStorage.removeItem(SSO_SESSION_KEY)
      if (masukLewatSso) window.location.assign(ssoLogoutUrl())
    })()
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh: loadUser }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth harus dipakai di dalam <AuthProvider>')
  return ctx
}
