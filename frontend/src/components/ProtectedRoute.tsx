import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { LOCAL_LOGIN_KEY } from '../lib/api'
import { FullScreenSpinner } from './Spinner'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) return <FullScreenSpinner />
  if (!user) {
    return <Navigate to={sessionStorage.getItem(LOCAL_LOGIN_KEY) === '1' ? '/welcome/user' : '/welcome'} replace />
  }
  return <>{children}</>
}
