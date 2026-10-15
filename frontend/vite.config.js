import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Host tunnel yang diizinkan mengakses dev server (Cloudflare tunnel QC).
    // Tanpa ini Vite menolak request ber-Host asing dengan 403.
    allowedHosts: ['.maulanacorp.biz.id', 'localhost'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
