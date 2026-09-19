import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';
import {RefreshCw,Check} from 'lucide-react';

/* Revisi #14 poin 5 — RELEASE TO COO.
   Handoff CMO → COO. Print bukan Release, dan CMO SPK Release bukan Batch
   Release milik Siti/COO. Halaman ini hanya menangani handoff; Generate,
   Preview dan Print tetap di /cmo/spk. */

export default function ReleaseToCOOPage(){
  const role=useRole();
  const manager=role==='CMO_MANAGER';
  const [list,setList]=useState([]),[orders,setOrders]=useState([]);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [showReleased,setShowReleased]=useState(false);
  const [target,setTarget]=useState(null),[readiness,setReadiness]=useState(null);
  const [reason,setReason]=useState(''),[correction,setCorrection]=useState('');

  async function load(){
    setBusy(true);
    try{const [s,o]=await Promise.all([api('/cmo/spk'),api('/orders')]);setList(s);setOrders(o);setErr('')}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  const orderOf=id=>orders.find(o=>o.id===id);
  /* Siap handoff = sudah PRINTED (prasyarat Release), belum RELEASED. */
  const ready=list.filter(k=>k.status==='PRINTED');
  const released=list.filter(k=>k.status==='RELEASED');
  const shown=showReleased?released:ready;

  async function openRelease(spk){
    setTarget(spk);setReadiness(null);setReason('');setCorrection('');setErr('');
    try{setReadiness(await api(`/cmo/spk/${spk.id}/release-readiness`))}
    catch(e){setErr(e.message);setTarget(null)}
  }

  async function submit(e){
    e.preventDefault();if(!target)return;
    setBusy(true);setErr('');
    try{
      await api(`/cmo/spk/${target.id}/release`,{method:'POST',body:JSON.stringify({
        version_id:target.id,reason:reason.trim(),correction_reason:correction.trim()||null})});
      setTarget(null);setReadiness(null);await load();
    }catch(e){
      setErr(e.message);
      try{setReadiness(await api(`/cmo/spk/${target.id}/release-readiness`))}catch{}
    }finally{setBusy(false)}
  }

  return <div className="page">
    <div className="page-title">
      <div><h1>Release to COO</h1>
        <p>Handoff SPK dari CMO ke COO. Print bukan Release; pelepasan batch tetap milik Siti/COO.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    {err&&!target&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards">
      <div className={'stat '+(ready.length?'amber':'green')}><strong>{ready.length}</strong><span>Siap Release to COO</span></div>
      <div className="stat blue"><strong>{released.length}</strong><span>Sudah di-release</span></div>
    </div>

    <div className="notice info">
      Generate, Preview dan Print SPK dikelola di <Link to="/cmo/spk">SPK — Generate &amp; Print</Link>.
      Halaman ini hanya mencatat handoff ke COO beserta aktor, timestamp, versi dan alasannya.
    </div>

    <div className="filter-bar">
      <button className={'pill '+(showReleased?'':'active in_progress')} onClick={()=>setShowReleased(false)}>Siap Release ({ready.length})</button>
      <button className={'pill '+(showReleased?'active done':'')} onClick={()=>setShowReleased(true)}>Sudah Release ({released.length})</button>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>SPK</th><th>Versi</th><th>Order</th><th>Status</th><th>Commercial Gate</th>
      <th>Sample/PPM Gate</th><th>Released By / At</th><th>Release Reason</th><th>Batch Release COO</th><th>Aksi</th>
    </tr></thead><tbody>
      {shown.map(k=>{
        const order=orderOf(k.order_fk);
        return <tr key={k.id}>
          <td><b>{k.spk_no}</b></td>
          <td>v{k.version}</td>
          <td>{order?<Link to={'/orders/'+order.order_id}>{order.order_id}</Link>:'—'}</td>
          <td><span className={'badge '+(k.status==='RELEASED'?'green':'amber')}>{k.status}</span></td>
          <td>{order?<span className={'badge '+(['CLEAR','PAID','READY'].includes(order.finance_status)?'green':'amber')}>{order.finance_status}</span>:'—'}</td>
          <td><small>{order?`flow: ${order.flow_step}`:'—'}</small></td>
          <td><small>{k.released_at?`user #${k.released_by} · ${new Date(k.released_at+'Z').toLocaleString('id-ID')}`:'—'}</small></td>
          <td><small>{k.release_reason||'—'}</small></td>
          <td><small>{(k.status==='RELEASED')?'Menunggu Siti/COO':'—'}</small></td>
          <td className="td-action">
            {manager&&k.status==='PRINTED'&&<button className="btn sm primary" disabled={busy} onClick={()=>openRelease(k)}><Check size={13}/> Release to COO</button>}
            {!manager&&k.status==='PRINTED'&&<span className="badge amber">Menunggu Cecep</span>}
            {k.status==='RELEASED'&&<span className="badge green">Sudah dihandoff</span>}
          </td>
        </tr>;
      })}
      {!shown.length&&<tr><td colSpan={10} className="empty">
        {showReleased?'Belum ada SPK yang di-release.':'Tidak ada SPK siap Release to COO. Pastikan SPK sudah di-Print.'}
      </td></tr>}
    </tbody></table></div>

    {target&&<FormModal title={`Release to COO · ${target.spk_no} v${target.version}`}
      error={err} busy={busy} onClose={()=>{setTarget(null);setReadiness(null);setErr('')}} onSubmit={submit}>
      <p>Versi dokumen #{target.id}. Release ini mengesahkan SPK ke produksi; pelepasan batch COO adalah langkah terpisah.</p>
      {!readiness?<p>Memeriksa prasyarat...</p>:<div>
        {Object.entries(readiness.checks||{}).map(([key,check])=><div key={key} style={{marginBottom:6}}>
          <span className={'badge '+(check.ok?'green':'red')}>{check.ok?'Siap':'Belum'}</span> {check.label}
        </div>)}
      </div>}
      <label>Alasan release *<textarea required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)} rows={3}/></label>
      {target.version>1&&<label>Alasan koreksi versi *<textarea required maxLength={2000} value={correction} onChange={e=>setCorrection(e.target.value)} rows={3}/></label>}
    </FormModal>}
  </div>;
}