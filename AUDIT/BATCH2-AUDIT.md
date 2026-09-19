# AUDIT BATCH 2 — QA/AUDIT INDEPENDEN

Auditor: independent audit agent (batch 2 QA)
Repo: `/tmp/final-syam` — branch `feat/revisi-batch2`
HEAD at audit close: `3b1384f` (`feat(sidebar): menu untuk 11 halaman baru ...`)
Dilarang: mengubah kode produksi. Kepatuhan: **dipatuhi** — satu-satunya file yang
saya tambahkan adalah `backend/tests/test_audit_batch2_endpoints.py`. Semua mutasi
sementara dipulihkan byte-identik (diverifikasi dengan `diff`).

> Catatan penting: 9 agent lain bekerja **paralel dan aktif** selama audit ini
> (working tree berubah tiap beberapa menit). Semua temuan di bawah dipisahkan
> dengan jelas antara **(A) ter-commit** dan **(B) working-tree/uncommitted**.

---

## RINGKASAN EKSEKUTIF

| # | Temuan | Kelas | Bukti |
|---|--------|-------|-------|
| 1 | `GET /api/hr/employees-summary` → **HTTP 500** saat `join_date` NULL (regresi integrasi model) | B — working tree | traceback `hr_employees.py:130` |
| 2 | `977308a` ("daftarkan 10 router") **tidak bisa di-import** — `ImportError` | A — ter-commit | `ImportError: cannot import name 'sample_lifecycle'` |
| 3 | 2 halaman frontend baru **tidak didaftarkan** (`CEOCompanyPerformance.jsx`, `CEOOverride.jsx`) | B — working tree | orphan import scan |
| 4 | 3 halaman orphan **pre-existing** (`ModuleDashboard`, `OrderCreate`, `Workspace`) | A — warisan | git log |

**Tidak ditemukan:** hash commit palsu, klaim versi tool palsu, klaim runner palsu,
atau tes yang tetap hijau saat fiturnya dibatalkan. Semua angka klaim yang saya uji
di batch 2 **terbukti benar** (lihat §3).

---

## 1. KESAHIHAN TES — MUTATION TESTING

Metode: batalkan perbaikan/fitur di salinan, jalankan tes, pulihkan byte-identik
(`/tmp/audit-scratch/mutate.py`, restore di `finally`, verifikasi `diff`).

| Fitur yang dimutasi | File | Tes | Hasil |
|---|---|---|---|
| Imutabilitas sample (keputusan buyer) | `workflow.py:468-474` → `elif False` | `test_sample_immutability.py` | ✅ **DETECTED** (1 failed, 2 passed) |
| RBAC view gate Sample PIC | `sample_work.py:142` → `if False` | `test_sample_work.py` | ✅ DETECTED (2 failed) |
| RBAC view gate CMO Manager | `cmo_manager.py:62` → `if False` | `test_cmo_manager.py` | ✅ DETECTED (1 failed) |
| RBAC view gate Sample lifecycle | `sample_lifecycle.py:111` → `if False` | `test_sample_lifecycle.py` | ✅ DETECTED (2 failed) |
| RBAC gate CFO receivables | `cfo_receivables.py:328` → `if False` | `test_cfo_receivables.py` | ✅ DETECTED (1 failed) |
| RBAC gate CFO costing | `cfo_costing.py:51` → `if False` | `test_cfo_costing.py` | ✅ DETECTED (5 failed) |
| RBAC gate HR employees | `hr_employees.py` `require_roles` → `get_current_user` | `test_hr_employees.py` | ✅ DETECTED (error) |
| RBAC gate COO execution | `coo_execution.py` `require_roles` → `get_current_user` | `test_coo_execution.py` | ✅ DETECTED (1 failed) |
| RBAC read gate printing_ops | `printing_ops.py:457+` `_require(...)` dihapus | `test_printing_ops.py` | ✅ DETECTED (1 failed) |

**Kesimpulan: 9/9 mutasi terdeteksi. Tidak ada tes palsu (= selalu hijau) di batch 2.**

