import MonitoringPanel from '../components/MonitoringPanel'
import { useAuth } from '../lib/auth'

/** Halaman Observability — metrik Prometheus/Grafana, khusus administrator utama. */
export default function Observability() {
  const { user } = useAuth()
  if (!user?.is_superadmin) {
    return (
      <div className="card-pad text-rose-600">
        Akses ditolak (administrator utama saja).
      </div>
    )
  }
  return <MonitoringPanel />
}
