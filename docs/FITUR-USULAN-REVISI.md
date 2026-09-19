# Fitur Usulan Revisi (Revision Proposal)

Dokumen konsep & referensi implementasi. Tujuan fitur ini: **setiap masukan tim tercatat di satu
tempat, dan setiap perbaikan punya jejak — siapa yang mengerjakan, kapan, dan dengan bukti apa.**

Fitur ini sengaja dibuat *append-only*: tidak ada endpoint `DELETE` untuk usulan revisi, dan
setiap perubahan status tersimpan sebagai baris riwayat tersendiri. Alasannya sederhana — kalau
jejak perbaikan bisa dihapus, fitur ini kehilangan gunanya sebagai alat kontrol.

---

## 1. Alur kerja

```
Tim / user menemukan masalah
        │
        ▼
  1. Buat usulan            status = REVISI      operator = kosong
        │
        ▼
  2. Pelaksana mengerjakan perbaikan
        │
        ▼
  3. Isi operator  ─────────► catat SIAPA yang mengerjakan
        │                     (Hermes / GPT / Claude / nama orang)
        ▼
  4. Kirim ke Check         status = CHECK      wajib pakai catatan
        │
        ▼
  5. Tim memeriksa hasil
        │
   ┌────┴────┐
   │         │
   ▼         ▼
SOLVED   TINJAU_ULANG ──► dikerjakan ulang ──► kembali ke langkah 2
(selesai)  (perlu diperbaiki)
```

**Prinsip yang dijaga:**

| Prinsip | Konsekuensi teknis |
|---|---|
| Usulan tidak boleh hilang | Tidak ada endpoint `DELETE` |
| Setiap perubahan harus bisa ditelusuri | Tiap perubahan status menulis baris `revision_status_events` |
| Perbaikan harus punya penanggung jawab | Kolom `operator` di usulan dan di setiap riwayat |
| Perubahan harus dibuktikan, bukan diklaim | `CHECK` dan `TINJAU_ULANG` wajib mengisi catatan |
| Perubahan serentak tidak boleh saling menimpa | Optimistic lock lewat `expected_status` / `expected_operator` |

---

## 2. Status

| Status | Arti | Siapa yang boleh mengubah |
|---|---|---|
| `REVISI` | Usulan baru, belum dikerjakan | — (status awal) |
| `CHECK` | Perbaikan sudah dikerjakan, menunggu pemeriksaan tim | CEO, atau pemilik `owner_role` |
| `SOLVED` | Diperiksa tim dan dianggap selesai | Pelapor asli, atau CEO |
| `TINJAU_ULANG` | Diperiksa tim, ternyata belum benar — perlu diperbaiki ulang | Pelapor asli, atau CEO |

**Transisi yang sah** (`allowed_next` di `backend/app/routers/revisions.py`):

```
REVISI         ──► CHECK          (CEO atau pemilik owner_role)
TINJAU_ULANG   ──► CHECK          (CEO atau pemilik owner_role)
CHECK          ──► SOLVED         (pelapor asli atau CEO)
CHECK          ──► TINJAU_ULANG   (pelapor asli atau CEO)
```

> **Catatan penting — tidak ada jalan kembali ke `REVISI`.**
> Jalur `TINJAU_ULANG → CHECK` adalah satu-satunya jalan memperbaiki usulan yang salah status.
> Ini sempat menyebabkan insiden: sebuah usulan ikut terpindah ke `CHECK` karena pengujian API,
> dan status `REVISI`-nya tidak bisa dikembalikan lewat aplikasi. Kalau kejadian serupa terulang,
> **jangan** menambal lewat endpoint sementara tanpa guard — tambahkan jalur resmi
> `→ REVISI` (khusus CEO) sebagai gantinya.

**Aturan catatan:** `CHECK` dan `TINJAU_ULANG` **wajib** disertai catatan (maks. 2000 karakter),
backend menolak dengan `422` kalau kosong. `SOLVED` boleh tanpa catatan.

---

## 3. Operator — siapa yang mengerjakan

Kolom `operator` menyimpan **siapa atau apa yang benar-benar mengerjakan perbaikan**. Ini yang
menjawab pertanyaan "kalau hasilnya belum benar, siapa yang harus ditanyai?".

**Kapan diisi:** setelah perbaikan dikerjakan — **bukan** saat usulan dibuat.
Usulan yang masih `REVISI` memang operatornya kosong; di UI tampil **"Belum dicatat"**.

**Nilai yang dianjurkan** (bebas diisi, tapi konsisten lebih enak dibaca):

- `Hermes` — agen Hermes
- `GPT` — model/asisten GPT
- `Claude` — model/asisten Claude
- `Gemini`
- nama orang, kalau dikerjakan manusia

**Dua tempat penyimpanan, sengaja dipisah:**

