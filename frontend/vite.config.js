import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: env.VITE_API_TARGET || 'http://localhost:3000',
          changeOrigin: true,
          cookieDomainRewrite: 'localhost',
        }
      },
      port: parseInt(env.VITE_PORT) || 5173,
      strictPort: true,
      allowedHosts: true,
      hmr: {
        // Tells the browser to connect the WebSocket to Nginx on port 80, 
        // which Nginx will then correctly proxy down to port 55111 internally.
        clientPort: 80 
      }
    }
  }
})
