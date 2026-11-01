/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app calls the API at VITE_API_BASE_URL directly; the API allows this origin via
// its DEMANDBENCH_CORS_ORIGINS setting.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Tests talk to MSW handlers at the default API address, never to a real server.
    env: { VITE_API_BASE_URL: 'http://localhost:8020' },
    css: false,
  },
})
