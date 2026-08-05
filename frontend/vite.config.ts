// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync } from 'node:fs'

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ||
  (existsSync('/.dockerenv') ? 'http://backend:8000' : 'http://localhost:8000')

const dgcaProxyTarget = process.env.VITE_DGCA_PROXY_TARGET || 'https://digitalsky.aai.aero/api'

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
      '/dgca-api': {
        target: dgcaProxyTarget,
        changeOrigin: true,
        rewrite: path => path.replace(/^\/dgca-api/, ''),
      },
    },
  },
  resolve: { alias: { '@': '/src' } },
})
