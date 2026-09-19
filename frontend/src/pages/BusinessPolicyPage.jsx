import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {History} from 'lucide-react';

/* Revisi #76: perubahan policy harus berversi — alasan perubahan wajib, dan
   riwayat versi (nilai lama, tanggal berlaku, pelaku) bisa dilihat CEO. */
const empty={minimum_margin_percent:'',minimum_dp_percent:'',cfo_quotation_limit:'',allow_credit_terms:false};
export default function BusinessPolicyPage(){
 const [policy,setPolicy]=useState(empty),[reason,setReason]=useState(''),[effective,setEffective]=useState('');
 const [versions,setVersions]=useState([]),[showHistory,setShowHistory]=useState(false);
 const [error,setError]=useState(''),[saved,setSaved]=useState(''),[busy,setBusy]=useState(false);

 function loadVersions(){
   api('/config/business-policy/versions').then(setVersions).catch(()=>setVersions([]));
 }
 useEffect(()=>{api('/config/business-policy').then(setPolicy).catch(()=>{});loadVersions()},[]);

 const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID');

 async function save(e){
   e.preventDefault();setBusy(true);setError('');setSaved('');
   try{
     await api('/config/business-policy',{method:'PUT',body:JSON.stringify({
       minimum_margin_percent:Number(policy.minimum_margin_percent),
       minimum_dp_percent:Number(policy.minimum_dp_percent),
       cfo_quotation_limit:Number(policy.cfo_quotation_limit),
       allow_credit_terms:policy.allow_credit_terms,
       change_reason:reason.trim(),
       effective_from:effective||null,
     })});
     setSaved('Kebijakan tersimpan sebagai versi baru dan diaudit.');
     setReason('');setEffective('');
     loadVersions();
   }catch(x){setError(x.message)}finally{setBusy(false)}
 }

 return <div className="page">
  <div className="page-title"><div><h1>Kebijakan Pricing &amp; Payment</h1><p>CEO menetapkan batas yang berlaku untuk approval quotation dan Finance Gate G1. Setiap perubahan menjadi versi baru.</p></div>
  <button className="btn" onClick={()=>setShowHistory(v=>!v)}><History size={15}/> Riwayat versi ({versions.length})</button></div>
  {error&&<div className="notice danger" role="alert">{error}</div>}
  {saved&&<div className="notice success" role="status">{saved}</div>}

  {showHistory&&<section className="panel">
    <div className="panel-head"><h2>Riwayat perubahan kebijakan</h2><span>Tidak ada versi yang ditimpa</span></div>
    {versions.length?<div className="table-scroll"><table><thead><tr>
      <th>Versi</th><th>Berlaku</th><th>Margin min</th><th>DP min</th><th>Limit CFO</th><th>Alasan perubahan</th><th>Diubah oleh</th><th>Nilai sebelumnya</th>
    </tr></thead><tbody>{versions.map(v=><tr key={v.id}>
      <td><b>v{v.version}</b>{v.is_active&&<> <span className="badge green">berlaku</span></>}</td>
      <td>{v.effective_from}{v.effective_to?` → ${v.effective_to}`:''}</td>
      <td>{Number(v.policy.minimum_margin_percent)}%</td>
      <td>{Number(v.policy.minimum_dp_percent)}%</td>
      <td>{money(v.policy.cfo_quotation_limit)}</td>
      <td>{v.change_reason}</td>
      <td>{v.changed_by||'—'}<br/><small>{v.created_at?new Date(v.created_at).toLocaleString('id-ID'):''}</small></td>
      <td className="td-sm" style={{maxWidth:'220px'}}>{v.previous?<small>margin {Number(v.previous.minimum_margin_percent)}%, DP {Number(v.previous.minimum_dp_percent)}%, limit {money(v.previous.cfo_quotation_limit)}</small>:'— (versi pertama)'}</td>
    </tr>)}</tbody></table></div>:<p className="empty">Belum ada riwayat versi.</p>}
  </section>}

  <form className="panel" onSubmit={save}>
    <div className="form-grid">
      <label>Margin minimum (%)<input type="number" min="0" max="100" step="0.01" required value={policy.minimum_margin_percent} onChange={e=>setPolicy({...policy,minimum_margin_percent:e.target.value})}/></label>
      <label>DP minimum (%)<input type="number" min="0" max="100" step="0.01" required value={policy.minimum_dp_percent} onChange={e=>setPolicy({...policy,minimum_dp_percent:e.target.value})}/></label>
      <label>Limit approval CFO (Rp)<input type="number" min="0.01" step="0.01" required value={policy.cfo_quotation_limit} onChange={e=>setPolicy({...policy,cfo_quotation_limit:e.target.value})}/></label>
      <label>Berlaku mulai<input type="date" value={effective} onChange={e=>setEffective(e.target.value)}/><small>Kosongkan untuk berlaku hari ini.</small></label>
    </div>
    <label><input type="checkbox" checked={Boolean(policy.allow_credit_terms)} onChange={e=>setPolicy({...policy,allow_credit_terms:e.target.checked})}/> Izinkan terms kredit dengan tanggal jatuh tempo dan bukti kontrak</label>
    <label>Alasan perubahan *<textarea required minLength={5} rows={2} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Contoh: menaikkan margin minimum setelah kenaikan harga bahan"/></label>
    <div className="modal-foot"><button className="btn primary" disabled={busy||reason.trim().length<5}>{busy?'Menyimpan...':'Simpan Kebijakan'}</button></div>
  </form>
 </div>;
}
