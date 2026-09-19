/* SIDEBAR MENU — kontrak data murni (Batch 2).

   Kenapa file ini ada: `components/Layout.jsx`, `business.js` dan `main.jsx` ada
   di daftar file terlarang AGENT-RULES.md §1, jadi batch-1 dan batch-2 hanya bisa
   MENGUSULKAN entri sidebar lewat `REQUESTS/*.md`. Akibatnya 11 halaman baru
   punya route + hak akses, tetapi tidak punya jalan klik dari UI.

   Modul ini sengaja TANPA JSX supaya bisa diuji langsung oleh `node --test`
   (frontend memakai node --test, bukan vitest) — lihat
   `tests/sidebarMenu.test.mjs`. Komponen pemasangnya ada di
   `components/SidebarMenu.jsx`.

   Cara pasang di Layout.jsx (detail di REQUESTS/sidebar.md):

     import {mergeMenus,footerFor} from './SidebarMenu.js';
     ...
     const menus=mergeMenus(roleMenus, me?.role);   // menggantikan visibleMenus()
     const foot=footerFor(me?.role);                // menggantikan footerLinks()

   Kedua fungsi mengembalikan baris `[label, path, iconName]`. `roleMenus` milik
   Layout.jsx memakai elemen komponen ikon, jadi cukup dipetakan sekali:
   `Lucide[iconName]` (atau helper `resolveIcon` di SidebarMenu.jsx).

   BATAS PERAN YANG DIPEGANG (jangan dilanggar saat memasang):
   - CEO tidak punya halaman kerja operasional (revisi #74/#77). `menusFor('CEO')`
     kosong: CEO tetap memakai sidebar Layout.jsx yang sudah ada + drill-down
     read-only. Halaman batch-1 tidak ditambahkan ke CEO hanya karena
     `/cmo/priority-v2` memberi CEO hak baca (revisi #14 poin 2 masih menunggu
     keputusan orkestrator apakah menu CMO Manager dipakai bersama).
   - SAMPLE_PIC: 7 entri final, urut sesuai revisi #31 (Keluar = tombol footer).
   - PRINTING_PIC: 8 entri, urut sesuai revisi #41/#43/#47 (Panduan/Usulan
     Revisi/Task/Keluar = footer).
   - CHRO/HR tidak pernah mendapat menu Production/Printing/Sample work.
*/

/* ── Kelompok menu per peran ───────────────────────────────────────────────
   Satu blok per divisi supaya penggabungan oleh orkestrator tidak menimpa daftar
   yang sudah ada. `null` = divisi belum punya entri nav tambahan. */

/* HR — revisi #62 (Employee Master) & #63-#66 (Recruitment, Performance, Issue). */
export const HR_MENUS={
  CHRO_MANAGER:[
    ['Employees','/chro/employees','Users'],
    ['Recruitment','/chro/recruitment','UserPlus'],
    ['Training','/chro/training','BookOpen'],
    ['Performance','/chro/performance','BarChart3'],
    ['Employee Issues','/chro/issues','AlertTriangle'],
    ['Master Control','/master','Database'],
  ],
  HR_SUPPORT:[
    ['Employees','/chro/employees','Users'],
    ['Recruitment','/chro/recruitment','UserPlus'],
    ['Training','/chro/training','BookOpen'],
    ['Master Control — Lihat Saja','/master','Database'],
  ],
};

/* Sample — revisi #31 (sidebar final), #34/#36/#38 (lifecycle), #35/#37 (tasks).
   Urutan terkunci: Sample Today; My Sample Tasks; Sample Workspace;
   Sample Exception; Master Control — Lihat Saja; Usulan Revisi; Keluar.
   'Keluar' bukan entri nav: tombol logout di `.side-foot` (Layout.jsx sudah
   merendernya) — tidak dimasukkan supaya tidak dobel. 'Sample Workspace'
   menunjuk `/sample/lifecycle` (halaman lifecycle versi/bukti/immutability)
   karena itu satu-satunya route sample versi-baru yang terdaftar di main.jsx. */
export const SAMPLE_MENUS={
  SAMPLE_PIC:[
    ['Sample Today','/sample/today','Target'],
    ['My Sample Tasks','/sample/tasks','ClipboardList'],
    ['Sample Workspace','/sample/lifecycle','History'],
    ['Sample Exception','/exceptions','AlertTriangle'],
    ['Master Control — Lihat Saja','/master','Database'],
  ],
};

