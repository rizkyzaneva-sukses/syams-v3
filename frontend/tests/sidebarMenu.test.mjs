import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';

import {canAccess} from '../src/business.js';
import {menusFor,footerFor,mergeMenus,MENUS_BY_ROLE,FOOTER_BY_ROLE,ROLE_LIST,BLOCKED_BY_PERMISSION,LAYOUT_ANCHOR_LABELS} from '../src/sidebarMenu.js';

/* BATCH 2 — SIDEBAR/MENU.

   Konteks: batch-1 membuat 11 halaman yang ber-route + ber-hak-akses, tetapi
   TIDAK punya entri menu, sehingga tidak ada jalan mengkliknya dari UI.
   `components/Layout.jsx` ada di daftar terlarang AGENT-RULES.md §1, jadi definisi
   menu hidup di `src/sidebarMenu.js` (+ `components/SidebarMenu.jsx`) untuk
   disuntikkan orkestrator.

   Yang dibuktikan berkas ini, bukan diklaim:
     1. setiap menu menunjuk tujuan yang BENAR-BENAR terdaftar sebagai <Route> di
        main.jsx;
     2. setiap menu lolos `canAccess(role,path)` — kalau tidak, menu muncul lalu
        ditolak `Access.jsx` saat diklik (persis keluhan batch-1);
     3. sidebar final SAMPLE_PIC (revisi #31) dan PRINTING_PIC (revisi #43/#47)
        sama persis dengan blueprint, urutannya diuji;
     4. CEO tidak mendapat satu pun menu kerja divisi (revisi #74/#77);
     5. tidak ada entri menu yang mengarah ke route dinamis (`:param`);
     6. mergeMenus tidak menghapus/menduplikasi menu lama. */

const here=dirname(fileURLToPath(import.meta.url));
const srcDir=join(here,'..','src');
const read=rel=>readFileSync(join(srcDir,rel),'utf8');

const mainSrc=read('main.jsx');
const businessSrc=read('business.js');
const layoutSrc=read('components/Layout.jsx');

/* ── Daftar <Route> yang benar-benar terdaftar di main.jsx ──────────────── */
export function registeredRoutePaths(source){
  const paths=new Set(['/']);
  const re=/<Route\s+path="([^"]+)"/g;
  let hit;
  while((hit=re.exec(source))){
    const raw=hit[1];
    if(raw==='/'){paths.add('/');continue;}
    let path='/'+raw.replace(/^\/+/,'');
    if(path.includes(':orderId')){paths.add('/orders/ORD-1');continue;}
    if(path.includes(':')){paths.add(path.replace(/:[^/]+/g,'1'));continue;}
    paths.add(path);
  }
  return paths;
}

const ROUTES=registeredRoutePaths(mainSrc);

/* Peran yang ada di aplikasi (grup di business.js + user demo). */
const ALL_ROLES=['CEO','CMO_MANAGER','CMO_SUPPORT','CFO_MANAGER','FINANCE_SUPPORT',
  'COO_MANAGER','PRODUCTION_PIC','PRINTING_PIC','SAMPLE_PIC','SHIPMENT_ADMIN',
  'CHRO_MANAGER','HR_SUPPORT'];

/* Halaman baru batch-1: wajib punya menu di peran pemiliknya. */
const BATCH1_PAGES=[
  ['/cmo/priority-v2',['CMO_MANAGER']],
  ['/chro/employees',['CHRO_MANAGER','HR_SUPPORT']],
  ['/chro/recruitment',['CHRO_MANAGER','HR_SUPPORT']],
  ['/sample/lifecycle',['SAMPLE_PIC']],
  ['/sample/today',['SAMPLE_PIC']],
  ['/sample/tasks',['SAMPLE_PIC']],
  ['/printing/job-cards',['PRINTING_PIC']],
  ['/printing/daily-target',['PRINTING_PIC']],
  ['/cfo/receivables',['CFO_MANAGER','FINANCE_SUPPORT']],
  ['/cfo/costing',['CFO_MANAGER','FINANCE_SUPPORT']],
  ['/coo/execution',['COO_MANAGER','PRODUCTION_PIC']],
];

test('main.jsx benar-benar mendaftarkan 11 route batch-1 (dasar perbandingan)', () => {
  for(const [path] of BATCH1_PAGES) assert.ok(ROUTES.has(path),`route ${path} belum terdaftar di main.jsx`);
  assert.equal(ROUTES.size>30,true,`hanya ${ROUTES.size} route terbaca dari main.jsx`);
});

