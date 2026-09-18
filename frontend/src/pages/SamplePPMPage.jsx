import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';
import {Plus,Edit2,Search,Paperclip,Download,ShieldCheck} from 'lucide-react';

const empty={order_fk:'',article_code:'',status:'PROCESS',notes:'',requested_date:'',completed_date:''};
const statusOpts=['PROCESS','IN_PROCESS','PENDING','COMPLETED','REVISION'];
const evidenceAccept='application/pdf,image/png,image/jpeg';

function customerDecision(sample){
  if(sample.customer_decision_status) return sample.customer_decision_status;
  if(sample.status==='APPROVED'||sample.status==='REJECTED') return sample.status;
  return null;
}

export default function SamplePPMPage(){
  const role=useRole();
  const canRecord=['CMO_MANAGER','SAMPLE_PIC'].includes(role);
  const canApprove=role==='CMO_MANAGER';
  const canViewEvidence=['CEO','CMO_MANAGER','CMO_SUPPORT','SAMPLE_PIC','COO_MANAGER'].includes(role);
  const [list,setList]=useState([]),[orders,setOrders]=useState([]);
  const [err,setErr]=useState('');
  const [q,setQ]=useState(''),[filterStatus,setFilterStatus]=useState('');
  const [form,setForm]=useState(null),[saving,setSaving]=useState(false);
  const [evidence,setEvidence]=useState(null),[evidenceFile,setEvidenceFile]=useState(null);
  const [decision,setDecision]=useState(null);

  async function load(){
    try{
      const [samples,allOrders]=await Promise.all([api('/cmo/samples'),api('/orders')]);
      setList(samples);setOrders(allOrders);setErr('');
    }catch(error){setErr(error.message)}
  }
  useEffect(()=>{load()},[]);

  function filtered(){
    return list.filter(sample=>{
      if(filterStatus&&sample.status!==filterStatus) return false;
      if(!q) return true;
      const term=q.toLowerCase();
      return [sample.article_code,sample.notes,sample.customer_decision_reason]
        .some(value=>String(value||'').toLowerCase().includes(term));
    });
  }

  async function save(event){
    event.preventDefault(); setSaving(true);setErr('');
    try{
      const payload={...form,order_fk:form.order_fk?Number(form.order_fk):null};
      if(form.id) await api('/cmo/samples/'+form.id,{method:'PATCH',body:JSON.stringify(payload)});
      else await api('/cmo/samples',{method:'POST',body:JSON.stringify(payload)});
      setForm(null);await load();
    }catch(error){setErr(error.message)}finally{setSaving(false)}
  }

  async function openEvidence(sample){
    setErr('');setEvidenceFile(null);
    try{
      const rows=await api(`/cmo/samples/${sample.id}/evidence`);
      setEvidence({sample,rows});
    }catch(error){setErr(error.message)}
  }

  async function uploadEvidence(event){
    event.preventDefault();
    if(!evidenceFile){setErr('Pilih file bukti terlebih dahulu.');return}
    setSaving(true);setErr('');
    try{
      const data=new FormData();
      data.append('evidence',evidenceFile);
      await api(`/cmo/samples/${evidence.sample.id}/evidence`,{method:'POST',body:data});
      const rows=await api(`/cmo/samples/${evidence.sample.id}/evidence`);
      setEvidence(current=>({...current,rows}));setEvidenceFile(null);await load();
    }catch(error){setErr(error.message)}finally{setSaving(false)}
  }

  async function downloadEvidence(item){
    setSaving(true);setErr('');
    try{
      const blob=await api(`/cmo/samples/${evidence.sample.id}/evidence/${item.id}/file`,{responseType:'blob'});
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download=item.file_name||item.document_name||`evidence-${item.id}`;
      document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){setErr(error.message)}finally{setSaving(false)}
  }

  async function decide(event){
    event.preventDefault();setSaving(true);setErr('');
    try{
      await api(`/cmo/samples/${decision.sample.id}/customer-decision`,{
        method:'POST',body:JSON.stringify({action:decision.action,reason:decision.reason.trim()})
      });
      setDecision(null);await load();
    }catch(error){setErr(error.message)}finally{setSaving(false)}
  }

  const f2=filtered();
  const orderLabel=id=>orders.find(order=>order.id===id)?.order_id||'-';
  const evidenceCount=sample=>sample.evidence_count??sample.evidences?.length??0;

  return <div className="page">
    <div className="page-title"><div><h1>Sample & PPM</h1><p>Catat proses, simpan bukti, lalu Cecep mengesahkan keputusan customer.</p></div>
      {canRecord&&<button className="btn primary" onClick={()=>{setErr('');setForm({...empty})}}><Plus size={16}/> Tambah Sample</button>}</div>
    {err&&!form&&!evidence&&!decision&&<div className="notice danger" role="alert">{err}</div>}
    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/><input placeholder="Cari article, catatan, atau keputusan customer..." value={q} onChange={event=>setQ(event.target.value)}/></div>
      <div className="filter-pills">{statusOpts.map(status=><button key={status} className={'pill '+(filterStatus===status?'active '+status.toLowerCase():'')} onClick={()=>setFilterStatus(filterStatus===status?'':status)}>{status}</button>)}</div>
    </div>
    <div className="table-scroll"><table><thead><tr><th>Order / Article</th><th>Jadwal</th><th>Proses</th><th>Bukti</th><th>Keputusan Customer</th><th>Catatan</th><th>Aksi</th></tr></thead>
      <tbody>{f2.map(sample=>{
        const decisionStatus=customerDecision(sample);
        return <tr key={sample.id}>
          <td>{orderLabel(sample.order_fk)}<br/><b>{sample.article_code||'-'}</b></td>
          <td>Diminta: {sample.requested_date||'-'}<br/>Selesai: {sample.completed_date||'-'}</td>
          <td><span className={'badge '+(sample.status==='APPROVED'?'green':sample.status==='REJECTED'?'red':sample.status==='REVISION'?'red':'amber')}>{sample.status}</span></td>
          <td>{evidenceCount(sample)?<span className="badge blue">{evidenceCount(sample)} file</span>:'Belum ada'}{canViewEvidence&&<button className="btn sm" onClick={()=>openEvidence(sample)}><Paperclip size={13}/> Bukti</button>}</td>
          <td>{decisionStatus?<><span className={'badge '+(decisionStatus==='APPROVED'?'green':'red')}>{decisionStatus}</span>{sample.customer_decision_at&&<small><br/>{new Date(sample.customer_decision_at+'Z').toLocaleString('id-ID')}</small>}{sample.customer_decision_reason&&<small><br/>{sample.customer_decision_reason}</small>}</>:'Menunggu keputusan'}</td>
          <td>{sample.notes||'-'}</td>
          <td className="td-action">
            {canRecord&&sample.status!=='APPROVED'&&<button className="icon-btn" onClick={()=>{setErr('');setForm({...sample,order_fk:sample.order_fk||'',requested_date:sample.requested_date||'',completed_date:sample.completed_date||'',notes:sample.notes||''})}} title="Edit proses"><Edit2 size={15}/></button>}
            {canApprove&&sample.status!=='APPROVED'&&<><button className="btn sm primary" onClick={()=>{setErr('');setDecision({sample,action:'APPROVE',reason:''})}}><ShieldCheck size={13}/> Setujui Customer</button><button className="btn sm" onClick={()=>{setErr('');setDecision({sample,action:'REJECT',reason:''})}}>Minta Revisi</button></>}
          </td>
        </tr>;
      })}
      {f2.length===0&&<tr><td colSpan={7} className="empty">Belum ada Sample atau PPM.</td></tr>}</tbody></table></div>

    {form&&<FormModal title={form.id?'Edit proses Sample / PPM':'Tambah Sample / PPM'} error={err} busy={saving} onClose={()=>{setForm(null);setErr('')}} onSubmit={save}>
      <div className="form-grid">
        <label>Order<select required value={form.order_fk} onChange={event=>setForm({...form,order_fk:event.target.value})}><option value="">Pilih order...</option>{orders.map(order=><option key={order.id} value={order.id}>{order.order_id} — {order.buyer}</option>)}</select></label>
        <label>Article Code *<input required value={form.article_code} onChange={event=>setForm({...form,article_code:event.target.value})} placeholder="ART-001"/></label>
      </div>
      <div className="form-grid">
        <label>Tanggal diminta<input type="date" value={form.requested_date} onChange={event=>setForm({...form,requested_date:event.target.value})}/></label>
        <label>Tanggal selesai<input type="date" value={form.completed_date} onChange={event=>setForm({...form,completed_date:event.target.value})}/></label>
        <label>Status proses<select value={form.status} onChange={event=>setForm({...form,status:event.target.value})}>{statusOpts.map(status=><option key={status}>{status}</option>)}</select></label>
      </div>
      <label>Catatan proses<textarea value={form.notes} onChange={event=>setForm({...form,notes:event.target.value})} placeholder="Keterangan sample atau PPM..." rows={3}/></label>
    </FormModal>}

    {evidence&&<div className="modal-bg" onClick={()=>{setEvidence(null);setErr('')}}><div className="modal" onClick={event=>event.stopPropagation()}><div className="modal-head"><h2>Bukti Sample / PPM · {evidence.sample.article_code||'Sample'}</h2><button type="button" className="icon-btn" disabled={saving} onClick={()=>{setEvidence(null);setErr('')}} aria-label="Tutup">×</button></div><form onSubmit={uploadEvidence}>{err&&<div className="notice danger" role="alert">{err}</div>}
      <p className="notice info">Simpan foto, PDF PPM, atau bukti persetujuan customer pada record ini. File tersimpan bersama data aplikasi.</p>
      {evidence.rows.length?<div className="table-scroll"><table><thead><tr><th>File</th><th>Diunggah</th><th></th></tr></thead><tbody>{evidence.rows.map(item=><tr key={item.id}><td>{item.file_name||item.document_name||`Bukti #${item.id}`}</td><td>{item.created_at?new Date(item.created_at+'Z').toLocaleString('id-ID'):'—'}</td><td><button type="button" className="btn sm" disabled={saving} onClick={()=>downloadEvidence(item)}><Download size={13}/> Unduh</button></td></tr>)}</tbody></table></div>:<p>Belum ada bukti yang diunggah.</p>}
      {canRecord&&<><label>File bukti *<input required type="file" accept={evidenceAccept} onChange={event=>setEvidenceFile(event.target.files?.[0]||null)}/><small>PDF, PNG, atau JPG. Maksimal 10 MB.</small></label><div className="modal-foot"><button type="button" className="btn" onClick={()=>{setEvidence(null);setErr('')}}>Tutup</button><button className="btn primary" disabled={saving||!evidenceFile}><Paperclip size={14}/> {saving?'Mengunggah...':'Simpan bukti'}</button></div></>}
      {!canRecord&&<div className="modal-foot"><button type="button" className="btn" onClick={()=>{setEvidence(null);setErr('')}}>Tutup</button></div>}
    </form></div></div>}

    {decision&&<div className="modal-bg" onClick={()=>{setDecision(null);setErr('')}}><div className="modal" onClick={event=>event.stopPropagation()}><div className="modal-head"><h2>{decision.action==='APPROVE'?'Setujui Sample oleh Customer':'Minta Revisi Sample'}</h2><button type="button" className="icon-btn" disabled={saving} onClick={()=>{setDecision(null);setErr('')}} aria-label="Tutup">×</button></div><form onSubmit={decide}>{err&&<div className="notice danger" role="alert">{err}</div>}
      <p>{decision.action==='APPROVE'?'Keputusan ini mengesahkan Sample / PPM untuk customer dan tidak dapat diubah dari form proses.':'Keputusan ini mengembalikan Sample / PPM untuk diperbaiki oleh tim.'}</p>
      <label>{decision.action==='APPROVE'?'Referensi persetujuan customer *':'Alasan revisi dari customer *'}<textarea required value={decision.reason} onChange={event=>setDecision({...decision,reason:event.target.value})} placeholder={decision.action==='APPROVE'?'Contoh: Email buyer tanggal 19 Sept 2026':'Jelaskan perubahan yang diminta customer'} rows={3}/></label>
      <div className="modal-foot"><button type="button" className="btn" onClick={()=>{setDecision(null);setErr('')}}>Batal</button><button className="btn primary" disabled={saving||!decision.reason.trim()}>{decision.action==='APPROVE'?'Sahkan keputusan':'Kirim untuk revisi'}</button></div>
    </form></div></div>}
  </div>;
}
