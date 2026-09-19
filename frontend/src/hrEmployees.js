// Employee Master & Lifecycle (revisi #62, #67) — logika murni untuk halaman HR.
//
// Halaman ini read-only terhadap attendance & payroll (keduanya milik CFO) dan
// read-only terhadap Employee Master itu sendiri: tidak ada tombol hapus, tidak
// ada form tulis. Semua derivasi di bawah ini dihitung dari payload
// GET /api/hr/employees-summary dan GET /api/hr/employees/{id}/lifecycle supaya
// bisa diuji tanpa DOM dan tidak ada angka yang di-hard-code.

export const SUMMARY_ENDPOINT = '/hr/employees-summary';
export const lifecycleEndpoint = (id) => `/hr/employees/${id}/lifecycle`;

// Status yang masih memakai slot headcount.
export const OPEN_STATUSES = ['ACTIVE', 'PROBATION', 'TRAINING', 'CONTRACT', 'EXTENDED'];

// Label manusiawi + nada warna untuk status kepegawaian.
const STATUS_LABEL = {
  ACTIVE: 'Aktif',
  PROBATION: 'Percobaan',
  TRAINING: 'Masa training',
  CONTRACT: 'Kontrak',
  EXTENDED: 'Kontrak diperpanjang',
  ON_LEAVE: 'Cuti',
  INACTIVE: 'Nonaktif',
  TERMINATED: 'Berhenti (terminate)',
  RESIGNED: 'Mengundurkan diri',
  EXITED: 'Sudah keluar',
  RETIRED: 'Pensiun',
  UNKNOWN: 'Tidak diketahui',
};

export const MIGRATION_FLAG_LABEL = {
  SEED_DEMO_ROW: 'Data seed/demo — tidak boleh ada di produksi',
  MISSING_EMPLOYEE_NO: 'NIP kosong',
  MISSING_JOIN_DATE: 'Tanggal masuk kosong',
  JOIN_DATE_NOT_MIGRATED: 'Tanggal masuk belum dimigrasi (pakai created_at)',
  MISSING_DIVISION: 'Divisi kosong',
  MISSING_POSITION: 'Posisi kosong',
  MISSING_MANAGER: 'Atasan belum diisi',
  CONTRACT_EXPIRED_BUT_OPEN: 'Kontrak lewat tapi status masih terbuka',
  CONTRACT_FIELDS_NOT_MIGRATED: 'Kolom kontrak belum dimigrasi',
  EXIT_DATE_BUT_OPEN: 'Ada tanggal keluar tapi status masih terbuka',
};

export const EVENT_LABEL = {
  JOINED: 'Masuk kerja',
  TRAINING_START: 'Mulai training',
  TRAINING_END: 'Selesai training',
  PERFORMANCE_REVIEW: 'Performance review',
  EMPLOYEE_ISSUE: 'Employee issue',
  CONTRACT_END: 'Kontrak berakhir',
  EXIT: 'Keluar',
  MIGRATED: 'Migrasi data',
};

export function statusLabel(status) {
  const key = String(status || '').toUpperCase();
  return STATUS_LABEL[key] || key || '-';
}

// Revisi #62: jangan hard delete — status tertutup berarti arsip, bukan hapus.
export function isOpenStatus(status) {
  return OPEN_STATUSES.includes(String(status || '').toUpperCase());
}

export function migrationLabel(flag) {
  return MIGRATION_FLAG_LABEL[flag] || flag;
}

export function eventLabel(type) {
  return EVENT_LABEL[type] || type;
}

export function employeeLabel(row) {
  if (!row) return '-';
  const no = row.employee_no || 'tanpa NIP';
  return `${no} · ${row.name || 'tanpa nama'}`;
}

