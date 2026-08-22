import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// One process, one port in production (spec §17): FastAPI serves `dist`.
// `--dev` runs Vite on 5173 and proxies the API + logo to FastAPI on 8000
// (spec §17). Production is one process on 8420 serving `dist` directly.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/logo.png': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/favicon.png': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
