import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // в dev-режиме проксируем /api на FastAPI (uvicorn main:app)
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
