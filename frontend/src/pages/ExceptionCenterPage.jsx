import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import {RefreshCw} from 'lucide-react';
import {isOverdue} from '../queue';

/* Revisi #14 poin 7 — EXCEPTION CENTER (komersial).
   Hanya exception komersial/customer yang perlu keputusan atau eskalasi Cecep,
   dengan severity, reason, owner, due, keputusan dan audit. Exception produksi,
   keuangan dan operasional tetap milik COO/CFO/CEO sesuai kewenangan. */

const COMMERCIAL=['sales','customer','quotation','order','delivery','buyer'];
const isCommercial=item=>COMMERCIAL.some(w=>String(item.category||'').toLowerCase().includes(w));

export default function ExceptionCenterPage(){
  const role=useRole();
  const canDecide=['CMO_MANAGER','CEO'].includes(role);
  const [list,setList]=useState([]),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [showAll,setShowAll]=useState(false);

  async function load(){setBusy(true);try{setList(await api('/exceptions'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  const open=list.filter(e=>['OPEN','IN_PROGRESS'].includes(e.status));
  const commercial=open.filter(isCommercial);
  const nonCommercial=open.filter(e=>!isCommercial(e));
  const shown=showAll?open:commercial;

  async function resolve(id){
    if(!confirm('Tandai exception ini selesai?'))return;
    setBusy(true);setErr('');
    try{await api('/exceptions/'+id,{method:'PATCH',body:JSON.stringify({status:'RESOLVED'})});await load()}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  return <div className="page">
    <div className="page-title">
      <div><h1>Exception Center</h1>
        <p>Exception komersial yang butuh keputusan Cecep. Produksi, keuangan dan operasional tetap milik COO/CFO/CEO.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards">
      <div className={'stat '+(commercial.some(e=>e.severity==='RED')?'red':commercial.length?'amber':'green')}>
        <strong>{commercial.length}</strong><span>Exception komersial terbuka</span></div>
      <div className="stat blue"><strong>{commercial.filter(e=>e.severity==='RED').length}</strong><span>Severity RED</span></div>
      <div className="stat gray"><strong>{nonCommercial.length}</strong><span>Di luar kewenangan CMO</span></div>
    </div>

    <div className="filter-bar">
      <button className={'pill '+(showAll?'':'active open')} onClick={()=>setShowAll(false)}>Komersial ({commercial.length})</button>
      <button className={'pill '+(showAll?'active in_progress':'')} onClick={()=>setShowAll(true)}>Semua Terbuka ({open.length})</button>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>Severity</th><th>Kategori</th><th>Masalah</th><th>Order</th><th>Owner</th>
      <th>Due</th><th>Next Action</th><th>Status</th><th>Dibuat</th><th>Aksi</th>
    </tr></thead><tbody>
      {shown.map(item=>{
        const commercialRow=isCommercial(item);
        return <tr key={item.id}>
          <td><span className={'badge '+(item.severity==='RED'?'red':'amber')}>{item.severity}</span></td>
          <td><span className={'badge '+(commercialRow?'blue':'gray')}>{item.category}</span>
            {!commercialRow&&<small><br/>COO/CFO</small>}</td>
          <td>{item.title}</td>
          <td>{item.order_fk?<Link to={'/orders/'+item.order_fk}>{item.order_fk}</Link>:'—'}</td>
          <td><span className="badge gray">{item.owner_name||item.owner_role||'—'}</span></td>
          <td>{item.due_date?(isOverdue(item.due_date)?<span className="badge red">{item.due_date} · lewat</span>:item.due_date):'—'}</td>
          <td>{item.next_action||'—'}</td>
          <td><span className={'badge '+(item.status==='OPEN'?'red':'amber')}>{item.status}</span></td>
          <td><small>{item.created_at?new Date(item.created_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
          <td className="td-action">
            {canDecide&&commercialRow&&item.status!=='RESOLVED'&&<button className="btn sm" disabled={busy} onClick={()=>resolve(item.id)}>Selesaikan</button>}
            {!commercialRow&&<span className="badge gray">Eskalasi</span>}
          </td>
        </tr>;
      })}
      {!shown.length&&<tr><td colSpan={10} className="empty">
        {showAll?'Tidak ada exception terbuka.':'Tidak ada exception komersial terbuka.'}
      </td></tr>}
    </tbody></table></div>
  </div>;
}