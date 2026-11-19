import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the SPA and the API share an origin through this proxy, exactly like
// Caddy does in Docker. Start the api on :8000 (or set VITE_API_TARGET).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 700,
  },
})
