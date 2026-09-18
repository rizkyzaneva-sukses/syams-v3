import React,{useEffect,useState} from 'react';
import {Outlet,NavLink,useNavigate} from 'react-router-dom';
import {Home,Database,Package,ShoppingCart,DollarSign,Factory,Users,Crown,ClipboardList,AlertTriangle,LogOut,Menu,X,FileText,BarChart3,BookOpen,Truck,CheckSquare,MessageSquarePlus} from 'lucide-react';
import {api,clearToken} from '../api';
import {canAccess} from '../business';
import GlobalSearch from './GlobalSearch';

const roleMenus={
  CEO:[['CEO Home','/ceo',Crown],['Master Control','/master',Database],['Decisions','/ceo/decisions',ClipboardList],['Exceptions','/exceptions',AlertTriangle],['Audit Log','/audit-log',ClipboardList],['CFO Home','/cfo',DollarSign],['Shipment Gate','/cfo/shipments',Truck],['Deliveries','/coo/deliveries',Truck],['Order Closing','/coo/closing',CheckSquare]],
  CMO_MANAGER:[['CMO Home','/cmo',Home],['PO Inbox & Review','/cmo/po-inbox',ShoppingCart],['Order Management','/cmo/orders',ShoppingCart],['Customer / Buyer','/cmo/customers',Users],['Quotations','/cmo/quotations',FileText],['Sample / PPM','/cmo/samples',ClipboardList],['SPK','/cmo/spk',CheckSquare],['Master Control','/master',Database],['Shipment (Lihat)','/cfo/shipments',Truck],['Konfirmasi Customer','/coo/deliveries',Truck],['Closing Customer','/coo/closing',CheckSquare]],
  CMO_SUPPORT:[['CMO Home','/cmo',Home],['PO Inbox','/cmo/po-inbox',ShoppingCart],['Order Management','/cmo/orders',ShoppingCart],['Customer / Buyer','/cmo/customers',Users],['Quotations','/cmo/quotations',FileText],['Sample / PPM','/cmo/samples',ClipboardList],['SPK','/cmo/spk',CheckSquare],['Master Control','/master',Database]],
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
roleMenus.CEO.splice(3,0,['Pricing Policy','/ceo/business-policy',DollarSign],['Quotation Limit','/cmo/quotations',FileText]);
for(const role of ['CEO','CFO_MANAGER','COO_MANAGER','PRODUCTION_PIC']) roleMenus[role].push(['BOM & Actual Cost','/coo/bom-cost',Package]);

export default function Layout(){
 const [me,setMe]=useState(null),[open,setOpen]=useState(false); const nav=useNavigate();
 useEffect(()=>{api('/auth/me').then(setMe)},[]);
 const menus=(roleMenus[me?.role]||[['Master Control','/master',Database]]).filter(([,path])=>!me?.role||canAccess(me.role,path));
 async function logout(){try{await api('/auth/logout',{method:'POST'})}catch{}finally{clearToken();nav('/login')}}
 return <div className="app-shell">
   <aside className={'sidebar '+(open?'open':'')}>
    <div className="brand"><b>BOS SYAMS</b><span>Business Operating System</span></div>
    <button className="close-mobile" onClick={()=>setOpen(false)}><X/></button>
    <div className="userbox"><div className="avatar">{me?.name?.[0]||'S'}</div><div><strong>{me?.name||'...'}</strong><small>{me?.role?.replaceAll('_',' ')}</small></div></div>
    <nav>{menus.map(([label,path,Icon],i)=><NavLink key={i} to={path} onClick={()=>setOpen(false)} className={({isActive})=>isActive?'active':''}><Icon size={18}/><span>{label}</span></NavLink>)}</nav>
    <div className="side-foot"><NavLink to="/panduan" onClick={()=>setOpen(false)}><BookOpen size={18}/>Panduan</NavLink><NavLink to="/revisions" onClick={()=>setOpen(false)}><MessageSquarePlus size={18}/>Usulan Revisi</NavLink><NavLink to="/tasks"><ClipboardList size={18}/>Task</NavLink><NavLink to="/exceptions"><AlertTriangle size={18}/>Exception</NavLink><button onClick={logout}><LogOut size={18}/>Keluar</button></div>
   </aside>
   <main className="main"><header className="topbar"><button className="menu-mobile" onClick={()=>setOpen(true)}><Menu/></button><GlobalSearch/><div className="top-user">{me?.name}</div></header><Outlet context={{me}}/></main>
 </div>}
