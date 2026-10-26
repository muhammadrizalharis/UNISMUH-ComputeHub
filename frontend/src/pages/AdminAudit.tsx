import { AuditTrail } from './Admin'
import { useAuth } from '../lib/auth'

/** Menu admin tersendiri: log aktivitas admin (audit trail) dengan filter & ekspor CSV. */
export default function AdminAudit() {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  return <AuditTrail />
}
