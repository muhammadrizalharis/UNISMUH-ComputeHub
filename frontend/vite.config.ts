import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Backend FastAPI (default port 8088). Override lewat VITE_API_PROXY saat dev.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.VITE_API_PROXY || 'http://127.0.0.1:8088'

  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: false,
      proxy: {
        // Semua request /api diteruskan ke backend.
        '/api': { target, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 1200,
    },
  }
})
