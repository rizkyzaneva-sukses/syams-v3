import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

/* Konfigurasi khusus BUKTI SIDEBAR (batch 2). Tidak menyentuh vite.config.*
   milik aplikasi; hanya dipakai `proof/run-proof.sh` untuk merender sidebar
   dengan React nyata (react-dom/server) lalu menyisir href yang keluar. */
export default defineConfig({
  plugins: [react()],
  build: {
    ssr: 'proof/sidebar-proof.jsx',
    outDir: 'proof/dist',
    emptyOutDir: true,
    rollupOptions: {external: ['node:fs','node:url','node:path']},
  },
});