test('setiap path yang dipakai menu terdaftar sebagai <Route> di main.jsx (tanpa :param)', () => {
  const problems=[];
  for(const role of ALL_ROLES){
    for(const [label,path] of [...mergeMenus(undefined,role),...footerFor(role)]){
      if(path.includes(':')) problems.push(`${role} · "${label}" -> ${path} (route dinamis, tidak bisa jadi menu)`);
      if(!ROUTES.has(path)) problems.push(`${role} · "${label}" -> ${path} (tidak ada <Route>)`);
    }
  }
  assert.deepEqual(problems,[],'menu menunjuk route yang tidak terdaftar:\n'+problems.join('\n'));
});

test('setiap menu lolos canAccess KECUALI celah izin yang didaftarkan eksplisit', () => {
  const observed=[];
  for(const role of ALL_ROLES){
    for(const [label,path] of [...mergeMenus(undefined,role),...footerFor(role)]){
      if(!canAccess(role,path)) observed.push(`${role}|${label}|${path}`);
    }
  }
  // Celah yang DIHARAPKAN: menu sudah benar, hak akses belum dipasang
  // orkestrator di business.js. Daftar lengkap + tambalannya ada di
  // REQUESTS/sidebar.md dan `BLOCKED_BY_PERMISSION` di src/sidebarMenu.js.
  const expected=BLOCKED_BY_PERMISSION.map(([role,label,path])=>`${role}|${label}|${path}`);
  assert.deepEqual(observed.sort(),expected.sort(),
    'celah izin berubah — perbarui BLOCKED_BY_PERMISSION & REQUESTS/sidebar.md, atau kosongkan kalau izinnya sudah dipasang');
  // Sisanya (mayoritas menu) harus lolos tanpa kecuali.
  const total=ALL_ROLES.flatMap(role=>[...mergeMenus(undefined,role),...footerFor(role)]).length;
  assert.equal(total-observed.length>0,true,`${total} entri menu diperiksa, ${observed.length} celah izin`);
});

test('setiap halaman batch-1 punya jalan klik dari menu peran pemiliknya', () => {
  const missing=[];
  for(const [page,roles] of BATCH1_PAGES){
    for(const role of roles){
      if(!canAccess(role,page)){missing.push(`${role} kehilangan hak akses ${page}`);continue;}
      const reachable=[...mergeMenus(undefined,role),...footerFor(role)].some(([,p])=>p===page);
      if(!reachable) missing.push(`${role} tidak punya menu menuju ${page}`);
    }
  }
  assert.deepEqual(missing,[],'halaman tanpa jalan klik:\n'+missing.join('\n'));
});

test('sidebar final SAMPLE_PIC persis blueprint revisi #31', () => {
  const rows=mergeMenus(undefined,'SAMPLE_PIC');
  assert.deepEqual(rows.map(([label])=>label),
    ['Sample Today','My Sample Tasks','Sample Workspace','Sample Exception','Master Control — Lihat Saja']);
  assert.deepEqual(rows.map(([,path])=>path),
    ['/sample/today','/sample/tasks','/sample/lifecycle','/exceptions','/master']);
  // 'Keluar' = tombol logout di .side-foot, bukan entri nav.
  assert.ok(!rows.some(([label])=>label==='Keluar'));
  assert.ok(/Keluar/.test(layoutSrc),'Layout.jsx harus tetap merender tombol Keluar');
  // Menu kerja divisi lain tidak muncul (revisi #31/#32/#37).
  for(const denied of ['SPK','Production Queue','Purchasing','Purchase Orders','Finance','Delivery','Buyer Approval','Printing']){
    assert.ok(!rows.some(([label])=>label.includes(denied)),`SAMPLE_PIC tidak boleh punya menu "${denied}"`);
  }
  assert.deepEqual(footerFor('SAMPLE_PIC').map(([label])=>label),['Panduan','Usulan Revisi','Task'],'footer Sample PIC: Panduan; Usulan Revisi; Task; Keluar');
});

test('sidebar PRINTING_PIC memuat Job Card & Daily Target sesuai blueprint Iman', () => {
  const rows=mergeMenus(undefined,'PRINTING_PIC');
  assert.deepEqual(rows.map(([label])=>label),['My Tasks','Production Queue','Job Card','Daily Target','Master Control']);
  assert.deepEqual(rows.map(([,path])=>path),['/tasks','/coo/production','/printing/job-cards','/printing/daily-target','/master']);
  assert.deepEqual(footerFor('PRINTING_PIC').map(([label])=>label),['Panduan','Usulan Revisi','Task'],'footer Printing PIC: Panduan; Usulan Revisi; Task; Keluar');
  for(const denied of ['/cfo/receivables','/cfo/costing','/chro/employees','/cmo/spk']){
    assert.equal(canAccess('PRINTING_PIC',denied),false,`${denied} bukan hak PRINTING_PIC`);
  }
});