/* Printing — revisi #41/#42/#46/#47 (daily target, eligibility, makloon) dan
   #43-#45 (Job Card, quantity control, defect). Urutan blueprint Iman:
   My Tasks; Production Queue; Job Card; Daily Target; Master Control; Panduan;
   Usulan Revisi; Task; Keluar — sisanya ditangani `.side-foot`. */
export const PRINTING_MENUS={
  PRINTING_PIC:[
    ['My Tasks','/tasks','ClipboardList'],
    ['Production Queue','/coo/production','Factory'],
    ['Job Card','/printing/job-cards','FileText'],
    ['Daily Target','/printing/daily-target','Target'],
    ['Master Control','/master','Database'],
  ],
};

/* COO — revisi #53/#54/#57 (eksekusi harian, WIP/handoff/kapasitas, BOM fisik).
   COO_MANAGER juga berhak membuka Job Card & Daily Target Printing
   (`business.js`), jadi entrinya ikut muncul untuknya. */
export const COO_MENUS={
  COO_MANAGER:[
    ['COO Home','/coo','Home'],
    ['Eksekusi Harian','/coo/execution','Activity'],
    ['Material Requests','/coo/material-requests','Package'],
    ['Production Queue','/coo/production','Factory'],
    ['WIP Tracking','/coo/wip','Package'],
    ['QC Records','/coo/qc','CheckSquare'],
    ['Shipments & Serah Terima','/cfo/shipments','Truck'],
    ['Job Card Printing','/printing/job-cards','FileText'],
    ['Printing Daily Target','/printing/daily-target','Target'],
    ['Master Control','/master','Database'],
    ['Production Plan','/coo/planning','Factory'],
    ['Konfirmasi Customer (Lihat)','/coo/deliveries','Truck'],
    ['Closing Operasional','/coo/closing','CheckSquare'],
  ],
  PRODUCTION_PIC:[
    ['My Tasks','/tasks','ClipboardList'],
    ['Eksekusi Harian','/coo/execution','Activity'],
    ['Production Queue','/coo/production','Factory'],
    ['Material Requests','/coo/material-requests','Package'],
    ['Master Control','/master','Database'],
  ],
};

/* CFO — revisi #17/#20 (AR aging, AP supplier & makloon) dan #21/#24 (actual
   cost vs HPP, operational cost). 'CFO Home', 'Invoices', 'Purchase Orders',
   'Shipments Gate' dan 'Closing Keuangan' sudah ada di Layout.jsx; di sini
   ditambahkan dua halaman baru. CATATAN: revisi #21/#24 belum pernah diminta
   masuk sidebar oleh agent batch-1, padahal halamannya sudah ber-route +
   ber-hak-akses — jadi CFO hari ini juga tidak punya jalan klik ke /cfo/costing. */
export const CFO_MENUS={
  CFO_MANAGER:[
    ['Piutang & Collection','/cfo/receivables','DollarSign'],
    ['Actual Cost & HPP','/cfo/costing','BarChart3'],
  ],
  FINANCE_SUPPORT:[
    ['Piutang & Collection','/cfo/receivables','DollarSign'],
    ['Actual Cost & HPP','/cfo/costing','BarChart3'],
  ],
};

/* CMO — revisi #13/#14 poin 2 (Morning Priority action-first). Blueprint CMO
   Manager terkunci: urutannya tidak boleh berubah, jadi entri baru disisipkan
   tepat sesudah 'Morning Priority'. Deby (CMO Support) hanya LIHAT: feed
   approval sample & lifecycle sample, tanpa aksi tulis. */
export const CMO_MENUS={
  CMO_MANAGER:[
    ['Morning Priority V2','/cmo/priority-v2','Target'],
  ],
  CMO_SUPPORT:[
    ['Approval Sample (Lihat)','/cmo/sample-approval','ClipboardList'],
    ['Sample Lifecycle (Lihat)','/sample/lifecycle','History'],
  ],
};

export const MENUS_BY_ROLE={
  CEO:[],
  ...CMO_MENUS,...CFO_MENUS,...COO_MENUS,...SAMPLE_MENUS,...PRINTING_MENUS,...HR_MENUS,
  SHIPMENT_ADMIN:[],
};

/* Footer per peran. Menggantikan `footerLinks` di Layout.jsx: setiap entri
   dideklarasikan eksplisit per peran, bukan lagi aturan `if` berantai yang
   mudah bocor antar peran (itu isi catatan revisi #9/#14 poin 9). 'Keluar'
   tetap tombol terpisah di Layout.jsx. */
