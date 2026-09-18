# BOS SYAMS — ALL-IN V0.2

Versi all-in MVP/developer foundation dari pembicaraan BOS Syams. **Ini aplikasi yang dapat dijalankan, bukan klaim bahwa seluruh detail bisnis sudah production-final.** Bagian yang belum ditetapkan tetap harus dikembangkan tanpa mengarang hard-coded rule.

## Stack
- React + Vite
- FastAPI + SQLAlchemy
- PostgreSQL 16
- JWT role-based login
- Docker Compose
- Nginx frontend proxy
- Caddy HTTPS untuk deployment production

## Area yang sudah disatukan
- Login multi-user / role
- Master Control
- Master Produksi / Morning Priority
- Process Movement / partial WIP
- WIP & Capacity / Forecast
- Shared Order Detail / multi-article
- CMO workspace foundation: Customer, Quotation, Sample/PPM, SPK, demand modules
- CFO foundation: Invoice, Payment, AR/AP, Purchasing, Shipment Finance Gate
- COO foundation: material request, production movement, QC, shipment
- CHRO foundation: Employee, Training, Performance, People Issue
- CEO foundation: Exception, Decision & Action Tracker
- Audit/config data models
- Separate Customer Closed / Financial Closed / Order Closed
- Mandatory backend guard: shipment with outstanding cannot be cleared without CEO approval

## Demo lokal
```bash
cp .env.example .env
docker compose up --build
```
Buka http://localhost:8080

### Menjalankan backend tanpa Docker Compose

Backend memerlukan `DATABASE_URL` yang mengarah ke PostgreSQL yang dapat dijangkau dari proses backend. Buat `backend/.env` (dibaca dari folder tersebut walaupun perintah dijalankan dari folder lain), misalnya:

```dotenv
DATABASE_URL=postgresql+psycopg2://bos:local-development-only@127.0.0.1:5432/bos_syams
```

Contoh ini hanya berlaku jika PostgreSQL berjalan di komputer yang sama dan database/user tersebut sudah dibuat. Untuk database terkelola, gunakan host, kredensial, dan nama database dari penyedia layanan. Nama host `db` hanya tersedia bagi service `app` di jaringan `docker compose` proyek ini. Jika backend dijalankan sebagai container terpisah, `127.0.0.1` menunjuk ke container backend itu sendiri, sehingga gunakan alamat database yang dapat dijangkau dari container tersebut. Atur `DATABASE_URL` di environment deployment; jangan simpan kredensial produksi di repository.

Jika menerima `could not translate host name "db" to address`, periksa apakah backend dijalankan melalui `docker compose up --build` bersama service `db`, atau apakah `DATABASE_URL` pada runtime sudah berisi host database yang benar.

### Akun demo

Seed hanya berjalan saat `APP_ENV=development` **dan** `SEED_DEMO=true`, dan
hanya jika tabel user masih kosong. Password semua akun: `demo123456789`
(minimal 12 karakter — backend menolak password lemah saat `APP_ENV=production`).

| Email | Role |
|---|---|
| ceo@syams.local | CEO |
| cmo.manager@syams.local | CMO_MANAGER |
| cmo.support@syams.local | CMO_SUPPORT |
| cfo.manager@syams.local | CFO_MANAGER |
| finance.support@syams.local | FINANCE_SUPPORT |
| coo.manager@syams.local | COO_MANAGER |
| sample.pic@syams.local | SAMPLE_PIC |
| printing.pic@syams.local | PRINTING_PIC |
| production.pic@syams.local | PRODUCTION_PIC |
| chro.manager@syams.local | CHRO_MANAGER |
| hr.support@syams.local | HR_SUPPORT |
| shipment.admin@syams.local | SHIPMENT_ADMIN |

### Mengisi data demo (customer, order, produksi)

`seed.py` hanya membuat user — tidak ada order/customer. Untuk data transaksi,
gunakan skrip di `scripts/` yang mengisi lewat API publik sehingga seluruh
business rule ikut tervalidasi. Lihat `scripts/README.md`.

## Alur bisnis & urutan gate