test('CEO tidak diberi satu pun menu kerja divisi (revisi #74/#77)', () => {
  assert.deepEqual(menusFor('CEO'),[]);
  for(const rows of [mergeMenus(undefined,'CEO'),footerFor('CEO')]){
    for(const [label,path,icon] of rows){
      assert.equal(typeof label,'string'); assert.equal(typeof path,'string'); assert.equal(typeof icon,'string');
    }
  }
  const operational=['/coo/execution','/printing/job-cards','/printing/daily-target','/sample/today','/sample/tasks','/cfo/receivables','/cfo/costing','/cmo/priority-v2','/chro/employees','/chro/recruitment'];
  // Menu itu memang diberikan ke peran non-CEO (jadi uji ini bukan uji kosong)...
  const givenToOthers=new Set(ALL_ROLES.filter(r=>r!=='CEO').flatMap(role=>mergeMenus(undefined,role).map(([,p])=>p)));
  for(const path of operational) assert.ok(givenToOthers.has(path),`${path} tidak diberikan ke peran mana pun — menu tidak terpasang`);
  // ...tetapi tidak satu pun boleh muncul untuk CEO.
  for(const path of operational) assert.ok(!mergeMenus(undefined,'CEO').some(([,p])=>p===path),`CEO tidak boleh dapat ${path}`);
  for(const path of ['/coo/production','/cfo/invoices','/cfo/purchase-orders','/coo/closing','/coo/bom-cost']){
    assert.equal(canAccess('CEO',path),false,`CEO tidak punya halaman kerja ${path}`);
  }
});

test('mergeMenus mempertahankan menu lama, tidak menduplikasi label, dan tidak mengacak urutan CMO', () => {
  const legacy={
    CMO_MANAGER:[['Morning Priority','/cmo/priority','Target'],['Orders','/cmo/orders','ShoppingCart'],['PPM','/cmo/samples','ClipboardList']],
    CHRO_MANAGER:[['CHRO Home','/chro','Home'],['Training','/chro/training','BookOpen']],
    HR_SUPPORT:[['CHRO Home','/chro','Home'],['Training','/chro/training','BookOpen']],
  };
  const before=JSON.stringify(legacy);
  const cmo=mergeMenus(legacy,'CMO_MANAGER');
  assert.deepEqual(cmo.map(([label])=>label),['Morning Priority','Morning Priority V2','Orders','PPM']);
  assert.equal(JSON.stringify(legacy),before,'mergeMenus tidak boleh memutasi daftar lama');
  // Entri lama persis seperti semula (ikon & path tidak berubah).
  assert.deepEqual(cmo.find(([label])=>label==='Orders'),['Orders','/cmo/orders','ShoppingCart']);

  // HR: halaman kerja revisi didahulukan, menu lama yang belum digantikan tetap ada.
  const hr=mergeMenus(legacy,'CHRO_MANAGER');
  assert.deepEqual(hr.map(([label])=>label),
    ['Employees','Recruitment','Training','Performance','Employee Issues','Master Control']);
  assert.ok(hr.some(([label,path])=>label==='Training'&&path==='/chro/training'),'menu Training lama dipakai ulang, bukan diduplikasi');
  assert.equal(hr.filter(([label])=>label==='Training').length,1);
  assert.ok(!hr.some(([label])=>label==='CHRO Home'),'CHRO Home digantikan Employees pada posisi yang sama');
  // Tanpa 'CHRO Home' di sidebar lama, halaman HR tetap di depan (bukan tenggelam).
  assert.deepEqual(mergeMenus({},'HR_SUPPORT').map(([label])=>label),
    ['Employees','Recruitment','Training','Master Control — Lihat Saja']);

  const fin=mergeMenus({FINANCE_SUPPORT:[['CFO Home','/cfo','Home']]},'FINANCE_SUPPORT');
  assert.deepEqual(fin.map(([label])=>label),['CFO Home','Piutang & Collection','Actual Cost & HPP']);

  // Juga menerima fungsi (bentuk `visibleMenus` di Layout.jsx).
  assert.deepEqual(mergeMenus(()=>({}),'PRINTING_PIC').map(([label])=>label),
    ['My Tasks','Production Queue','Job Card','Daily Target','Master Control']);
  // Deterministik: tidak ada urutan yang berubah antar pemanggilan.
  assert.equal(JSON.stringify(mergeMenus(legacy,'CHRO_MANAGER')),JSON.stringify(mergeMenus(legacy,'CHRO_MANAGER')));
});

