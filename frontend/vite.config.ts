import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Server-side only — never expose API_KEY via VITE_* to the browser bundle.
  const env = loadEnv(mode, process.cwd(), '')
  const apiKey = env.API_KEY || process.env.API_KEY || ''

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              // Prefer injected key; strip any client-supplied key.
              proxyReq.removeHeader('x-api-key')
              if (apiKey) {
                proxyReq.setHeader('X-API-Key', apiKey)
              }
            })
          },
        },
      },
    },
  }
})