1. `revision_proposals.operator` — operator terkini usulan tersebut
2. `revision_status_events.operator` — operator **pada perubahan status itu**

Pemisahan ini penting: kalau GPT mengerjakan lalu Hermes yang mengubah status, keduanya tercatat
dan tidak saling menimpa. Saat mengubah status tanpa mengirim operator, sistem memakai operator
usulan sebagai nilai bawaan.

---

## 4. Tabel database

### `revision_proposals`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | Integer PK | |
| `module_name` | String(120) | Wajib, maks. 120 karakter |
| `bug_description` | Text | Wajib, maks. 5000 karakter |
| `expected_behavior` | Text | Wajib, maks. 5000 karakter |
| `image_data` | LargeBinary | Opsional, maks. 5 MB |
| `image_mime` | String(40) | `image/png`, `image/jpeg`, `image/webp` |
| `reported_by_id` | FK → `users.id` | Pelapor |
| `owner_role` | String(40) | Divisi yang menangani |
| `status` | String(24) | Bawaan `REVISI` |
| `status_note` | Text | Catatan perubahan status terakhir |
| `status_updated_at` | DateTime | |
| `status_updated_by_id` | FK → `users.id` | |
| `operator` | String(64) | **Siapa yang mengerjakan** |
| `created_at` | DateTime | |

### `revision_status_events`

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | Integer PK | |
| `proposal_id` | FK → `revision_proposals.id` | |
| `from_status` / `to_status` | String(24) | |
| `note` | Text | Alasan perubahan |
| `changed_by_id` | FK → `users.id` | Akun yang menekan tombol |
| `operator` | String(64) | **Pelaksana pada perubahan itu** |
| `created_at` | DateTime | |

Migrasi terkait: `0015_operator_attribution` (`backend/migrations/versions/`).

> **Perhatian saat menambah kolom:** container produksi menolak start kalau schema bukan head —
> `entrypoint.sh` menjalankan `alembic upgrade head`, dan `main.py` melempar `RuntimeError`
> bila revisi database berbeda dari head migrasi. Setiap perubahan model **wajib** disertai file
> migrasi baru, kalau tidak aplikasi tidak akan naik.

---

## 5. API

Semua endpoint memerlukan autentikasi. Basis: `/api/revisions`.

| Method | Path | Akses | Keterangan |
|---|---|---|---|
| `GET` | `/revisions` | Semua yang login | Daftar usulan. `?limit=` (maks. 200) & `?offset=` |
| `POST` | `/revisions` | Semua yang login | Buat usulan. `multipart/form-data` |
| `GET` | `/revisions/{id}/history` | Semua yang login | Riwayat status |
| `GET` | `/revisions/{id}/image` | Semua yang login | Gambar pendukung |
| `PATCH` | `/revisions/{id}/status` | Lihat tabel transisi | Ubah status |
| `PATCH` | `/revisions/{id}/operator` | **CEO saja** | Tetapkan operator |

### `POST /revisions`

`multipart/form-data`:

| Field | Wajib | Catatan |
|---|---|---|
| `module_name` | ✅ | maks. 120 |
| `bug_description` | ✅ | maks. 5000 |
| `expected_behavior` | ✅ | maks. 5000 |
| `owner_role` | — | Bawaan: role pengusul |
| `operator` | — | Opsional; umumnya diisi **setelah** perbaikan, bukan di sini |
| `image` | — | PNG / JPG / WebP, maks. 5 MB |

### `PATCH /revisions/{id}/status`

```json
{
  "expected_status": "REVISI",
  "status": "CHECK",
  "note": "Perbaikan sudah live di deploy 3893cb1.",
  "operator": "Hermes"
}
```

`expected_status` **wajib** dan harus sama dengan status saat ini; kalau tidak, server membalas
`409`. Ini mencegah dua orang saling menimpa perubahan.

`operator` opsional — kalau kosong, dipakai `operator` milik usulan.

### `PATCH /revisions/{id}/operator`

```json
{ "operator": "GPT", "expected_operator": null }
```

- Hanya **CEO**; role lain dibalas `403`.
- `expected_operator` adalah optimistic lock: kirim nilai operator saat ini (`null` bila kosong).
  Bila sudah berubah, server membalas `409` dan perubahan ditolak.
- Kirim `operator: null` atau string kosong untuk mengosongkan.
- Aksi ini tercatat di `audit_logs` dengan aksi `OPERATOR_ASSIGN`, dan menulis satu baris riwayat
  (`CHECK → CHECK`, catatan `Operator: ... → ...`) sehingga penugasan tidak bisa diubah diam-diam.

### Kode balasan

| Kode | Arti |
|---|---|
| `401` | Belum/tidak login |
| `403` | Login, tapi tidak berwenang untuk aksi itu |
| `404` | Usulan tidak ada |
| `409` | Status/operator sudah berubah — muat ulang dulu |
| `413` | Gambar melebihi 5 MB |
| `415` | Format gambar tidak didukung |
| `422` | Isian tidak valid, atau `CHECK`/`TINJAU_ULANG` tanpa catatan |