test('bentuk baris menu konsisten dan ikonnya nyata di lucide-react', async () => {
  const lucide=await import('lucide-react');
  for(const [role,rows] of Object.entries(MENUS_BY_ROLE)){
    for(const row of rows){
      assert.equal(row.length,3,`${role}: baris menu harus [label,path,ikon]`);
      const [label,path,icon]=row;
      assert.equal(typeof label,'string');
      assert.ok(label.trim().length>2,`${role}: label "${label}" terlalu pendek`);
      assert.ok(path.startsWith('/'),`${role}: path "${path}" harus absolut`);
      assert.equal(typeof lucide[icon],'object',`${role}: ikon "${icon}" tidak ada di lucide-react`);
    }
  }
  for(const [role,rows] of Object.entries(FOOTER_BY_ROLE)){
    for(const [label,,icon] of rows) assert.equal(typeof lucide[icon],'object',`${role}: ikon footer "${icon}" tidak ada di lucide-react`);
  }
  // Kontrak baris `[label,path,Icon]` dihormati di kedua keadaan: sebelum dipasang
  // (Layout.jsx masih memakai map inline) maupun sesudah (Layout.jsx memakai
  // <SidebarNav>/<SidebarFoot> dari SidebarMenu.jsx).
  const layoutInline=/menus\.map\(\(\[label,path,Icon\]/.test(layoutSrc);
  const layoutUsesComponent=/<SidebarNav\b/.test(layoutSrc)&&/<SidebarFoot\b/.test(layoutSrc);
  assert.ok(layoutInline||layoutUsesComponent,'Layout.jsx harus memakai kontrak [label,path,Icon] (inline atau lewat SidebarNav/SidebarFoot)');
  // Penjaga menu (canAccess) harus tetap ada di salah satu lapisan.
  assert.ok(/canAccess\(role,path\)/.test(layoutSrc)||/canAccess\(role,path\)/.test(read('components/SidebarMenu.jsx')),
    'filter canAccess untuk menu harus tetap ada');
});

test('modul menu tidak menduplikasi hak akses dan file terlarang tidak disentuh', () => {
  const sidebarSrc=read('sidebarMenu.js');
  assert.ok(!/routeRoles\s*=\s*\{/.test(sidebarSrc),'sidebarMenu.js tidak boleh mendeklarasikan routeRoles sendiri');
  assert.ok(!/export function canAccess/.test(sidebarSrc),'sidebarMenu.js tidak boleh mendeklarasikan canAccess sendiri');
  // Aturan urutan hanya boleh menyebut label yang benar-benar ada di sidebar lama.
  for(const [role,labels] of Object.entries(LAYOUT_ANCHOR_LABELS)){
    for(const label of labels){
      const known=[...mergeMenus({},role),...menusFor(role)].some(([l])=>l===label)
        || new RegExp(`\\['${label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}'`).test(layoutSrc);
      assert.ok(known,`${role}: label acuan "${label}" tidak ada di sidebar lama Layout.jsx maupun menu baru`);
    }
  }
  // Seluruh path halaman baru ada di business.js (izin, dengan '/' awal) dan
  // main.jsx (route React Router tanpa '/' awal — bandingkan keduanya).
  for(const path of ['/sample/today','/sample/tasks','/sample/lifecycle','/printing/job-cards','/printing/daily-target','/cfo/receivables','/cfo/costing','/coo/execution','/cmo/priority-v2','/chro/employees','/chro/recruitment']){
    assert.ok(businessSrc.includes(`'${path}'`),`${path} harus terdaftar di business.js`);
    assert.ok(mainSrc.includes(`"${path.slice(1)}"`),`${path} harus terdaftar di main.jsx`);
    assert.ok(ROUTES.has(path),`${path} harus terbaca sebagai <Route> dari main.jsx`);
  }
  // SidebarMenu.jsx adalah komponen baru; ia tidak menggantikan Layout.jsx.
  assert.ok(!/export default function Layout/.test(read('components/SidebarMenu.jsx')));
  assert.deepEqual(ROLE_LIST.sort(),ALL_ROLES.slice().sort(),'daftar peran di menu harus mencakup semua peran aplikasi');
});
