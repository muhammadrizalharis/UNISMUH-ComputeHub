import LinuxAccountsPanel from '../components/LinuxAccountsPanel'
import { useAuth } from '../lib/auth'

/** Menu admin tersendiri: batas cgroup (CPU/RAM) per akun Linux, runtime maupun permanen. */
export default function LinuxLimits() {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  return <LinuxAccountsPanel />
}
