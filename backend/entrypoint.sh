#!/bin/sh
# Entrypoint produksi.
#
# Sebelumnya `set -eu; alembic upgrade head; exec "$@"` membuat SATU migration
# gagal = container mati total dan tidak pernah start, sehingga seluruh aplikasi
# (termasuk endpoint yang tidak berhubungan) menjadi 502 sampai deploy diperbaiki.
# Itu yang menjatuhkan produksi dua kali.
#
# Sekarang: migration dicoba dulu. Kalau gagal, kegagalan dicatat dengan jelas,
# lalu aplikasi tetap dijalankan dengan skema yang ada. Endpoint yang tidak
# bergantung pada migration baru tetap melayani, dan masalahnya terlihat di log
# alih-alih berupa blackout total tanpa pesan.
#
# Untuk memaksa perilaku lama (mati kalau migration gagal), set:
#   STRICT_MIGRATIONS=1

set -u

STRICT_MIGRATIONS="${STRICT_MIGRATIONS:-0}"

echo "[entrypoint] menjalankan alembic upgrade head ..."
if alembic upgrade head; then
  echo "[entrypoint] migration selesai."
else
  status=$?
  echo "[entrypoint] !!! ALEMBIC UPGRADE GAGAL (exit $status) !!!"
  echo "[entrypoint] aplikasi akan tetap dijalankan dengan skema yang ada."
  echo "[entrypoint] perbaiki migration lalu deploy ulang; jangan abaikan baris di atas."
  if [ "$STRICT_MIGRATIONS" = "1" ]; then
    echo "[entrypoint] STRICT_MIGRATIONS=1 -> berhenti sesuai permintaan."
    exit "$status"
  fi
fi

exec "$@"