export const FOOTER_BY_ROLE={
  CEO:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList'],['Exception','/exceptions','AlertTriangle']],
  CMO_MANAGER:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList'],['Exception','/exceptions','AlertTriangle']],
  CMO_SUPPORT:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList']],
  CFO_MANAGER:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Exception','/exceptions','AlertTriangle']],
  FINANCE_SUPPORT:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus']],
  COO_MANAGER:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList'],['Exception','/exceptions','AlertTriangle']],
  PRODUCTION_PIC:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList']],
  PRINTING_PIC:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList']],
  SAMPLE_PIC:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Task','/tasks','ClipboardList']],
  CHRO_MANAGER:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus'],['Exception','/exceptions','AlertTriangle']],
  HR_SUPPORT:[['Panduan','/panduan','BookOpen'],['Usulan Revisi','/revisions','MessageSquarePlus']],
  SHIPMENT_ADMIN:[['Panduan','/panduan','BookOpen']],
};

/* URUTAN FINAL per peran. `rows` = daftar menu terurut yang dipakai kalau
   Layout.jsx tidak punya daftar lama untuk peran itu (peran baru / HR / PIC).
   `replace` = label lama di Layout.jsx yang digantikan entri baru pada posisi
   yang sama (mis. 'Employees' mengambil slot 'CHRO Home'). `after` = label lama
   yang menjadi acuan penyisipan (entri baru ditaruh tepat sesudahnya).
   Peran yang tidak disebut di sini memakai urutan lama Layout.jsx + entri baru
   di belakang, sehingga sidebar CMO/COO/CFO yang sudah dikunci revisi
   #9/#13/#14/#74 tidak diacak. */
export const ROLE_LAYOUT_ORDER={
  /* HR — revisi #62 (Employee Master) & #63-#66 (Recruitment/Performance/Issue).
     Urutan final: Employee Master, Recruitment, Training, Performance, Issues,
     Master Control (revisi #62 menyebut 'Employee Master' dulu). */
  CHRO_MANAGER:{replace:{'CHRO Home':'Employees'},after:{'Recruitment':'Employees','Training':'Recruitment'}},
  HR_SUPPORT:{replace:{'CHRO Home':'Employees'},after:{'Recruitment':'Employees','Training':'Recruitment'},front:['Employees','Recruitment','Training','Master Control — Lihat Saja']},
  /* CMO — revisi #14 poin 2: Morning Priority action-first. Blueprint CMO
     Manager terkunci, entri baru disisipkan tepat sesudah 'Morning Priority'. */
  CMO_MANAGER:{after:{'Morning Priority V2':'Morning Priority'}},
};

/* Label lama Layout.jsx yang menjadi acuan penyisipan. Dipakai tes untuk
   memastikan aturan urutan di atas hanya menyebut label yang benar-benar ada. */
export const LAYOUT_ANCHOR_LABELS={
  CHRO_MANAGER:['CHRO Home','Training','Recruitment'],
  HR_SUPPORT:['CHRO Home','Training','Recruitment'],
  CMO_MANAGER:['Morning Priority','Orders'],
};

export const ROLE_LIST=Object.keys(MENUS_BY_ROLE);

/* Menu yang SUDAH benar dibuat, tetapi belum bisa diklik karena `business.js`
   belum memberi hak aksesnya. Ini bukan bug menu — ini celah izin yang harus
   ditambal orkestrator (detail & usulan baris routeRoles ada di
   REQUESTS/sidebar.md). Dibiarkan sebagai baris menu supaya halamannya tetap
   punya jalan klik begitu izinnya dipasang, dan supaya celahnya tidak hilang
   dari laporan. Tes memverifikasi daftar ini PERSIS sama dengan kenyataan —
   kalau orkestrator memasang izinnya, tes gagal dan daftar ini harus dikosongkan. */
export const BLOCKED_BY_PERMISSION=[
  // (role, label, path, tambalan yang dibutuhkan di business.js)
  ['CMO_SUPPORT','Approval Sample (Lihat)','/cmo/sample-approval',"tambahkan 'CMO_SUPPORT' ke routeRoles['/cmo/sample-approval']"],
  ['SAMPLE_PIC','Sample Exception','/exceptions',"tambahkan 'SAMPLE_PIC' ke routeRoles['/exceptions']"],
  ['CHRO_MANAGER','Master Control','/master',"tambahkan groups.hr ke routeRoles['/master']"],
  ['HR_SUPPORT','Master Control — Lihat Saja','/master',"tambahkan groups.hr ke routeRoles['/master']"],
];

