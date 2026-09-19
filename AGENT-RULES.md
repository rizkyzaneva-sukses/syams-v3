# ATURAN KOORDINASI — WAJIB DIBACA SEBELUM BEKERJA

Repo: `/tmp/final-syam` (branch `master`). Ini repo bersama: **10 agent bekerja paralel**.
Melanggar aturan ini = kerjaan agent lain hilang. Baca sampai habis.

## 1. FILE YANG DILARANG KAMU SENTUH (dipakai agent lain / dikawal orkestrator)

JANGAN edit file-file ini, sekalipun kelihatannya perlu:

- `backend/app/models.py`            <- SEMUA model baru ditambahkan oleh orkestrator
- `backend/app/routers/modules.py`   <- router pusat, paling rawan konflik
- `backend/app/schemas.py`
- `backend/app/workflow.py`
- `backend/app/audit.py`
- `backend/migrations/versions/*`    <- migration ditulis oleh orkestrator
- `frontend/src/components/Layout.jsx`
- `frontend/src/business.js`
- `frontend/src/main.jsx`
- `frontend/src/api.js`

Kalau pekerjaanmu BUTUH perubahan di file itu, JANGAN edit sendiri.
Tulis kebutuhanmu di `/tmp/final-syam/REQUESTS/<domain>.md` dengan format:

```
## Butuh: <judul singkat>
File   : backend/app/models.py
Alasan : <kenapa>
Isi    : <kode/kolom yang diminta, sedetail mungkin>
```

Lalu lanjutkan bagian lain yang tidak bergantung pada itu.

## 2. FILE YANG BOLEH KAMU BUAT/EDIT

- File BARU di `backend/app/routers/<domain>_*.py` (router baru)
- File BARU di `frontend/src/pages/<Domain>*.jsx`
- File BARU di `frontend/src/<domain>*.js`
- File BARU di `backend/tests/test_<domain>*.py`
- File BARU di `frontend/tests/<domain>*.test.mjs`

Buat file BARU sebanyak mungkin. Menyentuh file yang sudah ada = risiko konflik.

## 3. CARA MENDAFTARKAN ROUTER BARU

JANGAN edit `backend/app/main.py`. Orkestrator yang akan mendaftarkan router-mu.
Di `REQUESTS/<domain>.md` tulis:

```
## Butuh: daftarkan router
File   : backend/app/main.py
Isi    : from .routers.<modul> import router as <nama>_router  (prefix <prefix>)
```

Selama router belum didaftarkan, uji router-mu langsung dengan `TestClient(app)` setelah
memanggil `app.include_router(...)` di file tes kamu sendiri. Jadi kamu tetap bisa
membuktikan kodenya jalan tanpa menunggu orkestrator.

## 4. CARA MENAMBAH KOLOM/TABEL DB

JANGAN bikin migration sendiri dan JANGAN edit `models.py`.
Tulis spesifikasi di `REQUESTS/<domain>.md`:

```
## Butuh: tabel/kolom baru
Tabel  : shipment_checks
Kolom  : id, shipment_fk (FK shipments.id), result (str), note (text), created_at
Index  : shipment_fk
Backfill: <ada/tidak, dan kenapa>
```

## 5. UJI WAJIB SEBELUM COMMIT

Backend (venv sudah siap):
```
cd /tmp/final-syam/backend && /tmp/bosvenv/bin/python -m pytest -q
```
Frontend:
```
cd /tmp/final-syam/frontend && npm run build 2>&1 | tail -5 && npm test 2>&1 | tail -8
```

**PENTING:** PostgreSQL berbeda dari SQLite. Jangan menulis migration (tugas orkestrator),
tapi kalau kamu memakai query mentah, hindari pola yang gagal di PostgreSQL:
- jangan kirim `sa.func.*` sebagai parameter bind
- jangan kirim angka `1`/`0` untuk kolom boolean (pakai `True`/`False`)
- nama revision/id maksimal 32 karakter

## 6. COMMIT (JANGAN PUSH)

Commit HANYA file milikmu. Jangan `git add -A` (bisa menyapu kerjaan agent lain).

```
git add <file-1> <file-2>
git -c user.name="Shaff Development" -c user.email="shaffdevelopment@gmail.com" \
    commit -m "feat(<domain>): <ringkas> (revisi #<id>)"
```

**JANGAN `git push`.** Orkestrator yang memverifikasi lalu push.

## 7. LAPORAN AKHIR

Laporkan dengan jujur:
- daftar file yang dibuat/diubah
- hash commit
- OUTPUT ASLI `pytest` dan `npm test` (tempel, jangan diringkas jadi "lulus")
- isi `REQUESTS/<domain>.md` (kalau ada)
- apa yang BELUM selesai dan kenapa
- kalau ada tes yang gagal, sebutkan — jangan disembunyikan
