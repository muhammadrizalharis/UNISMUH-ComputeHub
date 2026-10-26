import { OllamaKeysPanel } from './Admin'
import { useAuth } from '../lib/auth'

/** Menu admin tersendiri: kelola API key akses Ollama untuk pihak luar (OpenCode dll.). */
export default function OllamaAccess() {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <div className="card-pad text-rose-600">Akses ditolak (admin saja).</div>
  }
  return <OllamaKeysPanel />
}
