#!/usr/bin/env bash
# Batch 2 — jalankan bukti runtime sidebar.
# Merender sidebar tiap peran dengan React (react-dom/server) lalu memastikan
# setiap href yang keluar benar-benar punya <Route> di main.jsx dan lolos canAccess.
set -euo pipefail
cd "$(dirname "$0")/.."
npx vite build --config proof/vite.proof.config.js --logLevel warn
node proof/dist/sidebar-proof.js
