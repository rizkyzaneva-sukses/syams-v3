/* BUKTI RUNTIME — Batch 2 SIDEBAR (bukan sekadar perbandingan string).

   Skrip ini menyusun aplikasi React nyata dengan router yang SAMA dengan
   `main.jsx` + sidebar yang SAMA dengan yang dipasang di `Layout.jsx`
   (`SidebarMenu.jsx` -> `src/sidebarMenu.js`), lalu merender sidebar untuk tiap
   peran memakai `react-dom/server`. Jadi yang dibuktikan adalah perilaku
   render sebenarnya: menu apa yang muncul, dan apakah `canAccess` (penjaga yang
   dipakai `Access.jsx` untuk route) mengizinkan tujuannya.

   Dijalankan dengan vite (?ssr) supaya .jsx bisa dimuat:
     npx vite-node? — tidak tersedia; pakai `vite build --ssr` (lihat run-proof.sh).
*/
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import {canAccess} from '../src/business.js';
import {mergeMenus,footerFor} from '../src/sidebarMenu.js';
import {SidebarNav,SidebarFoot} from '../src/components/SidebarMenu.jsx';
import * as React from 'react';
import fs from 'node:fs';

const ALL_ROLES=['CEO','CMO_MANAGER','CMO_SUPPORT','CFO_MANAGER','FINANCE_SUPPORT',
  'COO_MANAGER','PRODUCTION_PIC','PRINTING_PIC','SAMPLE_PIC','SHIPMENT_ADMIN',
  'CHRO_MANAGER','HR_SUPPORT'];

/* main.jsx memakai <Route path="sample/today"> (tanpa '/' awal). Ambil daftar itu
   dari sumber yang sama supaya bukti ini tidak bisa "lulus" karena salah baca. */
function registeredRoutes(){
  /* Dijalankan lewat `node proof/dist/sidebar-proof.js` dari root frontend, jadi
     cwd selalu root frontend. Dibaca dari berkas sumber, bukan dari bundel, supaya
     daftar <Route>-nya identik dengan yang dipakai aplikasi. */
  const src=fs.readFileSync('src/main.jsx','utf8');
  const set=new Set(['/']);
  for(const m of src.matchAll(/<Route\s+path="([^"]+)"/g)){
    const p=m[1];
    if(p==='/'){continue;}
    set.add('/'+p.replace(/^\/+/,'').replace(/:[^/]+/g,'1'));
  }
  return set;
}

const ROUTES=registeredRoutes();
const failures=[];
const rowsOut=[];

for(const role of ALL_ROLES){
  const menus=mergeMenus(undefined,role);
  let navHtml='',footHtml='';
  try{
    navHtml=renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/']},
      React.createElement(SidebarNav,{menus:undefined,role,onNavigate:undefined})));
    footHtml=renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/']},
      React.createElement(SidebarFoot,{role,onNavigate:undefined})));
  }catch(err){
    failures.push(`${role}: RENDER GAGAL — ${err.message}`);
    continue;
  }
  // Href yang benar-benar keluar dari render (bukan dari daftar saya).
  const hrefs=[...navHtml.matchAll(/href="([^"]+)"/g)].map(m=>m[1]);
  const footHrefs=[...footHtml.matchAll(/href="([^"]+)"/g)].map(m=>m[1]);
  rowsOut.push({role,menus:menus.map(([l])=>l),renderedNav:hrefs,renderedFoot:footHrefs});
  for(const href of [...hrefs,...footHrefs]){
    if(!ROUTES.has(href)) failures.push(`${role}: menu merender href ${href} yang TIDAK ada <Route>-nya`);
    if(!canAccess(role,href)) failures.push(`${role}: href ${href} dirender tapi canAccess=false (akan ditolak Access.jsx)`);
  }
  if(role!=='CEO'&&hrefs.length===0&&!['SHIPMENT_ADMIN'].includes(role)) failures.push(`${role}: sidebar kosong`);
}

/* Halaman batch-1 harus muncul sebagai href nyata di render peran pemiliknya. */
const BATCH1={SAMPLE_PIC:['/sample/today','/sample/tasks','/sample/lifecycle'],
  PRINTING_PIC:['/printing/job-cards','/printing/daily-target'],
  CFO_MANAGER:['/cfo/receivables','/cfo/costing'],
  FINANCE_SUPPORT:['/cfo/receivables','/cfo/costing'],
  COO_MANAGER:['/coo/execution'],PRODUCTION_PIC:['/coo/execution'],
  CMO_MANAGER:['/cmo/priority-v2'],
  CHRO_MANAGER:['/chro/employees','/chro/recruitment'],
  HR_SUPPORT:['/chro/employees','/chro/recruitment']};
for(const [role,paths] of Object.entries(BATCH1)){
  const row=rowsOut.find(r=>r.role===role);
  for(const p of paths) if(!row.renderedNav.includes(p)) failures.push(`${role}: halaman ${p} TIDAK dirender sebagai menu`);
}
/* CEO tidak boleh mendapat menu kerja divisi. */
const ceo=rowsOut.find(r=>r.role==='CEO');
for(const p of Object.values(BATCH1).flat()) if(ceo.renderedNav.includes(p)) failures.push(`CEO: tidak boleh punya menu ${p}`);

console.log('=== MENU YANG BENAR-BENAR DIRENDER (dari HTML) ===');
for(const r of rowsOut) console.log(r.role.padEnd(17),'nav:',(r.renderedNav.join(' ')||'(kosong, pakai sidebar lama)'));
console.log('');
console.log('=== HASIL ===');
console.log('peran diperiksa :',ALL_ROLES.length);
console.log('route terdaftar :',ROUTES.size);
console.log('kegagalan       :',failures.length);
for(const f of failures) console.log('  GAGAL:',f);
if(failures.length){process.exitCode=1;console.log('\nBUKTI GAGAL');}
else console.log('\nBUKTI LULUS: setiap menu yang dirender menunjuk route terdaftar dan lolos canAccess.');
