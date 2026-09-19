import React,{useEffect,useState} from 'react';
import {Outlet,NavLink,useNavigate} from 'react-router-dom';
import {Home,Database,Package,ShoppingCart,DollarSign,Factory,Users,Crown,ClipboardList,AlertTriangle,LogOut,Menu,X,FileText,BarChart3,BookOpen,Truck,CheckSquare,MessageSquarePlus,Target,TrendingUp} from 'lucide-react';
import {api,clearToken} from '../api';
import {canAccess} from '../business';
import GlobalSearch from './GlobalSearch';

/* Sidebar menus.
   CMO_MANAGER follows the locked blueprint in revisi #14 poin 1 — order is
   fixed and must not be extended without change control. Deby's list follows
   revisi #9 poin 1. Neither list shows Delivery Execution, Order Closing,
   Payment Verification, Production, Inventory or QC as a CMO action. */
const roleMenus={
  /* Blueprint REF-CEO-IYAN: sidebar CEO hanya berisi tampilan keputusan dan
     kontrol. Workspace operasional (CFO Home, Shipment Gate, Deliveries, Order
     Closing, PO rutin) sengaja TIDAK ada — CEO melihatnya sebagai drill-down
     read-only, bukan sebagai menu kerja (revisi #74 & #77). */
  CEO:[['Morning CEO View','/ceo',Crown],['Company Performance','/ceo/company-performance',BarChart3],['Decision Needed','/ceo/decisions',ClipboardList],['CEO Action Tracker','/ceo/decisions',CheckSquare],['Exception Center','/exceptions',AlertTriangle],['Policy & Override','/ceo/business-policy',DollarSign],['Override Register','/ceo/overrides',AlertTriangle],['Master Control — Lihat Saja','/master',Database],['Audit Trail','/audit-log',ClipboardList],['Usulan Revisi','/revisions',MessageSquarePlus]],
  CMO_MANAGER:[['Morning Priority','/cmo/priority',Target],['Orders','/cmo/orders',ShoppingCart],['PPM','/cmo/samples',ClipboardList],['Sample Approval Feed','/cmo/sample-approval',ClipboardList],['SPK','/cmo/spk',CheckSquare],['Release to COO','/cmo/release-to-coo',CheckSquare],['Buyer CRM','/cmo/buyer-crm',Users],['Sales Pipeline','/cmo/sales-pipeline',TrendingUp],['Exception Center','/cmo/exception-center',AlertTriangle],['Reports','/cmo/reports',BarChart3],['Usulan Revisi','/revisions',MessageSquarePlus]],
  CMO_SUPPORT:[['Hari Ini','/cmo/today',Target],['PO Masuk','/cmo/po-inbox',ShoppingCart],['Buyer & Follow-up','/cmo/buyer-crm',Users],['Draft Order','/cmo/orders',ShoppingCart],['Quotation','/cmo/quotations',FileText],['Sample/PPM','/cmo/samples',ClipboardList],['SPK — Generate & Print','/cmo/spk',CheckSquare],['After Sales','/cmo/buyer-crm',Users],['Tugas Saya','/tasks',ClipboardList],['Master Control — Lihat Saja','/master',Database],['Usulan Revisi','/revisions',MessageSquarePlus]],
  CFO_MANAGER:[['CFO Home','/cfo',Home],['Invoices','/cfo/invoices',DollarSign],['Purchase Orders','/cfo/purchase-orders',Package],['Shipments Gate','/cfo/shipments',Truck],['Master Control','/master',Database],['Deliveries','/coo/deliveries',Truck],['Closing Keuangan','/coo/closing',CheckSquare]],
  FINANCE_SUPPORT:[['CFO Home','/cfo',Home],['Invoices','/cfo/invoices',DollarSign],['Master Control','/master',Database]],
  COO_MANAGER:[['COO Home','/coo',Home],['Material Requests','/coo/material-requests',Package],['Production Queue','/coo/production',Factory],['WIP Tracking','/coo/wip',Package],['QC Records','/coo/qc',CheckSquare],['Shipments & Serah Terima','/cfo/shipments',Truck],['Master Control','/master',Database],['Production Plan','/coo/planning',Factory],['Konfirmasi Customer (Lihat)','/coo/deliveries',Truck],['Closing Operasional','/coo/closing',CheckSquare]],
  SAMPLE_PIC:[['My Sample Tasks','/tasks',ClipboardList],['Samples','/cmo/samples',ClipboardList],['Master Control','/master',Database]],
  PRINTING_PIC:[['My Tasks','/tasks',ClipboardList],['Production Queue','/coo/production',Factory],['Master Control','/master',Database]],
  PRODUCTION_PIC:[['My Tasks','/tasks',ClipboardList],['Production Queue','/coo/production',Factory],['Material Requests','/coo/material-requests',Package],['Master Control','/master',Database]],
  CHRO_MANAGER:[['CHRO Home','/chro',Home],['Employees','/chro/employees',Users],['Training','/chro/training',BookOpen],['Performance','/chro/performance',BarChart3],['Employee Issues','/chro/issues',AlertTriangle]],
  HR_SUPPORT:[['CHRO Home','/chro',Home],['Employees','/chro/employees',Users],['Training','/chro/training',BookOpen]],
  SHIPMENT_ADMIN:[['Shipments','/cfo/shipments',Truck],['Master Control','/master',Database],['Deliveries','/coo/deliveries',Truck]]
};
roleMenus.CFO_MANAGER.splice(3,0,['Quotation Approval','/cmo/quotations',FileText]);
for(const role of ['CFO_MANAGER','COO_MANAGER','PRODUCTION_PIC']) roleMenus[role].push(['BOM & Actual Cost','/coo/bom-cost',Package]);

