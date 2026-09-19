/* Komponen pemasang sidebar — Batch 2.

   `components/Layout.jsx` ada di daftar file terlarang AGENT-RULES.md §1, jadi
   Batch 2 tidak boleh mengeditnya. Berkas ini adalah lapisan tipis di atas
   `src/sidebarMenu.js` (kontrak data murni, diuji `node --test`) yang membuat
   pemasangan oleh orkestrator jadi satu impor:

     import {SidebarNav,SidebarFoot} from './SidebarMenu';
     ...
     <nav><SidebarNav menus={roleMenus} role={me?.role} onNavigate={()=>setOpen(false)}/></nav>
     <div className="side-foot"><SidebarFoot role={me?.role} onNavigate={()=>setOpen(false)}/><button onClick={logout}><LogOut size={18}/>Keluar</button></div>

   `SidebarNav`/`SidebarFoot` merender `<NavLink>` dengan markup & class yang sama
   persis seperti Layout.jsx sekarang, termasuk filter `canAccess`, jadi tidak ada
   perubahan tampilan. Kalau orkestrator lebih suka menempel langsung ke Layout,
   cukup pakai `mergeMenus`/`footerFor`/`resolveIcon` dari berkas ini dan biarkan
   `.map()` di Layout.jsx memetakan nama ikon ke komponen.
*/
import React from 'react';
import {NavLink} from 'react-router-dom';
import * as Lucide from 'lucide-react';
import {canAccess} from '../business';
import {mergeMenus,footerFor} from '../sidebarMenu.js';

/* Nama ikon -> komponen lucide-react. Fallback ke Database supaya salah tulis
   nama ikon tidak membuat sidebar gagal render (dulu satu entri rusak bisa
   menghapus seluruh daftar menu). */
export function resolveIcon(name){
  return Lucide[name]||Lucide.Database;
}

/* Menu nav satu peran: daftar lama Layout.jsx + entri baru, sudah difilter
   `canAccess` (penjaga menu yang sama dengan penjaga route) dan bebas duplikat
   tujuan. */
export function visibleRows(roleMenus,role){
  const seen=new Set();
  return mergeMenus(roleMenus,role)
    .filter(([,path])=>!role||canAccess(role,path))
    .filter(([label,path])=>{const key=label+'|'+path;if(seen.has(key))return false;seen.add(key);return true;});
}

export function SidebarNav({menus,role,onNavigate}){
  return <>{visibleRows(menus,role).map(([label,path,icon])=>{
    const Icon=resolveIcon(icon);
    return <NavLink key={label+'|'+path} to={path} onClick={onNavigate} className={({isActive})=>isActive?'active':''}><Icon size={18}/><span>{label}</span></NavLink>;
  })}</>;
}

export function SidebarFoot({role,onNavigate}){
  return <>{footerFor(role)
    .filter(([,path])=>!role||canAccess(role,path))
    .map(([label,path,icon])=>{const Icon=resolveIcon(icon);
      return <NavLink key={label+'|'+path} to={path} onClick={onNavigate}><Icon size={18}/>{label}</NavLink>;})}</>;
}

export default SidebarNav;