// Ringkasan siap-tampil: angka datang dari server, bukan dihitung ulang di UI.
export function summaryTiles(summary) {
  if (!summary) return [];
  const contract = summary.contract_watch || {};
  const migration = summary.migration || {};
  return [
    { label: 'Total karyawan', value: summary.total ?? 0, hint: 'Semua baris Employee Master' },
    { label: 'Aktif (headcount)', value: summary.headcount_active ?? 0, hint: 'Masih memakai slot headcount' },
    { label: 'Tidak aktif', value: summary.headcount_inactive ?? 0, hint: 'Arsip, bukan dihapus' },
    { label: `Kontrak \u2264 ${contract.window_days ?? 30} hari`, value: contract.count ?? 0, hint: 'Perlu ditindak HR' },
    { label: 'Kontrak lewat', value: contract.expired_count ?? 0, hint: 'Status masih terbuka' },
    { label: 'Perlu migrasi', value: migration.needs_migration ?? 0, hint: 'Kelengkapan data warisan' },
  ];
}

export function statusBreakdown(summary) {
  const rows = summary?.by_employment_status || [];
  return rows.map((row) => ({
    status: row.employment_status,
    label: statusLabel(row.employment_status),
    count: row.count,
    open: isOpenStatus(row.employment_status),
  }));
}

// Baris kontrak yang mendesak, sudah diurutkan menaik oleh server.
export function contractWatchList(summary) {
  const rows = summary?.contract_watch?.employees || [];
  return rows.map((row) => ({
    ...row,
    label: employeeLabel(row),
    daysLabel: row.days_to_contract_end < 0
      ? `lewat ${Math.abs(row.days_to_contract_end)} hari`
      : `${row.days_to_contract_end} hari lagi`,
    urgent: row.days_to_contract_end <= 7,
  }));
}

// Karyawan yang datanya belum lengkap — daftar kerja migrasi.
export function migrationQueue(summary) {
  return (summary?.employees || [])
    .filter((row) => row.needs_migration)
    .map((row) => ({ ...row, label: employeeLabel(row), reasons: (row.migration_flags || []).map(migrationLabel) }));
}

// ringkasan attendance = read-only dan bersumber CFO. Kalau belum tersedia,
// UI harus bilang "belum tersedia", bukan menampilkan angka nol palsu.
export function attendanceNotice(summary) {
  const attendance = summary?.attendance;
  if (!attendance) return { available: false, text: 'Ringkasan attendance belum tersedia dari CFO.' };
  if (attendance.available) {
    return { available: true, text: `Sumber: ${attendance.source}. HR hanya membaca, tidak mengubah.` };
  }
  return {
    available: false,
    text: attendance.reason || 'Ringkasan attendance belum tersedia dari CFO.',
  };
}

// Revisi #67: HR tidak boleh punya aksi tulis di halaman ini.
export function readOnlyActions() {
  return ['Lihat lifecycle', 'Lihat kontrak', 'Lihat jejak HR'];
}

// Jejak HR (training/performance/issue) — bukan pengganti attendance CFO.
export function hrTraceTiles(summary) {
  const trace = summary?.hr_trace;
  if (!trace) return [];
  return [
    { label: 'Record training', value: trace.training_records ?? 0 },
    { label: 'Karyawan belum training', value: trace.employees_without_training ?? 0 },
    { label: 'Record performance', value: trace.performance_records ?? 0 },
    { label: 'Karyawan belum dinilai', value: trace.employees_without_performance ?? 0 },
    { label: 'Employee issue', value: trace.employee_issues ?? 0 },
    { label: 'Issue masih terbuka', value: trace.open_issues ?? 0 },
  ];
}

// Timeline lifecycle untuk modal; tanggal null tetap tampil sebagai "tanggal tidak diketahui"
// supaya tidak berpura-pura punya data.
export function timelineRows(lifecycle) {
  return (lifecycle?.events || []).map((event) => ({
    ...event,
    typeLabel: eventLabel(event.type),
    dateLabel: event.date || 'tanggal tidak diketahui',
  }));
}