/* Footer links are role-scoped. Previously Panduan / Usulan Revisi / Task /
   Exception were rendered unconditionally, which leaked CMO Manager menus to
   every role — including CMO Support, who must only see "Lihat Saja"
   (revisi #9 poin 1 & 12, #14 poin 9). */
const footerLinks=role=>{
  const links=[['Panduan','/panduan',BookOpen]];
  if(role) links.push(['Usulan Revisi','/revisions',MessageSquarePlus]);
  if(role&&['CEO','CMO_MANAGER','CMO_SUPPORT','COO_MANAGER','PRODUCTION_PIC','PRINTING_PIC','SAMPLE_PIC'].includes(role)) links.push(['Task','/tasks',ClipboardList]);
  if(role&&['CEO','CMO_MANAGER','COO_MANAGER','CFO_MANAGER','CHRO_MANAGER'].includes(role)) links.push(['Exception','/exceptions',AlertTriangle]);
  return links.filter(([,path])=>canAccess(role,path));
};
const visibleMenus=role=>{
  const seen=new Set();
  return (roleMenus[role]||[['Master Control','/master',Database]])
    .filter(([,path])=>!role||canAccess(role,path))
    /* Two blueprint entries can point at the same page (PPM feed, Release to COO).
       Keep the first occurrence so the sidebar never shows a duplicate target. */
    .filter(([label,path])=>{const key=label+'|'+path;if(seen.has(key))return false;seen.add(key);return true;});
};

export default function Layout(){
 const [me,setMe]=useState(null),[open,setOpen]=useState(false); const nav=useNavigate();
 useEffect(()=>{api('/auth/me').then(setMe)},[]);
 useEffect(()=>{const main=document.querySelector('.main');if(main)main.scrollTo(0,0)},[]);
 const menus=visibleMenus(me?.role);
 const foot=footerLinks(me?.role);
 async function logout(){try{await api('/auth/logout',{method:'POST'})}catch{}finally{clearToken();nav('/login')}}
 return <div className="app-shell">
   <aside className={'sidebar '+(open?'open':'')}>
    <div className="brand"><b>BOS SYAMS</b><span>Business Operating System</span></div>
    <button className="close-mobile" onClick={()=>setOpen(false)}><X/></button>
    <div className="userbox"><div className="avatar">{me?.name?.[0]||'S'}</div><div><strong>{me?.name||'...'}</strong><small>{me?.role?.replaceAll('_',' ')}</small></div></div>
    <nav>{menus.map(([label,path,Icon],i)=><NavLink key={i} to={path} onClick={()=>setOpen(false)} className={({isActive})=>isActive?'active':''}><Icon size={18}/><span>{label}</span></NavLink>)}</nav>
    <div className="side-foot">{foot.map(([label,path,Icon],i)=><NavLink key={i} to={path} onClick={()=>setOpen(false)}><Icon size={18}/>{label}</NavLink>)}<button onClick={logout}><LogOut size={18}/>Keluar</button></div>
   </aside>
   <main className="main"><header className="topbar"><button className="menu-mobile" onClick={()=>setOpen(true)}><Menu/></button><GlobalSearch/><div className="top-user">{me?.name}</div></header><Outlet context={{me}}/></main>
 </div>}
