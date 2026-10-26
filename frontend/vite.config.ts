import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 5180,
    // /etc/hosts names (veritium.lab) so the keychain keeps each project's
    // credentials apart instead of pooling them under localhost.
    allowedHosts: ['.lab'],
    proxy: {
      // Backend runs on :8010 in this project's convention (see
      // scripts/*.py, README) — 8000/5173 defaults collide with other
      // local projects on this machine.
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
        rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
      },
    },
  },
})
