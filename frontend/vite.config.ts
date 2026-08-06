// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync } from 'node:fs'

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ||
  (existsSync('/.dockerenv') ? 'http://backend:8000' : 'http://localhost:8000')

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: false,
    allowedHosts: 'all',
    watch: {
      usePolling: true,   // required for hot reload on Windows Docker volume mounts (DEF-07)
      interval: 300,
    },
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true, ws: true },
    },
  },
  resolve: { alias: { '@': '/src' } },
})