Backend menolak lompatan tahap. Aturan ditegakkan di `backend/app/workflow.py`
dan `flow_engine.py`, bukan hanya di UI. Urutan wajibnya:

```
business policy (CEO, sekali saja)
  -> order + artikel (production_route WAJIB diisi)
  -> quotation DRAFT -> APPROVED (CFO)
  -> invoice -> payment -> reconcile -> finance-gate APPROVE (CFO)
  -> BOM -> material request -> purchase order READY (CFO)
  -> production plan APPROVED (COO)
  -> SPK RELEASED (CMO)
  -> process movement per proses -> QC final
  -> shipment: packing PACKED -> finance gate APPROVE (CFO) -> SHIPPED
  -> serah terima fisik DELIVERED (COO) + konfirmasi customer (CMO)
  -> closing: customer (CMO) + operasional (COO) + financial (CFO)
```

Cek posisi order kapan saja lewat `GET /api/orders/{order_id}/flow` — endpoint
ini melaporkan `current_step` beserta alasan setiap langkah berikutnya terblokir.

### Aturan yang mudah terlewat

**`production_route` tidak dapat diubah setelah order dibuat.** Tidak ada
endpoint update artikel. Order tanpa rute tidak akan pernah bisa release SPK;
satu-satunya jalan adalah membuat order baru. Format pemisah yang diterima:
`>`, `→`, atau `->` — contoh `Cutting > Sewing > QC`.

**Kuantitas berjenjang.** Material request harus ≥ (BOM `qty_per_unit` × qty
artikel), dan purchase order harus ≥ material request. Kurang sedikit pun, SPK
release ditolak.

**Status `DELIVERED` dicatat COO_MANAGER** lewat update shipment dari `SHIPPED`
dengan `delivery_date`. Konfirmasi customer oleh CMO_MANAGER tersimpan terpisah;
keduanya diperlukan sebelum customer closing.

**Closing butuh tiga role berbeda.** `customer_close_status` hanya bisa diset
CMO_MANAGER, `operational_close_status` hanya COO_MANAGER, dan
`financial_close_status` hanya CFO_MANAGER (segregation of duties).
`order_close_status` bersifat turunan — jangan dikirim manual.

**Pembayaran invoice bersifat turunan.** `paid_amount` dan `status` invoice
dihitung dari record payment; mengirimnya langsung akan ditolak.

**Order `SAMPLE_ONLY` tidak masuk produksi.** Ditolak di tahap production plan.

## Catatan keamanan

- `/docs`, `/redoc`, dan `/openapi.json` dimatikan saat `APP_ENV=production`
  (`openapi_url=None`, bukan hanya `docs_url`) dan tidak di-fallback ke SPA.
- `GET /api/users` dibatasi ke role yang berwenang menugaskan pekerjaan
  (CEO, CMO Manager/Support, COO Manager, CHRO Manager). Halaman yang
  memakainya tetap berfungsi untuk role lain — daftar assignee dibiarkan kosong.
- Access token disimpan di `sessionStorage`, bukan `localStorage`, sehingga
  token ikut hilang saat tab ditutup. Untuk ketahanan penuh terhadap XSS,
  langkah berikutnya adalah httpOnly cookie + proteksi CSRF.
- Sidebar difilter dengan `canAccess()` yang sama dengan penjaga route, jadi
  menu yang tidak boleh diakses tidak lagi muncul.

## Menggabungkan modul satu-per-satu nanti
Semua modul berada dalam satu repository:
- model/table -> `backend/app/models.py`
- API -> `backend/app/routers/`
- screen -> `frontend/src/pages/`
- routing -> `frontend/src/main.jsx`
- menu role -> `frontend/src/components/Layout.jsx`

Kalau ada modul baru, jangan bikin aplikasi/database terpisah. Tambahkan model + API + page di folder tersebut lalu rebuild Docker.

## Production install
Lihat `INSTALL_SERVER.md`.

## Batas V0.2
Data model & endpoint utama tersedia, tetapi modul accounting double-entry penuh, payroll calculation final, bank reconciliation, tax, document PDF template final, dan formula KPI/SLA/TB yang masih CONFIGURABLE/TBD belum boleh dianggap production-final sampai aturan bisnisnya dikunci.
