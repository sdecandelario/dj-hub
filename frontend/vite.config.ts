import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs on 127.0.0.1:8000 (make dev); Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
})
