import React,{useCallback,useEffect,useMemo,useState} from 'react';
import {Link,useOutletContext} from 'react-router-dom';
import {api} from '../api';
import {rowTone,sortRows} from '../control';
import OrderPanel from './OrderPanel';

/* Morning Priority — rekap untuk meeting pagi (tab MORNING PRIORITY di sheet lama).
   Merah = URGENT, kuning = PERHATIAN, putih = on track. Pilih PIC untuk melihat kerjaannya saja;
   klik judul kolom untuk menyortir; klik baris untuk menandai selesai / melapor masalah. */

const COLUMNS=[['priority_sort','Status'],['pic','PIC'],['buyer','Buyer'],['garment','Jenis'],['article','Article'],['stage','Tahap'],['qty','Qty'],['problem','Masalah'],['next_action','Next action'],['order_id','Order ID'],['deadline','Deadline']];

export default function MorningPriority(){
  const role=useOutletContext()?.me?.role;
  const [data,setData]=useState(null),[pic,setPic]=useState('ALL'),[err,setErr]=useState('');
  const [sort,setSort]=useState({key:'priority_sort',dir:1}),[open,setOpen]=useState(null),[pics,setPics]=useState([]);
  const load=useCallback(()=>api('/control/morning-priority'+(pic!=='ALL'?'?pic='+encodeURIComponent(pic):'')).then(setData).catch(e=>setErr(e.message)),[pic]);
  useEffect(()=>{load()},[load]);
  useEffect(()=>{api('/control/pics?active_only=true').then(setPics).catch(()=>{})},[]);
  const rows=useMemo(()=>sortRows(data?.rows||[],sort.key,sort.dir),[data,sort]);
  const toggle=key=>setSort(s=>s.key===key?{key,dir:-s.dir}:{key,dir:1});
  const t=data?.totals||{urgent:0,attention:0,progress:0};
  const all=(data?.pics||[]).reduce((a,p)=>({orders:a.orders+p.orders,urgent:a.urgent+p.urgent,attention:a.attention+p.attention}),{orders:0,urgent:0,attention:0});

  return <div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    <div className="cards cards-3">
      <div className="stat red"><strong>{t.urgent}</strong><span>Urgent — butuh tindakan segera</span></div>
      <div className="stat amber"><strong>{t.attention}</strong><span>Perhatian — harus dikejar</span></div>
      <div className="stat gray"><strong>{t.progress}</strong><span>On track</span></div>
    </div>
    <div className="pic-chips" role="group" aria-label="Filter PIC">
      <button type="button" className={pic==='ALL'?'on':''} onClick={()=>setPic('ALL')}>Semua <b>{all.orders}</b>{all.urgent>0&&<i className="pill red">{all.urgent}</i>}{all.attention>0&&<i className="pill amber">{all.attention}</i>}</button>
      {(data?.pics||[]).map(p=><button type="button" key={p.pic} className={pic===p.pic?'on':''} onClick={()=>setPic(p.pic)}>{p.pic} <b>{p.orders}</b>{p.urgent>0&&<i className="pill red">{p.urgent}</i>}{p.attention>0&&<i className="pill amber">{p.attention}</i>}</button>)}
    </div>
    <section className="panel flush"><div className="table-scroll control-scroll"><table className="morning-table">
      <thead><tr>{COLUMNS.map(([key,label])=><th key={key}><button type="button" className="th-sort" onClick={()=>toggle(key)} aria-label={'Urutkan '+label}>{label}{sort.key===key?(sort.dir>0?' ▲':' ▼'):''}</button></th>)}</tr></thead>
      <tbody>{rows.map(r=><tr key={r.order_id} className={'mp-row '+rowTone(r.priority)} tabIndex={0} onClick={()=>setOpen(r.order_id)} onKeyDown={e=>{if(e.key==='Enter')setOpen(r.order_id)}}>
        <td><b>{r.priority}</b></td><td>{r.pic||'-'}</td><td>{r.buyer}</td><td>{r.garment_types.join(', ')||'-'}</td><td>{r.articles.join(', ')}</td>
        <td>{r.current_stage_label}</td><td>{r.active_qty}</td><td className="wrap">{r.problem||'-'}</td><td className="wrap">{r.next_action||'-'}</td>
        <td><Link to={'/orders/'+r.order_id} onClick={e=>e.stopPropagation()}>{r.order_id}</Link></td><td>{r.deadline||'-'}</td>
      </tr>)}
      {data&&!rows.length&&<tr><td colSpan={COLUMNS.length} className="empty-cell">{pic==='ALL'?'Tidak ada pekerjaan aktif. Semua order selesai atau belum ada order.':'Tidak ada pekerjaan aktif untuk '+pic+'.'}</td></tr>}
      </tbody></table></div></section>
    {open&&<OrderPanel orderId={open} role={role} pics={pics} onClose={()=>setOpen(null)} onChanged={load}/>}
  </div>;
}
