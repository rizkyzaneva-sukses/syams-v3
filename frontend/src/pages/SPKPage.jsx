import React,{useEffect,useState} from 'react';
import {useOutletContext} from 'react-router-dom';
import {api} from '../api';
import {Plus,Edit2,Trash2,X,Check,Search,Eye,Printer,FileCheck2,Ban} from 'lucide-react';

const empty={spk_no:'',order_fk:'',notes:''};
const statusOpts=['DRAFT','GENERATED','PRINTED','RELEASED','VOID'];

export default function SPKPage(){
  const role=useOutletContext()?.me?.role;
  const manager=role==='CMO_MANAGER', preparer=manager||role==='CMO_SUPPORT';
  const [list,setList]=useState([]),[orders,setOrders]=useState([]);
  const [err,setErr]=useState(''),[q,setQ]=useState(''),[filterStatus,setFilterStatus]=useState('');
  const [form,setForm]=useState(null),[busy,setBusy]=useState(false),[preview,setPreview]=useState('');
  const [releaseTarget,setReleaseTarget]=useState(null),[readiness,setReadiness]=useState(null);
  const [releaseReason,setReleaseReason]=useState(''),[correctionReason,setCorrectionReason]=useState('');

  async function load(){
    try{const [s,o]=await Promise.all([api('/cmo/spk'),api('/orders')]);setList(s);setOrders(o);setErr('');}
    catch(e){setErr(e.message);}
  }
  useEffect(()=>{load()},[]);
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview]);

  const filtered=list.filter(s=>{
    if(filterStatus&&s.status!==filterStatus)return false;
    const term=q.trim().toLowerCase();
    return !term||[s.spk_no,s.notes,orders.find(o=>o.id===s.order_fk)?.order_id].some(v=>String(v||'').toLowerCase().includes(term));
  });
  const orderLabel=id=>orders.find(o=>o.id===id)?.order_id||String(id);

  async function save(ev){
    ev.preventDefault();setBusy(true);setErr('');
    try{
      if(form.id)await api(`/cmo/spk/${form.id}`,{method:'PATCH',body:JSON.stringify({notes:form.notes})});
      else await api('/cmo/spk',{method:'POST',body:JSON.stringify({spk_no:form.spk_no.trim(),order_fk:Number(form.order_fk),notes:form.notes})});
      setForm(null);await load();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  async function act(spk,action){
    if(action==='void'&&!confirm(`Void SPK ${spk.spk_no}?`))return;
    if(action==='delete'&&!confirm(`Hapus draft SPK ${spk.spk_no}?`))return;
    setBusy(true);setErr('');
    try{
      if(action==='delete')await api(`/cmo/spk/${spk.id}`,{method:'DELETE'});
      else await api(`/cmo/spk/${spk.id}/${action}`,{method:'POST'});
      await load();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  async function openRelease(spk){
    setReleaseTarget(spk);setReadiness(null);setReleaseReason('');setCorrectionReason('');setErr('');
    try{setReadiness(await api(`/cmo/spk/${spk.id}/release-readiness`));}
    catch(e){setErr(e.message);setReleaseTarget(null);}
  }

  async function submitRelease(ev){
    ev.preventDefault();if(!releaseTarget)return;
    setBusy(true);setErr('');
    try{
      await api(`/cmo/spk/${releaseTarget.id}/release`,{method:'POST',body:JSON.stringify({
        version_id:releaseTarget.id,reason:releaseReason.trim(),
        correction_reason:correctionReason.trim()||null})});
      setReleaseTarget(null);setReadiness(null);await load();
    }catch(e){setErr(e.message);try{setReadiness(await api(`/cmo/spk/${releaseTarget.id}/release-readiness`))}catch{}}
    finally{setBusy(false)}
  }

  async function showPdf(spk,print=false){
    setBusy(true);setErr('');
    const tab=print?window.open('','_blank'):null;
    try{
      const blob=await api(`/cmo/spk/${spk.id}/${print?'print':'pdf'}`,
        print?{method:'POST',responseType:'blob'}:{responseType:'blob'});
      const url=URL.createObjectURL(blob);
      if(print){
        if(tab){tab.location.href=url;tab.onload=()=>{try{tab.print()}catch{}};}
        else{setPreview(url);setErr('PDF siap. Gunakan tombol Print di penampil PDF.');}
        setTimeout(()=>URL.revokeObjectURL(url),120000);
        await load();
      }else setPreview(url);
    }catch(e){if(tab)tab.close();setErr(e.message)}finally{setBusy(false)}
  }

  return <div className="page">
    <div className="page-title"><div><h1>SPK</h1><p>Draft → Generate → Preview PDF → Print. Print tidak merilis SPK ke produksi.</p></div>
      {preparer&&<button className="btn primary" onClick={()=>setForm({...empty})}><Plus size={16}/> Buat Draft</button>}</div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/><input placeholder="Cari nomor SPK, order, catatan..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">{statusOpts.map(s=><button key={s} className={'pill '+(filterStatus===s?'active '+s.toLowerCase():'')} onClick={()=>setFilterStatus(filterStatus===s?'':s)}>{s}</button>)}</div>
    </div>
    <div className="table-scroll"><table><thead><tr><th>No. SPK</th><th>Versi</th><th>Order</th><th>Status</th><th>Catatan</th><th>Release CMO</th><th>Aksi</th></tr></thead>
      <tbody>{filtered.map(s=><tr key={s.id}>
        <td><b>{s.spk_no}</b></td><td>v{s.version}</td><td>{orderLabel(s.order_fk)}</td>
        <td><span className={'badge '+(['RELEASED','PRINTED'].includes(s.status)?'green':s.status==='GENERATED'?'amber':'gray')}>{s.status}</span></td>
        <td>{s.notes||'—'}</td>
        <td>{s.released_at?<span title={s.release_reason||''}>v{s.released_version} · {new Date(s.released_at+'Z').toLocaleString('id-ID')} · user #{s.released_by}</span>:s.status==='RELEASED'?'Riwayat lama — approver tidak tercatat':'—'}</td>
        <td className="td-action">
          {preparer&&s.status==='DRAFT'&&<>
            <button className="btn" disabled={busy} onClick={()=>setForm({id:s.id,notes:s.notes||''})}><Edit2 size={14}/> Edit</button>
            <button className="btn primary" disabled={busy} onClick={()=>act(s,'generate')}><FileCheck2 size={14}/> Generate</button>
          </>}
          {preparer&&['GENERATED','PRINTED','RELEASED'].includes(s.status)&&<button className="btn" disabled={busy} onClick={()=>showPdf(s)}><Eye size={14}/> Preview PDF</button>}
          {preparer&&['GENERATED','PRINTED'].includes(s.status)&&<button className="btn" disabled={busy} onClick={()=>showPdf(s,true)}><Printer size={14}/> Print</button>}
          {manager&&s.status==='PRINTED'&&<button className="btn primary" disabled={busy} onClick={()=>openRelease(s)}><Check size={14}/> Release</button>}
          {manager&&['DRAFT','GENERATED','PRINTED'].includes(s.status)&&<button className="btn" disabled={busy} onClick={()=>act(s,'void')}><Ban size={14}/> Void</button>}
          {manager&&s.status==='DRAFT'&&<button className="icon-btn danger" disabled={busy} onClick={()=>act(s,'delete')} title="Hapus draft"><Trash2 size={15}/></button>}
        </td>
      </tr>)}{filtered.length===0&&<tr><td colSpan={7} className="empty">Tidak ada SPK</td></tr>}</tbody></table></div>
    {form&&<div className="modal-bg" onClick={()=>setForm(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.id?'Edit Draft':'Buat Draft SPK'}</h2><button className="icon-btn" onClick={()=>setForm(null)}><X size={18}/></button></div>
      <form onSubmit={save}>
        {!form.id&&<div className="form-grid">
          <label>No. SPK *<input required value={form.spk_no} onChange={e=>setForm({...form,spk_no:e.target.value})} placeholder="SPK-001"/></label>
          <label>Order *<select required value={form.order_fk} onChange={e=>setForm({...form,order_fk:e.target.value})}><option value="">Pilih order...</option>{orders.filter(o=>o.order_type!=='SAMPLE_ONLY').map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}</select></label>
        </div>}
        <label>Catatan<textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows={3}/></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={busy}><Check size={14}/> Simpan Draft</button></div>
      </form>
    </div></div>}
    {preview&&<div className="modal-bg" onClick={()=>setPreview('')}><div className="modal" style={{width:'min(95vw,1000px)'}} onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>Preview PDF SPK</h2><button className="icon-btn" onClick={()=>setPreview('')}><X size={18}/></button></div>
      <iframe title="Preview PDF SPK" src={preview} style={{width:'100%',height:'75vh',border:0}}/>
    </div></div>}
    {releaseTarget&&<div className="modal-bg" onClick={()=>setReleaseTarget(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>CMO SPK Release · {releaseTarget.spk_no} v{releaseTarget.version}</h2><button className="icon-btn" onClick={()=>setReleaseTarget(null)}><X size={18}/></button></div>
      <p>Versi dokumen #{releaseTarget.id}. Release ini mengesahkan SPK ke produksi; pelepasan batch COO adalah langkah terpisah.</p>
      {!readiness?<p>Memeriksa prasyarat...</p>:<div>
        {Object.entries(readiness.checks).map(([key,check])=><div key={key} style={{marginBottom:6}}>
          <span className={'badge '+(check.ok?'green':'red')}>{check.ok?'Siap':'Belum'}</span> {check.label}
        </div>)}
      </div>}
      <form onSubmit={submitRelease}>
        <label>Alasan release *<textarea required maxLength={2000} value={releaseReason} onChange={e=>setReleaseReason(e.target.value)} rows={3}/></label>
        {releaseTarget.version>1&&<label>Alasan koreksi versi *<textarea required maxLength={2000} value={correctionReason} onChange={e=>setCorrectionReason(e.target.value)} rows={3}/></label>}
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setReleaseTarget(null)}>Batal</button>
          <button className="btn primary" disabled={busy||!readiness?.ready||!releaseReason.trim()||(releaseTarget.version>1&&!correctionReason.trim())}>Release versi ini</button></div>
      </form>
    </div></div>}
  </div>;
}
