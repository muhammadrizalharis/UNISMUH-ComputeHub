/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL backend publik untuk deploy terpisah (mis. Vercel). Kosong = same-origin. */
  readonly VITE_API_BASE_URL?: string
  /** Target proxy /api saat dev (npm run dev). */
  readonly VITE_API_PROXY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
