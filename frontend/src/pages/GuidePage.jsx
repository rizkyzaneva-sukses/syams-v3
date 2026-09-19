import React, { useState, useMemo } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import {
  Crown,
  Target,
  FileText,
  DollarSign,
  Factory,
  Printer,
  Scissors,
  Users,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Search,
  ArrowRight,
  Lock,
  ShieldCheck,
  Layers,
  Clock,
  BookOpen,
  Truck,
  CheckSquare,
  Package,
  Home,
  Info,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

/* PANDUAN LENGKAP PENGGUNAAN BOS SYAMS (Semua Revisi #1 - #78)
   Panduan komprehensif berbasis peran dengan SOP harian, batas kewenangan tegas,
   solusi troubleshooting gerbang (gate) terkunci, dan flowchart interaktif.
*/

const ROLE_GUIDES = {
  CEO: {
    title: 'Chief Executive Officer (CEO)',
    pic: 'Iyan',
    icon: Crown,
    tone: 'blue',
    summary: 'Pemegang kendali tata kelola tertinggi, penetapan kebijakan bisnis berversi, pemutus eskalasi, dan pemantau performa perusahaan secara read-only tanpa mencampuri eksekusi teknis operasional divisi.',
    dailyRoutine: [
      { step: 'Buka Morning CEO View (/ceo)', desc: 'Tinjau kartu metrik KPI bisnis, ringkasan pendapatan, performa margin, dan status penutupan order.' },
      { step: 'Periksa Decision Needed (/ceo/decisions)', desc: 'Beri keputusan bertipe (Approve/Reject) untuk eskalasi dari divisi: diskon di luar limit CFO, lembur darurat, atau perubahan kapasitas.' },
      { step: 'Monitor CEO Action Tracker', desc: 'Pantau status tindak lanjut instruksi CEO kepada kepala divisi untuk memastikan eksekusi selesai tepat waktu.' },
      { step: 'Tinjau Exception Center (/exceptions)', desc: 'Tinjau kendala operasional dengan severity HIGH atau RED yang dieskalasikan oleh COO/CFO/CHRO.' },
      { step: 'Kelola Kebijakan Bisnis (/ceo/business-policy)', desc: 'Tetapkan batas margin minimum (%), DP minimum (%), dan limit plafon approval CFO. Setiap perubahan wajib mencantumkan alasan tertulis dan tercatat versi baru secara atomik.' },
      { step: 'Evaluasi Company Performance (/ceo/company-performance)', desc: 'Pantau laporan keuangan, HPP aktual vs estimasi, dan log audit kepatuhan (/audit-log) secara menyeluruh.' },
    ],
    dos: [
      'Menetapkan kebijakan bisnis umum (Minimum DP, Limit Approval CFO, Syarat Kredit).',
      'Mengambil keputusan pada isu yang dieskalasi ke level CEO (Decision Needed).',
      'Memberikan persetujuan override darurat dengan catatan alasan yang jelas di register audit.',
      'Melakukan drill-down read-only ke data operasional divisi untuk audit dan evaluasi.',
    ],
    donts: [
      'DILARANG membuat atau mengubah transaksi operasional harian (PO pembelian, invoice rutin, atau surat jalan fisik).',
      'DILARANG menghapus atau mengedit data log audit sistem (seluruh log bersifat append-only / tamper-proof).',
      'DILARANG membypass gerbang sistem tanpa melalui form Override Governance resmi.',
    ],
    keyPages: [
      { name: 'Morning CEO View', path: '/ceo', desc: 'Dashboard ringkasan metrik keputusan dan status bisnis harian' },
      { name: 'Company Performance', path: '/ceo/company-performance', desc: 'Analisis kinerja margin, pendapatan, dan efisiensi' },
      { name: 'Decision Needed', path: '/ceo/decisions', desc: 'Daftar eskalasi keputusan yang menunggu putusan CEO' },
      { name: 'Exception Center', path: '/exceptions', desc: 'Pusat eskalasi isu operasional lintas divisi' },
      { name: 'Kebijakan Bisnis', path: '/ceo/business-policy', desc: 'Pengaturan limit margin, DP, dan tata kelola berversi' },
      { name: 'Audit Trail', path: '/audit-log', desc: 'Rekaman jejak aktivitas sistem yang tidak dapat diubah' },
    ],
  },

  CMO_MANAGER: {
    title: 'Chief Marketing Officer (CMO Manager)',
    pic: 'Cecep',
    icon: Target,
    tone: 'blue',
    summary: 'Penanggung jawab hubungan pelanggan (buyer), validasi order intake, penetapan harga (quotation), persetujuan sample PPM, pelepasan SPK resmi ke pabrik, dan penutupan sisi pelanggan (customer closing).',
    dailyRoutine: [
      { step: 'Buka Morning Priority (/cmo/priority)', desc: 'Tinjau antrean prioritas keputusan harian: PO masuk yang diajukan Deby, quotation menunggu harga, dan sample approval.' },
      { step: 'Review & Terima PO Masuk (/cmo/po-inbox)', desc: 'Periksa kelengkapan PO draft dari Deby. Verifikasi rute produksi dan deadline buyer sebelum klik "Accept Order".' },
      { step: 'Review Quotation (/cmo/quotations)', desc: 'Tentukan harga jual dan hitung margin estimasi. Ajukan ke CFO untuk persetujuan margin.' },
      { step: 'Uji Kesiapan & Rilis SPK (/cmo/spk)', desc: 'Setelah SPK dicetak Deby dan seluruh gate (Quotation, DP CFO, Rencana Produksi) hijau, lakukan "Release SPK" agar pabrik boleh mulai memotong kain.' },
      { step: 'Konfirmasi Penerimaan Barang (/cmo/buyer-crm)', desc: 'Setelah COO mencatat fisik terkirim (Delivered), minta konfirmasi kepuasan buyer dan catat Customer Delivery Confirmation.' },
      { step: 'Customer Order Closing (/coo/closing)', desc: 'Setelah buyer puas dan tidak ada retur, lakukan penutupan order dari sisi Customer.' },
    ],
    dos: [
      'Menerima atau menolak draft PO intake yang disiapkan oleh CMO Support (Deby).',
      'Mengesahkan dan merilis SPK resmi ke divisi produksi (Release to COO).',
      'Mencatat konfirmasi penerimaan barang dari pihak buyer.',
      'Melakukan closing order sisi pelanggan (Customer Close).',
    ],
    donts: [
      'DILARANG merilis SPK sebelum seluruh prasyarat (Quotation disetujui CFO & DP terbayar) terpenuhi.',
      'DILARANG mengubah rute produksi setelah order aktif (rute bersifat immutable).',
      'DILARANG menutup sisi operasional atau keuangan order (kewenangan eksklusif COO & CFO).',
    ],
    keyPages: [
      { name: 'Morning Priority', path: '/cmo/priority', desc: 'Antrean tindakan prioritas CMO action-first' },
      { name: 'PO Inbox', path: '/cmo/po-inbox', desc: 'Validasi dan penerimaan PO draft dari Deby' },
      { name: 'Daftar Order', path: '/cmo/orders', desc: 'Daftar seluruh pesanan pelanggan aktif' },
      { name: 'Pusat SPK', path: '/cmo/spk', desc: 'Pemeriksaan gate kesiapan dan pelepasan SPK' },
      { name: 'Sample Approval Feed', path: '/cmo/sample-approval', desc: 'Umpan balik persetujuan sample dari buyer' },
      { name: 'Buyer CRM', path: '/cmo/buyer-crm', desc: 'Database profil buyer, kontak, dan riwayat pesanan' },
    ],
  },

  CMO_SUPPORT: {
    title: 'CMO Support',
    pic: 'Deby',
    icon: FileText,
    tone: 'blue',
    summary: 'Garda depan administrasi penjualan: input data customer, penyusunan draft PO intake, upload dokumen kontrak buyer, drafting quotation, pembuatan sample request, serta generate dan cetak fisik SPK.',
    dailyRoutine: [
      { step: 'Buka Deby Today (/cmo/today)', desc: 'Tinjau daftar tugas harian Deby: PO masuk baru, follow-up buyer, dan antrean SPK siap cetak.' },
      { step: 'Input PO Masuk (/cmo/po-inbox)', desc: 'Input PO buyer lengkap dengan kode artikel, kuantitas, breakdown ukuran, dan RUTE PRODUKSI wajib (contoh: Cutting > Sewing > QC).' },
      { step: 'Unggah Dokumen PO Asli', desc: 'Wajib mengunggah file PDF bukti PO dari buyer. Tanpa file ini, tombol "Cek Kelengkapan" tidak akan lolos.' },
      { step: 'Cek & Submit PO ke Cecep', desc: 'Jalankan auto-check. Jika lengkap, klik "Kirim ke Cecep" agar masuk ke antrean persetujuan CMO Manager.' },
      { step: 'Draft Quotation & Request Sample', desc: 'Siapkan draft penawaran harga dan ajukan pembuatan sample ke Fahrul jika buyer meminta sample.' },
      { step: 'Generate & Print Dokumen SPK (/cmo/spk)', desc: 'Generate nomor SPK, lihat preview PDF resmi, dan cetak (Print) salinan fisik untuk arsip.' },
    ],
    dos: [
      'Menginput PO buyer, data customer, draft quotation, dan permintaan sample.',
      'Mengunggah dokumen kontrak/PO asli dari pelanggan.',
      'Melakukan Generate dan Print dokumen SPK ber-barcode resmi.',
      'Memantau status aman pelanggan (Customer Portal Safe View) tanpa membocorkan data internal.',
    ],
    donts: [
      'DILARANG melakukan "Release SPK" ke lantai produksi (kewenangan eksklusif CMO Manager).',
      'DILARANG menyetujui quotation atau mengubah status pembayaran invoice.',
      'DILARANG lupa mengisi "Rute Produksi" saat menginput artikel pesanan baru.',
    ],
    keyPages: [
      { name: 'Hari Ini (Deby Work List)', path: '/cmo/today', desc: 'Workspace tindakan harian terfokus Deby' },
      { name: 'PO Masuk (Intake)', path: '/cmo/po-inbox', desc: 'Pendaftaran PO, upload PDF, dan submit verifikasi' },
      { name: 'Quotation', path: '/cmo/quotations', desc: 'Pembuatan draf surat penawaran harga' },
      { name: 'SPK Dokumen', path: '/cmo/spk', desc: 'Generate dan cetak dokumen SPK' },
      { name: 'Tugas Saya', path: '/tasks', desc: 'Daftar penugasan operasional yang diberikan ke Deby' },
    ],
  },

  CFO_MANAGER: {
    title: 'Chief Financial Officer (CFO Manager)',
    pic: 'Riadi',
    icon: DollarSign,
    tone: 'amber',
    summary: 'Penjaga integritas arus kas dan profitabilitas: persetujuan margin quotation, penerbitan invoice DP/Pelunasan, rekonsiliasi pembayaran bank, clearance Finance Gate, approval PO bahan baku, dan penutupan finansial.',
    dailyRoutine: [
      { step: 'Buka CFO Home (/cfo)', desc: 'Periksa antrean prioritas keuangan: pembayaran masuk yang butuh verifikasi, invoice jatuh tempo, dan review HPP.' },
      { step: 'Approval Quotation (/cmo/quotations)', desc: 'Validasi margin harga jual terhadap HPP. Jika margin memenuhi kebijakan bisnis (>15%), klik "Approve".' },
      { step: 'Terbitkan Invoice & Catat Pembayaran (/cfo/invoices)', desc: 'Terbitkan Invoice DP (minimal 30%). Saat pembayaran masuk ke rekening bank, catat nominalnya dan lakukan "Reconcile".' },
      { step: 'Buka Finance Gate Pembayaran', desc: 'Setelah DP lunas dan terekonsiliasi, setujui Finance Gate agar order boleh diproses ke pembuatan SPK.' },
      { step: 'Approval Purchase Order (/cfo/purchase-orders)', desc: 'Tinjau pengajuan material dari COO di workspace Purchasing (/purchasing). Terbitkan PO supplier dan ubah status ke "READY" setelah barang datang.' },
      { step: 'Clearance Finance Gate Pengiriman (/cfo/shipments)', desc: 'Sebelum barang dikirim ke buyer, pastikan sisa tagihan lunas atau memiliki izin kredit berjangka dari CEO.' },
      { step: 'Financial Order Closing (/coo/closing)', desc: 'Setelah seluruh piutang buyer dan hutang supplier lunas tuntas (saldo nol), lakukan Financial Close.' },
    ],
    dos: [
      'Menyetujui atau menolak margin penawaran harga (Quotation).',
      'Menerbitkan invoice, mencatat pembayaran, dan mencocokkan mutasi bank (rekonsiliasi).',
      'Membuka Finance Gate untuk produksi dan pengiriman.',
      'Mengelola hutang usaha (AP), piutang usaha (AR aging), dan modul Purchasing Riadi.',
      'Melakukan Financial Closing pesanan.',
    ],
    donts: [
      'DILARANG mengetik nominal terbayar secara manual di invoice (wajib melalui input record pembayaran).',
      'DILARANG menyetujui Finance Gate pengiriman jika piutang masih ada tanpa izin tertulis CEO.',
      'DILARANG mengubah kuantitas atau jadwal eksekusi fisik mesin pabrik.',
    ],
    keyPages: [
      { name: 'CFO Home', path: '/cfo', desc: 'Pusat komando arus kas, verifikasi bayar, dan gate keuangan' },
      { name: 'Invoices', path: '/cfo/invoices', desc: 'Pengelolaan tagihan invoice DP dan Pelunasan' },
      { name: 'Purchase Orders', path: '/cfo/purchase-orders', desc: 'Persetujuan pesanan pembelian bahan baku ke supplier' },
      { name: 'Purchasing & Warehouse', path: '/purchasing', desc: 'Workspace kebutuhan material, PO vendor, dan stok gudang' },
      { name: 'Shipments Gate', path: '/cfo/shipments', desc: 'Pemeriksaan status saldo tagihan sebelum barang diberangkatkan' },
      { name: 'Closing Keuangan', path: '/coo/closing', desc: 'Verifikasi saldo nol dan penutupan finansial order' },
    ],
  },

  COO_MANAGER: {
    title: 'Chief Operating Officer (COO Manager)',
    pic: 'Siti',
    icon: Factory,
    tone: 'green',
    summary: 'Komandan operasional pabrik: penyusunan BOM, pengajuan kebutuhan material, perencanaan kapasitas mesin, pengawasan pergerakan WIP per route, kendali mutu QC internal, serah terima fisik (Delivered), dan penutupan operasional.',
    dailyRoutine: [
      { step: 'Buka COO Home (/coo)', desc: 'Tinjau kartu rencana produksi, status material shortage, kapasitas lini, dan antrean WIP.' },
      { step: 'Susun BOM & Ajukan Material Request (/coo/material-requests)', desc: 'Masukkan kebutuhan bahan baku per pcs. Buat Material Request ke Riadi (jumlah MR harus >= kebutuhan BOM).' },
      { step: 'Setujui Rencana Produksi (/coo/planning)', desc: 'Tentukan slot tanggal kerja dan alokasi lini, lalu set status Production Plan menjadi "APPROVED".' },
      { step: 'Awasi Eksekusi & WIP Harian (/coo/execution)', desc: 'Pastikan proses di lantai kerja bergerak urut sesuai rute artikel (contoh: Cutting -> Sewing -> QC).' },
      { step: 'Verifikasi Handoff Antar Proses (/coo/handoffs)', desc: 'Kawal serah terima output antar divisi. Terapkan prinsip: Qty Masuk = Selesai + Reject + Sisa.' },
      { step: 'QC Final & Packing Pengiriman (/coo/qc)', desc: 'Setelah seluruh kuantitas lulus QC PASS, lakukan pengemasan (PACKED) lengkap dengan rekonsiliasi baris artikel.' },
      { step: 'Kirim & Catat Serah Terima Fisik (/coo/deliveries)', desc: 'Setelah Finance Gate lolos, ubah status ke SHIPPED. Saat barang tiba di lokasi buyer, catat tanggal serah terima fisik (DELIVERED).' },
      { step: 'Operational Order Closing (/coo/closing)', desc: 'Setelah barang diterima fisik dan tidak ada rework tersisa, lakukan penutupan operasional.' },
    ],
    dos: [
      'Menyusun Bill of Materials (BOM) fisik dan mengajukan permintaan material.',
      'Menyetujui jadwal rencana produksi (Production Plan).',
      'Mencatat perpindahan proses fisik (Movements), QC internal, dan pengemasan (Packing).',
      'Mencatat tanggal serah terima fisik pengiriman (Physical Handover DELIVERED).',
      'Melakukan Operational Closing pesanan.',
    ],
    donts: [
      'DILARANG mengubah nominal harga beli material atau biaya finansial (data biaya di-masking read-only).',
      'DILARANG mengubah status fisik barang pembelian di gudang Riadi.',
      'DILARANG memberangkatkan pengiriman barang sebelum Finance Gate disetujui CFO.',
    ],
    keyPages: [
      { name: 'COO Home', path: '/coo', desc: 'Monitoring alur operasional pabrik, WIP, dan kapasitas' },
      { name: 'Daily Execution', path: '/coo/execution', desc: 'Lantai kerja pergerakan produksi per proses harian' },
      { name: 'Material Requests', path: '/coo/material-requests', desc: 'Pengajuan kebutuhan bahan baku ke logistik' },
      { name: 'WIP Tracking', path: '/coo/wip', desc: 'Pemantauan kuantitas barang dalam proses (WIP)' },
      { name: 'QC Records', path: '/coo/qc', desc: 'Pencatatan hasil inspeksi mutu lolos/reject' },
      { name: 'Deliveries', path: '/coo/deliveries', desc: 'Pencatatan pengiriman dan serah terima fisik buyer' },
    ],
  },

  PRINTING_PIC: {
    title: 'Printing & Bordir PIC',
    pic: 'Iman',
    icon: Printer,
    tone: 'blue',
    summary: 'Penanggung jawab eksekusi cetak sablon dan bordir komputer: penetapan target harian dinamis, eksekusi job card SPK, pencatatan hasil cetak accepted vs reject, penanganan defect, dan serah terima ke Sewing.',
    dailyRoutine: [
      { step: 'Buka Printing Hari Ini (/printing/today)', desc: 'Tetapkan target cetak fleksibel hari ini (standar 640 pcs) dan periksa antrean Job Card berstatus Siap Cetak.' },
      { step: 'Pilih Job Card & Siapkan Meja/Mesin (/printing/job-cards)', desc: 'Pilih artikel prioritas. Periksa kesiapan screen sablon, tinta/benang, dan kuantitas potongan kain dari Cutting.' },
      { step: 'Eksekusi & Catat Output Berkala', desc: 'Catat Qty Selesai (Accepted) dan Qty Reject secara berkala. Pilih kategori cacat jika ada reject (Blur, Geser Miskalibrasi, Noda Tinta, Belang Warna).' },
      { step: 'Jaga Keseimbangan Fisik Kuantitas', desc: 'Patuhi rumus mutlak: Qty Selesai + Qty Reject + Qty Sisa WIP = Qty Masuk Potongan Kain.' },
      { step: 'Serah Terima Partial ke Sewing (/printing/handoffs)', desc: 'Lakukan serah terima bertahap ke divisi penjahitan (Sewing) lengkap dengan verifikasi paraf penerima.' },
    ],
    dos: [
      'Menetapkan target harian fleksibel divisi printing.',
      'Mengoperasikan job card cetak printing dan bordir yang ditugaskan.',
      'Mencatat output riil, kuantitas reject, dan klasifikasi jenis cacat fisik.',
      'Mengajukan disposisi rework internal atau permohonan makloon luar jika mesin overload.',
    ],
    donts: [
      'DILARANG mengubah status pekerjaan menjadi "DONE" sebelum seluruh kuantitas masuk terekonsiliasi.',
      'DILARANG mengerjakan artikel di luar proses Printing/Bordir.',
      'DILARANG menyerahkan potongan cetak ke Sewing tanpa pencatatan serah terima (handoff).',
    ],
    keyPages: [
      { name: 'Printing Hari Ini', path: '/printing/today', desc: 'Workspace eksekusi harian Iman: target, antrean, dan input output' },
      { name: 'Job Cards', path: '/printing/job-cards', desc: 'Daftar kartu kerja cetak dan kendali kuantitas per batch' },
      { name: 'Target Harian', path: '/printing/daily-target', desc: 'Pencatatan dan evaluasi ketercapaian target harian' },
      { name: 'Tugas Saya', path: '/tasks', desc: 'Daftar penugasan operasional divisi printing' },
    ],
  },

  SAMPLE_PIC: {
    title: 'Sample Maker PIC',
    pic: 'Fahrul',
    icon: Scissors,
    tone: 'blue',
    summary: 'Spesialis pembuatan prototype & sample garmen: penerimaan task sample dari CMO, pembuatan pola/sample fisik, pengunggahan bukti dokumentasi foto berversi (evidence), dan pelaporan kesiapan ke buyer.',
    dailyRoutine: [
      { step: 'Buka Sample Today (/sample/today)', desc: 'Tinjau pesanan sample hari ini, antrean prioritas pembuatan, dan deadline persetujuan buyer.' },
      { step: 'Ambil & Mulai Sample Tasks (/sample/tasks)', desc: 'Buka kartu tugas (My Sample Tasks). Ubah status tugas menjadi "IN_PROGRESS" saat mulai memotong kain dan membuat pola.' },
      { step: 'Pembuatan Prototype Fisik', desc: 'Buat sample dengan standar fitting, bahan, dan jahitan presisi sesuai techpack/artwork buyer.' },
      { step: 'Unggah Bukti Dokumentasi Fisik (/sample/lifecycle)', desc: 'Unggah foto detail sample jadi (tampak depan, belakang, jahitan dalam, label). Setiap sample diberi nomor versi (V1, V2, dst) yang terkunci secara permanen (immutable).' },
      { step: 'Kirim Sample & Laporkan Kesiapan', desc: 'Serahkan sample ke Deby/Cecep untuk dikirimkan ke pihak buyer.' },
    ],
    dos: [
      'Mengerjakan prototype sample fisik sesuai spesifikasi pesanan.',
      'Mengunggah dokumentasi foto bukti pengerjaan sample berversi.',
      'Mencatat progres waktu kerja mulai dan selesai pembuatan sample.',
      'Melaporkan kendala bahan/pola sample ke antrean CMO.',
    ],
    donts: [
      'DILARANG menekan tombol persetujuan buyer (BUYER APPROVAL) — status persetujuan buyer murni hak pelanggan yang diinput oleh CMO.',
      'DILARANG mengedit atau menimpa bukti foto sample yang sudah disetujui (versi bersifat read-only).',
      'DILARANG mengerjakan produksi massal di luar pembuatan sample prototype.',
    ],
    keyPages: [
      { name: 'Sample Today', path: '/sample/today', desc: 'Dashboard ringkasan antrean sample harian Fahrul' },
      { name: 'My Sample Tasks', path: '/sample/tasks', desc: 'Daftar penugasan pembuatan sample dan input progres kerja' },
      { name: 'Sample Lifecycle', path: '/sample/lifecycle', desc: 'Audit versi sample, riwayat penolakan/perbaikan, dan bukti foto' },
      { name: 'Master Control', path: '/master', desc: 'Monitoring status global order (akses read-only)' },
    ],
  },

  CHRO_MANAGER: {
    title: 'Chief Human Resources Officer (CHRO Manager)',
    pic: 'Yuni',
    icon: Users,
    tone: 'green',
    summary: 'Pengelola sumber daya manusia: Employee Master kepegawaian, pengadaan tenaga kerja (recruitment), masa orientasi 2 minggu, evaluasi kinerja berkala (6 parameter), penanganan isu karyawan, dan serah terima payroll ke CFO.',
    dailyRoutine: [
      { step: 'Buka HR Today (/chro)', desc: 'Tinjau metrik SDM: permintaan karyawan baru, masa kontrak habis, training berjalan, dan isu karyawan terbuka.' },
      { step: 'Kelola Master Pegawai (/chro/employees)', desc: 'Pastikan seluruh data pegawai valid (NIP, Nama, Divisi, Jabatan, Tanggal Masuk, Status Kontrak). Tidak ada data dummy yang tertinggal.' },
      { step: 'Proses Permintaan SDM (Manpower Requests)', desc: 'Tinjau form permintaan tambahan operator dari divisi produksi Siti. Buka lowongan dan kelola seleksi kandidat.' },
      { step: 'Kawal Onboarding 2 Minggu & Training', desc: 'Pastikan karyawan baru mengikuti program pelatihan 2 minggu di lini produksi.' },
      { step: 'Fasilitasi Evaluasi 6 Parameter (/chro/performance)', desc: 'Kawal penilaian kinerja berkala oleh Kepala Divisi terkait pada 6 pilar: Quality, Responsibility, Discipline, Spiritual, Attitude, Skill.' },
      { step: 'Tangani People Issues & Eskalasi (/chro/issues)', desc: 'Selesaikan pelanggaran kedisiplinan tingkat ringan/sedang. Untuk kasus berat berisiko fraud/pidana, eskalasikan ke CEO Action Tracker.' },
      { step: 'Serah Terima Payroll ke CFO', desc: 'Kirimkan rekapitulasi status kelulusan probation/status aktif pegawai ke CFO untuk pemrosesan gaji.' },
    ],
    dos: [
      'Mengelola Employee Master, rekrutmen kandidat, dan siklus kepegawaian.',
      'Memfasilitasi masa orientasi 2 minggu dan evaluasi kinerja 6 parameter.',
      'Menangani konseling karyawan dan mediasi isu internal divisi.',
      'Membaca data absensi karyawan yang dicatat oleh sistem CFO (Read-Only).',
    ],
    donts: [
      'DILARANG melakukan hard delete data karyawan atau riwayat kasus (gunakan status non-aktif/arsip berizin).',
      'DILARANG mengedit data nominal gaji/pembayaran payroll secara sepihak (wewenang eksklusif CFO).',
      'DILARANG menutup kasus pelanggaran berat berkategori RED tanpa persetujuan CEO.',
    ],
    keyPages: [
      { name: 'HR Today (CHRO Home)', path: '/chro', desc: 'Pusat komando SDM, metrik karyawan, dan antrean tindakan HR' },
      { name: 'Employee Master', path: '/chro/employees', desc: 'Basis data resmi master seluruh karyawan perusahaan' },
      { name: 'Recruitment & Manpower', path: '/chro/recruitment', desc: 'Pengajuan kebutuhan tenaga kerja dan tracking kandidat' },
      { name: 'Training & Onboarding', path: '/chro/training', desc: 'Jadwal pelatihan dan siklus masa orientasi 2 minggu' },
      { name: 'Performance Reviews', path: '/chro/performance', desc: 'Evaluasi berkala 6 parameter oleh manager terkait' },
      { name: 'Employee Issues', path: '/chro/issues', desc: 'Pencatatan dan penyelesaian kasus kedisiplinan pegawai' },
    ],
  },
};

const FLOW_STEPS = [
  {
    step: '1. PO Intake & Order',
    owner: 'Deby (CMO Support) & Cecep (CMO Manager)',
    desc: 'Deby input data PO buyer, upload dokumen PDF asli, tentukan rute produksi (Cutting > Sewing > QC), lalu kirim ke Cecep. Cecep klik "Accept" untuk mengaktifkan Order.',
    gate: 'Order aktif dan memiliki nomor SO resmi. Rute produksi terkunci permanen.',
    tone: 'blue',
  },
  {
    step: '2. Quotation & Pricing Gate',
    owner: 'Cecep (CMO Manager) & Riadi (CFO Manager)',
    desc: 'Cecep tentukan harga jual per artikel. Riadi memeriksa kelayakan margin terhadap kebijakan bisnis. Jika margin >= 15%, Riadi klik "Approve Quotation".',
    gate: 'Quotation berstatus APPROVED. Jika margin di bawah batas, wajib eskalasi ke CEO.',
    tone: 'amber',
  },
  {
    step: '3. Down Payment & Finance Gate',
    owner: 'Riadi (CFO Manager)',
    desc: 'Riadi menerbitkan Invoice DP (min 30%). Setelah buyer transfer, pembayaran dicatat dan direkonsiliasi. Riadi menyetujui "Finance Gate".',
    gate: 'Finance Gate berstatus CLEAR. Lantai produksi tidak boleh bergerak sebelum DP lunas.',
    tone: 'amber',
  },
  {
    step: '4. Sample & Development (Jika Diminta)',
    owner: 'Fahrul (Sample Maker) & Buyer (via CMO)',
    desc: 'Fahrul membuat sample fisik, mengunggah foto bukti berversi (V1, V2), dan mengirim ke buyer. Keputusan buyer dicatat sebagai APPROVED.',
    gate: 'Sample berstatus APPROVED. Tanpa approval sample, rilis SPK ke produksi diblokir.',
    tone: 'blue',
  },
  {
    step: '5. Material & Rencana Produksi',
    owner: 'Siti (COO Manager) & Riadi (CFO Manager)',
    desc: 'Siti menyusun BOM dan mengajukan Material Request. Riadi membeli bahan hingga PO vendor READY. Siti menetapkan jadwal dan Approve Production Plan.',
    gate: 'Material READY dan Production Plan APPROVED.',
    tone: 'green',
  },
  {
    step: '6. Release SPK & Eksekusi Fisik',
    owner: 'Deby (Print SPK), Cecep (Release), Siti & Iman (Pabrik)',
    desc: 'Deby generate & cetak fisik SPK ber-barcode. Cecep klik "Release SPK". Tim pabrik mengeksekusi urut rute (Cutting -> Printing Iman -> Sewing -> QC).',
    gate: 'Setiap handoff wajib seimbang: Qty Masuk = Selesai + Reject + Sisa.',
    tone: 'green',
  },
  {
    step: '7. QC Final, Packing & Shipment',
    owner: 'Siti (COO) & Riadi (CFO)',
    desc: 'Setelah QC PASS 100%, Siti mengemas (PACKED) dengan rekonsiliasi kuantitas baris artikel. Riadi menyetujui Finance Gate Pengiriman. Barang diberangkatkan (SHIPPED).',
    gate: 'QC PASS 100%, Shipment PACKED terekonsiliasi, dan Finance Gate Pengiriman CLEAR.',
    tone: 'green',
  },
  {
    step: '8. Serah Terima Fisik & 3-Way Closing',
    owner: 'Siti (COO), Cecep (CMO), Riadi (CFO)',
    desc: 'Siti mencatat serah terima fisik (DELIVERED). Cecep mencatat kepuasan buyer (Customer Close). Siti menutup operasional. Riadi memverifikasi saldo nol & menutup finansial.',
    gate: 'Ketiga pilar (Customer + Operational + Financial) tertutup. Order resmi CLOSED.',
    tone: 'blue',
  },
];

const FAQS = [
  {
    q: 'Kenapa tombol "Release SPK" tidak bisa diklik / ditolak oleh sistem?',
    a: 'Sistem menerapkan perlindungan bertingkat. SPK hanya bisa dirilis jika seluruh gerbang terpenuhi: 1) Dokumen SPK sudah di-Generate dan di-Print oleh Deby; 2) Quotation telah disetujui CFO; 3) Finance Gate pembayaran DP telah disetujui CFO; 4) Approval sample buyer sudah masuk (jika artikel mewajibkan sample); 5) Rencana Produksi telah disetujui COO; dan 6) Kebutuhan bahan baku berstatus READY.',
  },
  {
    q: 'Kenapa muncul error "PACKED shipment requires reconciled article quantities"?',
    a: 'Saat mengemas pengiriman (PACKED), sistem mewajibkan verifikasi alokasi kuantitas per artikel (shipment lines). Pastikan jumlah barang yang dikemas persis sama dengan kuantitas artikel pesanan dan tidak melebihi hasil yang lulus QC Final.',
  },
  {
    q: 'Kenapa saya tidak bisa mengetik angka pelunasan langsung di kolom invoice?',
    a: 'Untuk mencegah kecurangan dan kesalahan ketik (*anti-fraud*), nominal terbayar dihitung secara otomatis oleh sistem dari data transaksi pembayaran riil yang diverifikasi dengan mutasi bank (rekonsiliasi). Untuk mencatat pembayaran, gunakan form "Catat Pembayaran" di menu CFO.',
  },
  {
    q: 'Bagaimana jika salah mengisi Rute Produksi saat pembuatan pesanan?',
    a: 'Demi integritas data pabrik, rute produksi bersifat permanen (immutable) dan tidak dapat diubah setelah order aktif. Jika salah rute, order tersebut harus dibatalkan sebelum SPK dirilis, dan PO intake baru dibuat dengan rute yang benar (misalnya: "Cutting > Printing > Sewing > QC").',
  },
  {
    q: 'Kenapa Sample Maker (Fahrul) atau Deby tidak bisa menyetujui status Sample?',
    a: 'Sesuai SOP pemisahan wewenang (*segregation of duties*), orang yang membuat barang dilarang menyetujui hasil kerjanya sendiri. Fahrul bertugas mengunggah foto bukti fisik sample berversi (V1, V2), sedangkan persetujuan approval murni hak pelanggan yang diinput secara transparan oleh CMO Manager.',
  },
  {
    q: 'Kenapa akun CEO tidak memiliki menu untuk membuat Purchase Order atau Surat Jalan?',
    a: 'Berdasarkan blueprint tata kelola BOS Syams (Revisi #74 & #77), CEO tidak memiliki workspace operasional harian. Pembelian material adalah wewenang CFO/Purchasing Riadi, dan pengiriman fisik adalah wewenang COO Siti. CEO bertindak sebagai pengawas strategis (read-only audit) dan pemutus eskalasi darurat.',
  },
  {
    q: 'Kenapa penutupan order (Closing) membutuhkan 3 orang berbeda?',
    a: 'BOS Syams menerapkan mekanisme kontrol 3-Way Closing: CMO menutup sisi kepuasan pelanggan (Customer Close), COO menutup ketiadaan sisa tanggungan di pabrik (Operational Close), dan CFO menutup pelunasan buku kas (Financial Close). Status ORDER CLOSED baru aktif otomatis bila ketiganya lengkap.',
  },
];

export default function GuidePage() {
  const context = useOutletContext();
  const currentRole = context?.me?.role || 'CEO';

  // Map user's actual role to the guide key
  const defaultRoleKey = useMemo(() => {
    if (ROLE_GUIDES[currentRole]) return currentRole;
    if (['CHRO_MANAGER', 'HR_SUPPORT'].includes(currentRole)) return 'CHRO_MANAGER';
    if (['CFO_MANAGER', 'FINANCE_SUPPORT'].includes(currentRole)) return 'CFO_MANAGER';
    if (['COO_MANAGER', 'PRODUCTION_PIC', 'SHIPMENT_ADMIN'].includes(currentRole)) return 'COO_MANAGER';
    if (currentRole === 'PRINTING_PIC') return 'PRINTING_PIC';
    if (currentRole === 'SAMPLE_PIC') return 'SAMPLE_PIC';
    if (currentRole === 'CMO_SUPPORT') return 'CMO_SUPPORT';
    if (currentRole === 'CMO_MANAGER') return 'CMO_MANAGER';
    return 'CEO';
  }, [currentRole]);

  const [selectedRole, setSelectedRole] = useState(defaultRoleKey);
  const [searchQuery, setSearchQuery] = useState('');
  const [openFaq, setOpenFaq] = useState(null);

  const guide = ROLE_GUIDES[selectedRole] || ROLE_GUIDES.CEO;
  const RoleIcon = guide.icon;

  // Filter FAQs based on search
  const filteredFaqs = useMemo(() => {
    if (!searchQuery.trim()) return FAQS;
    const q = searchQuery.toLowerCase();
    return FAQS.filter(f => f.q.toLowerCase().includes(q) || f.a.toLowerCase().includes(q));
  }, [searchQuery]);

  return (
    <div className="page" style={{ maxWidth: 1400, margin: '0 auto', paddingBottom: 60 }}>
      {/* Header Halaman */}
      <div className="page-title" style={{ marginBottom: 24 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 800 }}>Buku Panduan & SOP Operasional</h1>
            <span className="badge blue" style={{ fontSize: 12, padding: '4px 10px' }}>Versi 0.2.0 (Revisi #1 – #78)</span>
          </div>
          <p style={{ margin: '6px 0 0', color: '#64748b', fontSize: 14 }}>
            Panduan lengkap alur kerja, batas kewenangan tegas, dan petunjuk teknis spesifik untuk seluruh peran di BOS Syams.
          </p>
        </div>
      </div>

      {/* Banner Informasi Peran Aktif */}
      <div style={{
        background: 'linear-gradient(135deg, #1e3a5f 0%, #0c2b52 100%)',
        color: 'white',
        borderRadius: 14,
        padding: '20px 24px',
        marginBottom: 28,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 16,
        boxShadow: '0 4px 14px rgba(12, 43, 82, 0.15)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: 'rgba(255,255,255,0.15)',
            display: 'grid',
            placeItems: 'center',
            fontSize: 22
          }}>
            <RoleIcon size={26} color="#93c5fd" />
          </div>
          <div>
            <div style={{ fontSize: 12, opacity: 0.8, textTransform: 'uppercase', letterSpacing: 0.5 }}>Peran Anda Saat Ini</div>
            <strong style={{ fontSize: 18, fontWeight: 700 }}>{context?.me?.name || 'Pengguna'} ({currentRole.replaceAll('_', ' ')})</strong>
            <div style={{ fontSize: 13, opacity: 0.9, marginTop: 2 }}>Panduan di bawah ini disesuaikan dengan wewenang login akun Anda.</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 13, opacity: 0.85 }}>Pindah panduan peran:</span>
          <select
            value={selectedRole}
            onChange={(e) => setSelectedRole(e.target.value)}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid rgba(255,255,255,0.3)',
              background: '#153e6d',
              color: 'white',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              outline: 'none'
            }}
          >
            <option value="CEO">👑 CEO (Iyan)</option>
            <option value="CMO_MANAGER">🎯 CMO Manager (Cecep)</option>
            <option value="CMO_SUPPORT">📋 CMO Support (Deby)</option>
            <option value="CFO_MANAGER">💰 CFO Manager (Riadi)</option>
            <option value="COO_MANAGER">🏭 COO Manager (Siti)</option>
            <option value="PRINTING_PIC">🖨️ Printing PIC (Iman)</option>
            <option value="SAMPLE_PIC">🧵 Sample PIC (Fahrul)</option>
            <option value="CHRO_MANAGER">👥 CHRO / HR (Yuni)</option>
          </select>
        </div>
      </div>

      {/* Selector Tab Peran Cepat */}
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 10, marginBottom: 20 }}>
        {[
          { key: 'CEO', label: 'CEO (Iyan)', icon: Crown },
          { key: 'CMO_MANAGER', label: 'CMO Mgr (Cecep)', icon: Target },
          { key: 'CMO_SUPPORT', label: 'CMO Spt (Deby)', icon: FileText },
          { key: 'CFO_MANAGER', label: 'CFO Mgr (Riadi)', icon: DollarSign },
          { key: 'COO_MANAGER', label: 'COO Mgr (Siti)', icon: Factory },
          { key: 'PRINTING_PIC', label: 'Printing (Iman)', icon: Printer },
          { key: 'SAMPLE_PIC', label: 'Sample (Fahrul)', icon: Scissors },
          { key: 'CHRO_MANAGER', label: 'CHRO (Yuni)', icon: Users },
        ].map((r) => {
          const Icon = r.icon;
          const isActive = selectedRole === r.key;
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => setSelectedRole(r.key)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 16px',
                borderRadius: 10,
                border: isActive ? '2px solid #2563eb' : '1px solid #e2e8f0',
                background: isActive ? '#eff6ff' : 'white',
                color: isActive ? '#1d4ed8' : '#475569',
                fontWeight: isActive ? 700 : 500,
                fontSize: 13,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s ease'
              }}
            >
              <Icon size={16} />
              <span>{r.label}</span>
            </button>
          );
        })}
      </div>

      {/* Detail Panduan Peran Terpilih */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20, marginBottom: 32 }}>
        {/* Kolom Kiri: SOP & Rutinitas Harian */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <section className="panel" style={{ margin: 0 }}>
            <div className="panel-head" style={{ borderBottom: '1px solid #edf2f7', paddingBottom: 14, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: '#dbeafe', display: 'grid', placeItems: 'center' }}>
                  <RoleIcon size={22} color="#1d4ed8" />
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: 19 }}>{guide.title}</h2>
                  <span style={{ fontSize: 13, color: '#64748b' }}>Penanggung Jawab Utama: <b>{guide.pic}</b></span>
                </div>
              </div>
            </div>

            <p style={{ fontSize: 14, lineHeight: 1.6, color: '#334155', background: '#f8fafc', padding: 14, borderRadius: 8, borderLeft: '4px solid #3b82f6', margin: '0 0 20px' }}>
              {guide.summary}
            </p>

            <h3 style={{ fontSize: 16, margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Clock size={18} color="#2563eb" /> Alur Kerja & SOP Harian (Step-by-Step)
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {guide.dailyRoutine.map((item, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 14, padding: '12px 14px', background: '#ffffff', border: '1px solid #eef2f6', borderRadius: 10 }}>
                  <div style={{
                    width: 28,
                    height: 28,
                    borderRadius: '50%',
                    background: '#2563eb',
                    color: 'white',
                    display: 'grid',
                    placeItems: 'center',
                    fontWeight: 700,
                    fontSize: 13,
                    flexShrink: 0
                  }}>
                    {idx + 1}
                  </div>
                  <div>
                    <strong style={{ fontSize: 14, color: '#0f172a' }}>{item.step}</strong>
                    <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b', lineHeight: 1.5 }}>{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Batas Kewenangan (Do's & Don'ts) */}
          <section className="panel" style={{ margin: 0 }}>
            <div className="panel-head" style={{ marginBottom: 14 }}>
              <h2 style={{ fontSize: 17, display: 'flex', alignItems: 'center', gap: 8 }}>
                <ShieldCheck size={20} color="#16a34a" /> Batas Kewenangan & Integritas Peran
              </h2>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {/* Apa yang Boleh */}
              <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: 16 }}>
                <h4 style={{ margin: '0 0 10px', color: '#166534', fontSize: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <CheckCircle2 size={16} color="#16a34a" /> Wewenang Resmi (DO):
                </h4>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#14532d', lineHeight: 1.6 }}>
                  {guide.dos.map((item, i) => (
                    <li key={i} style={{ marginBottom: 6 }}>{item}</li>
                  ))}
                </ul>
              </div>

              {/* Apa yang Dilarang */}
              <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: 16 }}>
                <h4 style={{ margin: '0 0 10px', color: '#991b1b', fontSize: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <AlertTriangle size={16} color="#dc2626" /> Batasan Ketat (DON'T):
                </h4>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#7f1d1d', lineHeight: 1.6 }}>
                  {guide.donts.map((item, i) => (
                    <li key={i} style={{ marginBottom: 6 }}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          </section>
        </div>

        {/* Kolom Kanan: Menu Kerja & Tautan Langsung */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <section className="panel" style={{ margin: 0 }}>
            <div className="panel-head" style={{ marginBottom: 14 }}>
              <h2 style={{ fontSize: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <BookOpen size={18} color="#2563eb" /> Halaman Kerja Utama {guide.pic}
              </h2>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {guide.keyPages.map((pg, i) => (
                <div key={i} style={{ padding: '10px 12px', border: '1px solid #eef2f6', borderRadius: 8, background: '#fafafa' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <b style={{ fontSize: 13, color: '#0f172a' }}>{pg.name}</b>
                    <Link to={pg.path} className="btn sm primary" style={{ padding: '3px 8px', fontSize: 11 }}>
                      Buka <ArrowRight size={12} />
                    </Link>
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: 12, color: '#64748b' }}>{pg.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Tips Produktivitas */}
          <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 12, padding: 18 }}>
            <h4 style={{ margin: '0 0 8px', fontSize: 14, color: '#92400e', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Info size={16} color="#b45309" /> Tips Operasional BOS Syams:
            </h4>
            <p style={{ margin: 0, fontSize: 13, color: '#78350f', lineHeight: 1.5 }}>
              Jika ada tombol tindakan yang berwarna abu-abu (disabled) atau memunculkan pesan peringatan penolakan,
              periksa tab <strong>"Alur 8 Gate Utama"</strong> di bawah. Hampir selalu ada tahapan di divisi sebelumnya yang belum tuntas atau belum disetujui.
            </p>
          </div>
        </div>
      </div>

      {/* Bagian 2: Alur 8 Gate Utama Produksi & Pengiriman */}
      <section className="panel" style={{ marginBottom: 32 }}>
        <div className="panel-head" style={{ marginBottom: 18 }}>
          <div>
            <h2 style={{ fontSize: 19, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Layers size={20} color="#2563eb" /> Diagram Alur Bisnis & 8 Gerbang (Gate) Utama
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b' }}>
              Sistem menolak lompatan tahap (*anti-bypass*). Setiap tahapan memiliki penanggung jawab khusus dan syarat lolos mutlak.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {FLOW_STEPS.map((step, i) => (
            <div key={i} style={{ display: 'flex', gap: 16, padding: '16px 18px', border: '1px solid #e2e8f0', borderRadius: 12, background: i % 2 === 0 ? '#ffffff' : '#f8fafc' }}>
              <div style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: step.tone === 'blue' ? '#dbeafe' : step.tone === 'amber' ? '#fef3c7' : '#dcfce7',
                color: step.tone === 'blue' ? '#1e40af' : step.tone === 'amber' ? '#92400e' : '#166534',
                display: 'grid',
                placeItems: 'center',
                fontWeight: 800,
                fontSize: 16,
                flexShrink: 0
              }}>
                {i + 1}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{step.step}</h3>
                  <span className={`badge ${step.tone}`}>{step.owner}</span>
                </div>
                <p style={{ margin: '6px 0 8px', fontSize: 13, color: '#334155', lineHeight: 1.5 }}>{step.desc}</p>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
                  <Lock size={12} color="#64748b" /> <strong>Syarat Lolos Gate:</strong> {step.gate}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Bagian 3: Tanya Jawab Kendala Teknis (Troubleshooting & FAQs) */}
      <section className="panel">
        <div className="panel-head" style={{ marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ fontSize: 19, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <HelpCircle size={20} color="#2563eb" /> Kamus Masalah & Solusi (Troubleshooting Gate Terkunci)
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b' }}>
              Solusi cepat saat tombol tidak merespon atau muncul pesan penolakan dari sistem.
            </p>
          </div>

          <div style={{ position: 'relative', width: 280 }}>
            <input
              type="text"
              placeholder="Cari pertanyaan kendala..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px 8px 34px',
                borderRadius: 8,
                border: '1px solid #d1d5db',
                fontSize: 13,
                outline: 'none'
              }}
            />
            <Search size={16} color="#94a3b8" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filteredFaqs.map((f, i) => {
            const isOpen = openFaq === i;
            return (
              <div key={i} style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
                <button
                  type="button"
                  onClick={() => setOpenFaq(isOpen ? null : i)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '14px 18px',
                    background: isOpen ? '#f8fafc' : 'white',
                    border: 'none',
                    textAlign: 'left',
                    cursor: 'pointer',
                    fontSize: 14,
                    fontWeight: 700,
                    color: '#0f172a'
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="dot yellow"></span>
                    {f.q}
                  </span>
                  {isOpen ? <ChevronUp size={18} color="#64748b" /> : <ChevronDown size={18} color="#64748b" />}
                </button>
                {isOpen && (
                  <div style={{ padding: '14px 18px 18px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: 13, color: '#475569', lineHeight: 1.6 }}>
                    {f.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
