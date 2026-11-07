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
      // Vite 8 default minify CSS pakai lightningcss (lebih ketat & menolak
      // sebagian selector arbitrary Tailwind). Pertahankan esbuild spt Vite 5.
      cssMinify: 'esbuild',
      chunkSizeWarningLimit: 1200,
      rollupOptions: {
        output: {
          // Bundler baru (Rolldown di Vite 8) mewajibkan manualChunks berupa
          // fungsi, bukan objek. Pemetaan tetap sama seperti sebelumnya.
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (id.includes('monaco-editor') || id.includes('@monaco-editor/react'))
              return 'monaco-vendor'
            if (
              id.includes('/react/') ||
              id.includes('/react-dom/') ||
              id.includes('/react-router') ||
              id.includes('/scheduler/')
            )
              return 'react-vendor'
            if (id.includes('@tanstack/react-query')) return 'query-vendor'
          },
        },
      },
    },
  }
})
