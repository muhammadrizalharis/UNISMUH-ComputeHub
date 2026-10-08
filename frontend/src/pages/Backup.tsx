import BackupRestorePanel from '../components/BackupRestorePanel'
import { useAuth } from '../lib/auth'

/** Menu admin tersendiri: cadangan, rincian isi backup, uji pulih, dan pemulihan. */
export default function Backup() {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  return <BackupRestorePanel />
}
