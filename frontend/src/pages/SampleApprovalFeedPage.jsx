import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';
import {RefreshCw,ShieldCheck,Paperclip} from 'lucide-react';

/* Revisi #14 poin 4 — PPM & SAMPLE APPROVAL FEED.
   Feed keputusan untuk Cecep: version, Article ID, evidence/source,
   completeness, buyer response, decision, reason, actor, timestamp, next action.
   Deby mengelola administrasi/bukti; Cecep mencatat keputusan buyer.

   Halaman ini TIDAK menggantikan pengelolaan proses Sample/PPM — itu tetap di
   /cmo/samples. Yang ini murni antrean keputusan, sesuai pemisahan yang diminta
   blueprint ("Sample Approval Feed" vs "PPM"). */

const ORDER_LABEL=id=>id==null?'—':'Order #'+id;

export default function SampleApprovalFeedPage(){
  const role=useRole();
  const canApprove=role==='CMO_MANAGER';
  const [list,setList]=useState([]),[orders,setOrders]=useState([]);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false),[decision,setDecision]=useState(null);
  const [showDecided,setShowDecided]=useState(false);

  async function load(){
    setBusy(true);
    try{
      const [samples,allOrders]=await Promise.all([api('/cmo/samples'),api('/orders')]);
      setList(samples);setOrders(allOrders);setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  const orderOf=id=>orders.find(o=>o.id===id);
  const evidenceCount=s=>s.evidence_count??0;
  /* Pending = bukti sudah ada tapi keputusan buyer belum dicatat. */
  const pending=list.filter(s=>s.customer_approved_by_id==null);
  const decided=list.filter(s=>s.customer_approved_by_id!=null);
  const shown=showDecided?decided:pending;

  async function submitDecision(e){
    e.preventDefault();setBusy(true);setErr('');
    try{
      await api(`/cmo/samples/${decision.sample.id}/customer-decision`,{
        method:'POST',body:JSON.stringify({action:decision.action,reason:decision.reason.trim()})});
      setDecision(null);await load();
    }catch(x){setErr(x.message)}finally{setBusy(false)}
  }

  return <div className="page">
    <div className="page-title">
      <div><h1>Sample Approval Feed</h1>
        <p>Keputusan buyer atas Sample/PPM. Deby menyiapkan bukti; Cecep mencatat keputusan.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    {err&&!decision&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards">
      <div className={'stat '+(pending.length?'amber':'green')}><strong>{pending.length}</strong><span>Menunggu keputusan buyer</span></div>
      <div className="stat blue"><strong>{decided.length}</strong><span>Sudah ada keputusan</span></div>
    </div>

    <div className="filter-bar">
      <button className={'pill '+(showDecided?'':'active in_progress')} onClick={()=>setShowDecided(false)}>Menunggu ({pending.length})</button>
      <button className={'pill '+(showDecided?'active done':'')} onClick={()=>setShowDecided(true)}>Sudah Diputus ({decided.length})</button>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>Article ID</th><th>Order</th><th>Versi / Proses</th><th>Evidence / Source</th>
      <th>Kelengkapan</th><th>Buyer Response</th><th>Decision</th><th>Reason</th>
      <th>Actor</th><th>Timestamp</th><th>Next Action</th>
    </tr></thead><tbody>
      {shown.map(s=>{
        const complete=evidenceCount(s)>0;
        const decidedFlag=s.customer_approved_by_id!=null;
        return <tr key={s.id}>
          <td><b>{s.article_code||'—'}</b></td>
          <td>{(()=>{const o=orderOf(s.order_fk);return o?<Link to={'/orders/'+o.order_id}>{o.order_id}</Link>:ORDER_LABEL(s.order_fk)})()}</td>
          <td><span className="badge gray">{s.status}</span></td>
          <td>{complete?<span className="badge blue">{evidenceCount(s)} file</span>:<span className="badge red">Belum ada</span>}</td>
          <td>{complete?<span className="badge green">Lengkap</span>:<span className="badge amber">Bukti kurang</span>}</td>
          <td>{s.customer_decision_reason||'—'}</td>
          <td>{decidedFlag?<span className={'badge '+(s.customer_decision_reason?'green':'amber')}>Tercatat</span>:<span className="badge amber">Menunggu</span>}</td>
          <td><small>{s.customer_decision_reason||'—'}</small></td>
          <td><small>{decidedFlag?`user #${s.customer_decision_by_id}`:'—'}</small></td>
          <td><small>{s.customer_decision_at?new Date(s.customer_decision_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
          <td className="td-action">
            {canApprove&&!decidedFlag&&<>
              <button className="btn sm primary" disabled={busy} onClick={()=>{setErr('');setDecision({sample:s,action:'APPROVE',reason:''})}}><ShieldCheck size={13}/> Catat Keputusan</button>
              <button className="btn sm" disabled={busy} onClick={()=>{setErr('');setDecision({sample:s,action:'REJECT',reason:''})}}>Minta Revisi</button>
            </>}
            {!canApprove&&!decidedFlag&&<Link className="btn sm" to="/cmo/samples"><Paperclip size={13}/> Kelola bukti</Link>}
            {decidedFlag&&<span className="badge green">Selesai</span>}
          </td>
        </tr>;
      })}
      {!shown.length&&<tr><td colSpan={11} className="empty">
        {showDecided?'Belum ada keputusan buyer yang tercatat.':'Tidak ada Sample/PPM yang menunggu keputusan.'}
      </td></tr>}
    </tbody></table></div>

    {decision&&<FormModal
      title={decision.action==='APPROVE'?'Catat keputusan customer — disetujui':'Catat keputusan customer — minta revisi'}
      error={err} busy={busy}
      onClose={()=>{setDecision(null);setErr('')}} onSubmit={submitDecision}>
      <p>{decision.action==='APPROVE'
        ?'Keputusan ini mengesahkan Sample/PPM untuk customer dan tidak dapat diubah dari form proses.'
        :'Keputusan ini mengembalikan Sample/PPM untuk diperbaiki oleh tim.'}</p>
      <label>{decision.action==='APPROVE'?'Referensi persetujuan customer *':'Alasan revisi dari customer *'}
        <textarea required value={decision.reason}
          onChange={e=>setDecision({...decision,reason:e.target.value})}
          placeholder={decision.action==='APPROVE'?'Contoh: Email buyer tanggal 19 Sept 2026':'Jelaskan perubahan yang diminta customer'} rows={3}/></label>
    </FormModal>}
  </div>;
}