export function menusFor(role){
  const rows=MENUS_BY_ROLE[role];
  return rows?rows.map(row=>[...row]):[];
}

export function footerFor(role){
  const rows=FOOTER_BY_ROLE[role];
  return rows?rows.map(row=>[...row]):[];
}

/* Gabungkan daftar menu lama (Layout.jsx `roleMenus`) dengan entri baru.
   `existing` boleh berupa objek maupun fungsi () => objek.
   Sifat yang dijamin:
   - tidak pernah memutasi masukan;
   - tidak pernah menduplikasi label yang sudah ada di Layout.jsx
     ('Training', 'Master Control', 'Master Control — Lihat Saja', dsb.);
   - urutan label yang sudah ada di Layout.jsx TIDAK berubah kecuali pada posisi
     yang memang didaftarkan di ROLE_LAYOUT_ORDER (`replace`/`after`);
   - peran yang tidak didaftarkan cukup mendapat entri baru di belakang.

   PENTING soal `replace`: Label lama hanya digantikan kalau LAYOUT.jsx SUDAH
   memuat label lama itu. Kalau orkestrator sudah menghapus 'CHRO Home' dari
   sidebar HR, entri baru otomatis ditaruh di DEPAN supaya tidak ada halaman kerja
   yang jatuh ke bawah 'Master Control'. Ini mencegah dua kelas bug: (a) entri
   baru selalu menyisipkan diri sebelum/di posisi salah karena label acuan tidak
   ada, dan (b) halaman kerja baru terkubur di urutan terakhir. */
export function mergeMenus(existing,role){
  const base=typeof existing==='function'?(existing()||{}):(existing||{});
  const merged=(base[role]||[]).map(row=>[...row]);
  const seen=new Set(merged.map(row=>row[0]));
  const additions=menusFor(role).filter(row=>!seen.has(row[0]));
  if(!additions.length) return merged;

  const plan=ROLE_LAYOUT_ORDER[role];
  if(!plan) return merged.concat(additions);

  const replace=plan.replace||{};
  const after=plan.after||{};
  /* 1) Ganti label lama di posisinya (mis. 'CHRO Home' -> 'Employees'). */
  for(const [legacyLabel,newLabel] of Object.entries(replace)){
    const at=merged.findIndex(([label])=>label===legacyLabel);
    if(at<0) continue;   // label lama sudah tidak ada: entri baru ditaruh lewat `after`/langkah 3
    const row=additions.find(([label])=>label===newLabel);
    if(row) merged[at]=row;
  }
  /* 2) Sisipkan entri yang punya label acuan, tepat sesudah acuannya.
        Kalau acuannya tidak ada, entri ditaruh di depan supaya halaman kerja
        revisi selalu terlihat, bukan terkubur di bawah Master Control. */
  for(const [newLabel,anchorLabel] of Object.entries(after)){
    const row=additions.find(([label])=>label===newLabel);
    if(!row) continue;
    const at=merged.findIndex(([label])=>label===anchorLabel);
    merged.splice(at<0?0:at+1,0,row);
  }
  /* 3) Bangun ulang urutan secara deterministik.
        `front` menjadi urutan mutlak untuk label yang disebut (dipakai HR:
        halaman kerja harus di depan, tidak tenggelam di bawah 'Master Control');
        label lain tetap pada urutan relatif hasil langkah 1-2, dan entri baru
        yang masih tersisa ditaruh di belakang. */
  const front=plan.front||[];
  if(front.length){
    const head=front.map(label=>(merged.find(([l])=>l===label))||additions.find(([l])=>l===label)).filter(Boolean);
    const tail=merged.filter(row=>!head.includes(row));
    return head.concat(tail);
  }
  for(const row of additions){
    if(!merged.includes(row)) merged.push(row);
  }
  return merged;
}

/* Seluruh path yang ditunjuk menu sebuah peran (nav + footer). Dipakai tes untuk
   membandingkannya dengan daftar <Route> di main.jsx. */
export function menuPaths(role){
  return [...mergeMenus(undefined,role),...footerFor(role)].map(row=>row[1]);
}

export default {menusFor,footerFor,mergeMenus,menuPaths,MENUS_BY_ROLE,FOOTER_BY_ROLE,ROLE_LIST};