---

## 6. Tampilan

Halaman: **Usulan Revisi** (`frontend/src/pages/RevisionPage.jsx`), rute `/revisions`.

- **Kolom kiri** — form usulan baru: modul, owner, bug, harapan, gambar pendukung, dan
  **Operator yang mengerjakan** (opsional).
- **Kolom kanan** — feed usulan, filter status (Semua / Revisi / Check / Tinjau Ulang / Solved)
  dan kotak pencarian.
- **Kartu usulan** — urutan tampil:

  ```
  [ Nama Modul ]                          [ Status ] [ Gambar ]
  OPERATOR   ( Hermes )   [Ubah]
  Pelapor · Tanggal · Owner: Divisi
  Bug        ...
  Harusnya   ...
  [ Lihat detail ]
  ```

  Baris **OPERATOR** berada tepat di bawah status. Kalau belum ada, tampil *"Belum dicatat"*
  dengan gaya redup. Tombol **Ubah** hanya muncul untuk **CEO**.
- **Detail usulan** — isi lengkap, riwayat status (tiap baris menampilkan operator pelaksananya),
  dan aksi perubahan status sesuai kewenangan.

Gaya terkait ada di `frontend/src/styles.css` dengan awalan `.revision-*` —
termasuk `.revision-operator-*` untuk blok operator.

---

## 7. Aturan yang harus dijaga saat mengembangkan

1. **Jangan tambahkan `DELETE`** untuk usulan revisi. Fitur ini alat kontrol; usulan yang bisa
   dihapus melemahkan jejaknya. Kalau sebuah data uji harus dibersihkan, perbaiki lewat catatan
   atau minta operator database — jangan longgarkan desainnya.
2. **Setiap perubahan model wajib disertai migrasi.** Produksi tidak akan start tanpa itu.
3. **Jangan mengisi `operator` secara otomatis** dari role atau nama akun. Operator adalah
   pernyataan siapa yang mengerjakan, dan itu hanya boleh datang dari orang yang mengetahuinya.
   Data lama yang kosong **dibiarkan kosong** — jangan diisi nilai karangan.
4. **Wajib ada catatan** untuk `CHECK` dan `TINJAU_ULANG`. Tanpa catatan, tim pemeriksa tidak
   punya dasar untuk menilai.
5. **Pakai optimistic lock** pada setiap perubahan yang tunduk pada balapan antar pengguna.
6. **Kalau butuh jalur status baru, tambahkan sebagai jalur resmi** di `allowed_next` dengan
   kewenangan yang jelas — jangan menambal lewat endpoint sementara.
7. **Sinkronkan UI dengan backend.** Tombol yang disembunyikan bukan pengaman; kewenangan tetap
   harus ditegakkan di API. Sebaliknya, jangan tampilkan tombol yang pasti ditolak server.

---

## 8. Insiden yang pernah terjadi (jangan diulang)

| Kejadian | Penyebab | Pelajaran |
|---|---|---|
| Sebuah usulan terpindah ke `CHECK` lalu nyangkut di `TINJAU_ULANG` | Pengujian API memakai data asli, dan tidak ada validasi pada alur uji | Uji dengan data yang jelas ditandai, dan mengaku kalau status data berubah |
| Status tidak bisa dikembalikan ke `REVISI` | `allowed_next` tidak menyediakan jalur balik | Perbaikan dilakukan lewat endpoint khusus yang di-guard, lalu dihapus setelah selesai |
| Halaman keputusan bocor ke role lain | `canAccess` mengembalikan `true` untuk path yang tidak terdaftar (fail-open) | Daftarkan setiap rute secara eksplisit; kegagalan harus menutup, bukan membuka |
| Menu muncul untuk role yang tidak berhak | Menu di `side-foot` dirender tanpa memeriksa role | Saring menu berdasarkan role, jangan hanya mengandalkan penyembunyian |

---

## 9. Berkas terkait

| Berkas | Isi |
|---|---|
| `backend/app/models.py` | `RevisionProposal`, `RevisionStatusEvent` |
| `backend/app/routers/revisions.py` | Seluruh endpoint, aturan transisi, kewenangan |
| `backend/migrations/versions/0007_revision_proposals.py` | Tabel awal |
| `backend/migrations/versions/0008_revision_status.py` | Riwayat status |
| `backend/migrations/versions/0015_operator_attribution.py` | Kolom `operator` |
| `frontend/src/pages/RevisionPage.jsx` | Seluruh tampilan fitur |
| `frontend/src/business.js` | `canAccess` — kewenangan rute di sisi klien |
| `frontend/src/styles.css` | Kelas `.revision-*` |
