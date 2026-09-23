// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync } from "node:fs";

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ||
  (existsSync("/.dockerenv") ? "http://backend:8000" : "http://localhost:8000");

// The payload camera (OpenCV webcam capture) only works when the backend
// runs natively on the host — see backend/run_native.ps1. It listens on
// 8001 so it doesn't collide with the Dockerized backend on 8000.
const cameraProxyTarget =
  process.env.VITE_CAMERA_PROXY_TARGET ||
  (existsSync("/.dockerenv") ? "http://host.docker.internal:8001" : "http://localhost:8001");

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: false,
    allowedHosts: true,
    watch: {
      usePolling: true, // required for hot reload on Windows Docker volume mounts (DEF-07)
      interval: 300,
    },
    proxy: {
      "/camera-api": {
        target: cameraProxyTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/camera-api/, "/api"),
      },
      "/api": { target: apiProxyTarget, changeOrigin: true, ws: true },
    },
  },
  resolve: { alias: { "@": "/src" } },
});
