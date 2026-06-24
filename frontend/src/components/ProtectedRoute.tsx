import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { FullScreenSpinner } from './Spinner'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) return <FullScreenSpinner />
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