Pola khusus klaim orkestrator di commit `3eab0a1` ("dengan perbaikan dibatalkan,
`test_revision_with_buyer_decision_is_immutable` GAGAL") — **saya reproduksi sendiri
dan klaim itu BENAR**:
```
FAILED tests/test_sample_immutability.py::test_revision_with_buyer_decision_is_immutable
1 failed, 2 passed, 7 warnings in 2.51s
```
Setelah dipulihkan, `workflow.py` byte-identik dengan snapshot pra-audit
(`diff` bersih), `git status` untuk file itu bersih.

---

## 2. LAPORAN PALSU

### 2a. Hash commit — SEMUA SAH
93 commit pada branch diuji `git cat-file -t`: **semua mengembalikan `commit`**.
Tidak ada hash hantu seperti batch 1.

### 2b. Versi tool & runner — SEMUA SESUAI REPO
| Klaim yang diperiksa | Kenyataan repo | Verdict |
|---|---|---|
| runner frontend | `package.json`: `"test": "node --test tests/*.test.mjs"` (bukan vitest) | sesuai — tidak ada klaim vitest di batch 2 |
| vite | `package.json`: `"vite": "8.3.0"`, `node_modules/vite` = 8.3.0, build mencetak `vite v8.3.0` | sesuai |
| node | v22.23.2 | — |

### 2c. Angka klaim yang saya uji ULANG — SEMUA BENAR
Saya checkout tiap commit ke worktree terpisah dan menjalankan sendiri:

| Commit | Klaim | Hasil verifikasi saya | Verdict |
|---|---|---|---|
| `fd63782` | "frontend 48/48" | `# tests 48 / # pass 48 / # fail 0` | ✅ BENAR |
| `fd63782` | "backend 172/172" | `172 passed, 31 warnings` | ✅ BENAR |
| `fd63782` | "bundle 606→744 kB" | sebelum `index-DcjJzkJP.js 606.54 kB`; sesudah `index-1Xw_lHwD.js 743.69 kB` | ✅ BENAR |
| `fd63782` | bug sintaks `SampleTaskPage.jsx:166` (`row.task_id+r'+'`) | diff asli terlihat: `key={row.task_id+r'+'+row.stage}` → `key={row.task_id+'+'+row.stage}` | ✅ BENAR |
| `81f2c55` | "14/14 test frontend" | `# tests 14 / # pass 14 / # fail 0` | ✅ BENAR |
| `db8230f` | "13/13 printing_ops" | `13 passed` | ✅ BENAR |
| `3eab0a1` | tes imutabilitas gagal saat fix dibatalkan | direproduksi (lihat §1) | ✅ BENAR |

### 2d. Klaim `db8230f` tentang ImportError — BENAR, dan pelakunya lebih awal
Commit `db8230f` menyatakan container crash-loop karena
`ImportError: cannot import name 'sample_lifecycle' from 'app.routers'`.
Saya buktikan langsung pada commit pelakunya, `977308a`
("feat(routers): daftarkan 10 router domain hasil kerja paralel"):
```
$ git -C /tmp/final-syam worktree add --detach /tmp/audit-v2 977308a
$ python -c "from app.main import app"
IMPORT FAILED: ImportError cannot import name 'sample_lifecycle' from 'app.routers'
```
Matriks keadaan:

| Commit | `main.py` menyebut `printing_ops`/`sample_lifecycle` | file-nya ada? | app bisa import? |
|---|---|---|---|
| `977308a` | ya (masing-masing 2×) | **TIDAK** | **TIDAK** |
| `934c5c7` | ya | ya | ya |
| `db8230f` | ya | ya | ya |

→ `977308a` adalah commit rusak (broken commit) yang ter-commit. Diperbaiki 6 commit
kemudian. Ini masalah proses, bukan kebohongan laporan.

---

## 3. KLAIM vs KENYATAAN — ENDPOINT BARU DIUJI LANGSUNG

Semua endpoint GET batch-2 dipanggil nyata lewat `TestClient`
(`backend/tests/test_audit_batch2_endpoints.py`, 26 endpoint, dijalankan 2×:
uji-peran-salah dan uji-TIDAK-500/NULL). Hasil: **50 passed, 6 skipped** — tidak ada
500, tidak ada JSON `null`.

Uji terpisah `/tmp/audit-scratch/probe_rbac.py` memanggil 26 endpoint sebagai
anonim, sebagai peran berhak, dan sebagai peran terlarang (respons mentah direkam):

**A. Anonim → 401 di 26/26 endpoint.** ✅
**B. Peran berhak → 200 di 25/26 endpoint.** Satu anomali yang ternyata bukan bug:
`/api/printing/quantity-check` → **422** karena butuh query `article_id` (validasi
wajar, bukan kegagalan).
**C. Peran terlarang → 403 di 44/45 percobaan.**

Satu-satunya "200 untuk peran 'salah'" adalah `CMO_SUPPORT → /api/cmo/manager-priority`.
Ini **BUKAN kebocoran**: `cmo_manager.py:39` mendefinisikan
`VIEW_ROLES = {"CEO","CMO_MANAGER","CMO_SUPPORT"}` dengan komentar eksplisit
"pemilik customer truth". CMO_SUPPORT memang anggota tim CMO. Ekspektasi saya yang
keliru, bukan kodenya.

### ⚠️ TEMUAN NYATA: `GET /api/hr/employees-summary` → HTTP 500

`hr_employees.py:130` memakai `emp.created_at` **tanpa guard**, padahal baris-baris
sekitarnya memakai helper berguard `_get(emp, cols, ...)`:
```python
130:  join_date = _as_date(_get(emp, cols, "join_date")) or _as_date(emp.created_at)
                                      # ^ berguard          ^ TIDAK berguard
```
Dibuktikan dengan permintaan nyata (krypty `/tmp/audit-scratch/probe_hr_bug.py`,
`/tmp/audit-scratch/probe_hr_head.py`):

```
Employee columns (working tree): [..., 'join_date', ..., 'updated_at']   # TIDAK ada created_at
  200  /api/chro/employees          -> [...]            # tidak menyentuh _row()
  500  /api/hr/employees-summary    -> Internal Server Error

Traceback:
  hr_employees.py:188 in employees_summary
  hr_employees.py:130 in _row
  AttributeError: 'Employee' object has no attribute 'created_at'. Did you mean: 'updated_at'?
```

**Klasifikasi — oh ini penting:** pada **HEAD bersih (`3b1384f`)** kedua endpoint
**200 OK** (di HEAD model punya `created_at`, bukan `join_date`). Latensi muncul di
working tree karena `models.py` (uncommitted, milik agent/sibling lain) mengganti
`created_at` → `join_date`/`updated_at` tanpa memperbarui `hr_employees.py:130`.

→ **Regresi integrasi yang belum ter-commit.** Kalau `models.py` itu di-commit apa
adanya, `/api/hr/employees-summary` akan **500 di produksi** untuk karyawan tanpa
`join_date`. Rekomendasi: ubah baris 130 menjadi berguard, mis.
`_get(emp, cols, "created_at")` / fallback aman, sebelum commit berikutnya.

---

## 4. FILE YATIM & KODE MATI

Pemindaian import resolutif (`/tmp/audit-scratch/orphans.py`, memakai resolusi
ekstensi + `index.*`). Hasil: **5 file yatim** dari 77 file di `src/`.

| File | Status | Sintaks (esbuild) |
|---|---|---|
| `src/pages/CEOCompanyPerformance.jsx` | **BARU / uncommitted** | ✅ OK |
| `src/pages/CEOOverride.jsx` | **BARU / uncommitted** | ✅ OK |
| `src/pages/ModuleDashboard.jsx` | warisan (2026-09-10, `7442d19`) | ✅ OK |
| `src/pages/OrderCreate.jsx` | warisan (2026-09-14, `b136c6a`) | ✅ OK |
| `src/pages/Workspace.jsx` | warisan (2026-09-10, `7442d19`) | ✅ OK |

**Perbandingan dengan batch 1 (positif):** batch 1 punya halaman dengan **sintaks
RUSAK** yang lolos build karena tidak diimpor. Kelima yatim di batch 2 **semuanya
sintaks-valid** — jadi tidak ada "bom waktu build" tersembunyi. Dua yang baru
(`CEOCompanyPerformance`, `CEOOverride`) belum ada di `main.jsx` (`grep -c` = 0) dan
belum punya route; ini konsisten dengan agent CEO yang masih bekerja.

**Koreksi terhadap dugaan awal saya** (penting, supaya tidak jadi laporan palsu):
`hrRecruitment.js`, `ceoPerformance.js`, `sidebarMenu.js`, `SidebarMenu.jsx`, dan
`GlobalSearch.jsx` **BUKAN yatim** — semuanya diimpor/dipakai (terverifikasi; deteksi
pertama saya salah karena pola grep yang tidak resolusi ekstensi).

### Kode mati di backend
`/api` di-`openapi.json`: **140 path**. Setiap router batch-2 diperiksa terhadap app
nyata (`/tmp/audit-scratch/probe_coverage.py`):

```
cmo_manager    declared=1  unreachable=0      printing_jobs    declared=3  unreachable=0
hr_employees   declared=2  unreachable=0      printing_ops     declared=8  unreachable=0
hr_recruitment declared=6  unreachable=0      cfo_receivables  declared=2  unreachable=0
sample_lifecycle declared=4 unreachable=0     cfo_costing      declared=2  unreachable=0
sample_work    declared=2  unreachable=0      coo_execution    declared=3  unreachable=0
TOTAL UNREACHABLE ENDPOINTS: 0
```
**Tidak ada endpoint yatim backend.** Semua 10 router batch-2 terdaftar dan tercapai.

Pemeriksaan `return []` / `return {}` / `return None` di router batch-2: semuanya
adalah **guard defensif yang diberi komentar** (mis. `_ap_ledger_rows` saat tabel
`ap_payments` belum ada), bukan stub. `cfo_receivables.py` bahkan mengembalikan
`note` + `schema_ready: false` secara terbuka ketika tabel belum ada — praktik jujur.

---

## 5. KEBOCORAN HAK AKSES

Metode sesuai pelajaran batch 1: **setiap permintaan adalah request baru** ke app
hidup (bukan navigasi berantai), sehingga sisa DOM pra-React tidak bisa menyamarkan
kebocoran. Hasil di §3: **401 untuk anonim 26/26**, **403 untuk peran terlarang
44/45**, satu "200" yang terbukti sah secara spesifikasi (CMO_SUPPORT ∈ VIEW_ROLES).

Backend RBAC ditegakkan server-side di body handler (`_require_view`, `_require`,
`if user.role.value not in ...`) — bukan hanya di frontend. Ini benar, karena
`Access.jsx` hanyalah lapisan UI.

### Catatan frontend RBAC (transient, sudah pulih)
Saat audit berjalan, `frontend/tests/sidebarMenu.test.mjs` sempat **GAGAL**
(65 pass / 1 fail) dengan pesan celah izin:
```
menu akan ditolak Access.jsx:
  CHRO_MANAGER · "Master Control" -> /master
  CMO_SUPPORT · "Approval Sample (Lihat)" -> /cmo/sample-approval
  HR_SUPPORT  · "Master Control — Lihat Saja" -> /master
  SAMPLE_PIC  · "Sample Exception" -> /exceptions
```
Ini adalah **celah izin nyata yang didaftarkan terbuka** (`BLOCKED_BY_PERMISSION` di
`sidebarMenu.js` + `REQUESTS/sidebar.md`) — menu mengarah ke path yang belum
di-`routeRoles` di `business.js`. Pada putaran berikutnya (agent sidebar menyelesaikan
pekerjaannya) tes menjadi **66/66 pass**. Perlakukan ini sebagai **utang izin yang
harus ditutup**, bukan bug permanen.

---

## OUTPUT MENTAH

### Backend `pytest` (working tree, saat audit berjalan — sibling masih menulis)
```
13 failed, 290 passed, 16 skipped, 54 warnings in 94.95s
FAILED tests/test_cfo_receivables.py::test_ap_summary_uses_real_vendor_type_column
FAILED tests/test_hr_employees.py::test_summary_groups_by_status_and_flags_seed_rows
FAILED tests/test_hr_employees.py::test_join_date_is_derived_honestly_when_column_missing
FAILED tests/test_hr_employees.py::test_contract_window_and_expiry_are_computed_not_guessed
FAILED tests/test_hr_employees.py::test_lifecycle_timeline_is_derived_and_scoped_per_employee
FAILED tests/test_hr_employees.py::test_hr_trace_counts_do_not_touch_attendance_or_payroll
FAILED tests/test_printing_ops_write.py::test_write_roles_are_enforced_and_denials_are_audited
FAILED tests/test_printing_ops_write.py::test_receive_handoff_records_discrepancy_and_opens_exception
FAILED tests/test_printing_ops_write.py::test_rework_blocks_handoff_until_retest_then_handoff_is_allowed
FAILED tests/test_printing_ops_write.py::test_reject_disposition_closes_without_retest_and_outsider_process_is_denied
FAILED tests/test_printing_ops_write.py::test_daily_target_table_becomes_the_source_and_audit_trail_of_daily_target
FAILED tests/test_printing_ops_write.py::test_job_card_fields_are_reported_present_or_missing_honestly
FAILED tests/test_sample_work.py::test_row_binds_order_article_and_version
```
**PENTING — jangan salah baca:** kegagalan ini adalah **mid-flight**, bukan regresi
ter-commit. Terverifikasi: pada HEAD bersih `3b1384f` seluruh `test_hr_employees.py`
**8/8 pass** pada setiap revisi yang diuji (bisect `1755a85, 81f2c55, 934c5c7,
fd63782, 3eab0a1, 3b1384f` → semuanya "8 passed"). Penyebab kegagalan massal adalah
satu `AttributeError` dari `models.py` uncommitted (lihat §3) yang membuat import
rusak dan merobohkan file tes yang tidak bersalah.

Baseline bersih yang saya ukur di awal audit (sebelum edit sibling mendarat):
```
175 passed, 31 warnings in 44.01s
```

### Frontend
```
$ npm run build
vite v8.3.0 building client environment for production...
✓ 1928 modules transformed.
dist/assets/index-1Xw_lHwD.js   743.69 kB │ gzip: 180.08 kB
✓ built in 1.45s

$ npm test
# tests 66
# pass 66     (fluktuatif: pernah 48/48, 65/66 saat sibling menulis)
# fail 0
```

### Verifikasi per-commit (worktree terpisah)
```
fd63782  frontend: # tests 48 / # pass 48 / # fail 0     ← klaim "48/48" BENAR
fd63782  backend : 172 passed, 31 warnings               ← klaim "172/172" BENAR
fd63782  build   : 743.69 kB; fd63782^ build: 606.54 kB  ← klaim "606→744 kB" BENAR
81f2c55  frontend: # tests 14 / # pass 14 / # fail 0     ← klaim "14/14" BENAR
db8230f  printing_ops: 13 passed                        ← klaim "13/13" BENAR
0571caf  hr_employees: 8 passed                         ← sehat di commit sendiri
3b1384f  hr_employees: 8 passed                         ← sehat di HEAD
977308a  import app: ImportError cannot import name 'sample_lifecycle'
```

---

## YANG BELUM / TIDAK BISA SAYA SELESAIKAN

1. **Audit ini adalah snapshot dari repo yang bergerak.** Sembilan agent lain menulis
   ke working tree selama audit. Angka tes berubah antar-panggilan (48 → 65 → 66;
   175 → 303). Semua kesimpulan di atas sudah dipisahkan per-kelas (ter-commit vs
   working tree), tapi verdict akhir untuk kode uncommitted harus diulang setelah
   para agent berhenti.
2. **Temuan §3 (`created_at`) tidak saya perbaiki** karena larangan mengubah kode
   produksi. Perbaikannya satu baris di `hr_employees.py:130`; sebaiknya dikerjakan
   oleh agent pemilik file HR atau orkestrator sebelum `models.py` di-commit.
3. **`hr_recruitment.py` sedang ditulis ulang** (diff uncommitted +1190 baris) —
   audit fungsionalnya belum bisa final.
4. **`test_printing_ops_write.py`** (uncommitted, baru) gagal; karena file ini belum
   pernah ter-commit, kegagalannya adalah WIP, bukan regresi. Belum saya audit
   sebagai barang jadi.
5. **Tidak ada push / commit ke branch** yang saya lakukan selain file audit saya.

---

## FILE YANG SAYA BUAT

- `backend/tests/test_audit_batch2_endpoints.py` — tes audit (endpoint 500/null + RBAC).
- `AUDIT/BATCH2-AUDIT.md` — laporan ini.
- (scratch, di luar repo) `/tmp/audit-scratch/` — harness mutasi & probe.

Kode produksi **tidak diubah**. Semua mutasi dipulihkan byte-identik.
