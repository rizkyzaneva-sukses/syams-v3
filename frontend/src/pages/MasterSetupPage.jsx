import React,{useCallback,useEffect,useState} from 'react';
import {Link,useOutletContext} from 'react-router-dom';
import {api} from '../api';
import {canEditSettings} from '../control';

/* Pengaturan Master Control — setara tab MASTER ENGINE + SLA ENGINE di sheet lama.
   Semua peran boleh melihat; hanya CMO Manager yang boleh mengubah. Perubahan SLA
   selalu membuat versi baru lengkap dengan alasan, dan tidak menggeser order berjalan. */

function Simple({title,hint,rows,onAdd,onToggle,editable,extra}){
  const [name,setName]=useState(''),[label,setLabel]=useState('');
  return <section className="panel"><div className="panel-head"><h2>{title}</h2><span>{hint}</span></div>
    <div className="chips">{rows.map(r=><button key={r.id} type="button" disabled={!editable} className={'chip-toggle '+(r.is_active?'on':'off')} onClick={()=>onToggle(r)} title={editable?(r.is_active?'Klik untuk nonaktifkan':'Klik untuk aktifkan'):''}>{r.name}{r.role_label&&<small> · {r.role_label}</small>}{!r.is_active&&<small> (nonaktif)</small>}</button>)}</div>
    {editable&&<form className="add-row" onSubmit={e=>{e.preventDefault();if(!name.trim())return;onAdd({name:name.trim(),...(extra?{role_label:label.trim()||null}:{})}).then(ok=>{if(ok){setName('');setLabel('')}})}}>
      <input value={name} onChange={e=>setName(e.target.value)} placeholder={'Tambah '+title.toLowerCase()+'…'} aria-label={'Nama '+title}/>
      {extra&&<input value={label} onChange={e=>setLabel(e.target.value)} placeholder="Bagian / peran (opsional)" aria-label="Bagian atau peran"/>}
      <button className="btn primary sm">Tambah</button></form>}
  </section>;
}

export default function MasterSetupPage(){
  const role=useOutletContext()?.me?.role,editable=canEditSettings(role);
  const [garments,setGarments]=useState([]),[pics,setPics]=useState([]),[sla,setSla]=useState(null),[draft,setDraft]=useState(null),[versions,setVersions]=useState([]);
  const [reason,setReason]=useState(''),[err,setErr]=useState(''),[ok,setOk]=useState(''),[busy,setBusy]=useState(false);

  const load=useCallback(async()=>{
    try{
      const [g,p,s,v]=await Promise.all([api('/control/garment-types'),api('/control/pics'),api('/control/sla'),api('/control/sla/versions')]);
      setGarments(g);setPics(p);setSla(s);setDraft(s.items.map(i=>({...i})));setVersions(v);
    }catch(e){setErr(e.message)}
  },[]);
  useEffect(()=>{load()},[load]);

  async function mutate(fn){setErr('');setOk('');try{await fn();await load();return true}catch(e){setErr(e.message);return false}}
  const addGarment=body=>mutate(()=>api('/control/garment-types',{method:'POST',body:JSON.stringify(body)}));
  const toggleGarment=r=>mutate(()=>api('/control/garment-types/'+r.id,{method:'PATCH',body:JSON.stringify({is_active:!r.is_active})}));
  const addPic=body=>mutate(()=>api('/control/pics',{method:'POST',body:JSON.stringify(body)}));
  const togglePic=r=>mutate(()=>api('/control/pics/'+r.id,{method:'PATCH',body:JSON.stringify({is_active:!r.is_active})}));

  const dirty=draft&&sla&&JSON.stringify(draft)!==JSON.stringify(sla.items);
  const setItem=(code,key,value)=>setDraft(d=>d.map(i=>i.stage_code===code?{...i,[key]:value}:i));
  async function saveSla(e){
    e.preventDefault();setBusy(true);
    const items=draft.map(i=>({stage_code:i.stage_code,duration_days:Number(i.duration_days),primary_pic:i.primary_pic||null,is_active:i.is_active,
      daily_capacity:Number(i.daily_capacity),capacity_unit:i.capacity_unit,warning_pct:Number(i.warning_pct),note:i.note||null}));
    const done=await mutate(()=>api('/control/sla',{method:'POST',body:JSON.stringify({reason,items})}));
    if(done){setReason('');setOk('SLA versi baru tersimpan. Order yang sudah berjalan tetap memakai SLA lamanya.')}
    setBusy(false);
  }

  return <div className="page">
    <div className="page-title"><div><Link to="/master" className="back-link">← Kembali ke Master Control</Link><h1>Pengaturan Master Control</h1>
      <p>Daftar jenis pakaian, PIC, dan standar SLA tiap tahap.{!editable&&' Hanya CMO Manager yang dapat mengubah; Anda dapat melihat saja.'}</p></div></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}{ok&&<div className="notice success">{ok}</div>}
    <div className="grid-half">
      <Simple title="Jenis pakaian" hint="Muncul sebagai pilihan di form PO" rows={garments} editable={editable} onAdd={addGarment} onToggle={toggleGarment}/>
      <Simple title="PIC" hint="Muncul sebagai pilihan PIC & filter" rows={pics} editable={editable} onAdd={addPic} onToggle={togglePic} extra/>
    </div>

    <section className="panel"><div className="panel-head"><h2>SLA & kapasitas per tahap</h2><span>{sla?`Versi aktif v${sla.version} — ${sla.change_reason}`:'Memuat…'}</span></div>
      {draft&&<form onSubmit={saveSla}><div className="table-scroll"><table className="sla-table">
        <thead><tr><th>Tahap</th><th>Durasi (hari)</th><th>PIC utama</th><th>Dipakai</th><th>Kapasitas / hari</th><th>Satuan</th><th>Peringatan di (%)</th><th>Catatan</th></tr></thead>
        <tbody>{draft.map(i=><tr key={i.stage_code}><td><b>{i.label}</b>{i.kind==='auto'&&<small> otomatis</small>}</td>
          <td><input type="number" min="0" max="365" disabled={!editable} value={i.duration_days} onChange={e=>setItem(i.stage_code,'duration_days',e.target.value)} aria-label={'Durasi '+i.label}/></td>
          <td><input disabled={!editable} value={i.primary_pic||''} maxLength={80} onChange={e=>setItem(i.stage_code,'primary_pic',e.target.value)} aria-label={'PIC utama '+i.label}/></td>
          <td><input type="checkbox" disabled={!editable} checked={i.is_active} onChange={e=>setItem(i.stage_code,'is_active',e.target.checked)} aria-label={'Dipakai '+i.label}/></td>
          <td><input type="number" min="0" disabled={!editable} value={i.daily_capacity} onChange={e=>setItem(i.stage_code,'daily_capacity',e.target.value)} aria-label={'Kapasitas '+i.label}/></td>
          <td><input disabled={!editable} value={i.capacity_unit} maxLength={16} onChange={e=>setItem(i.stage_code,'capacity_unit',e.target.value)} aria-label={'Satuan '+i.label}/></td>
          <td><input type="number" min="1" max="100" disabled={!editable} value={Math.round(i.warning_pct*100)} onChange={e=>setItem(i.stage_code,'warning_pct',Number(e.target.value)/100)} aria-label={'Peringatan '+i.label}/></td>
          <td className="wrap"><small>{i.note||''}</small></td></tr>)}</tbody></table></div>
        {editable&&<div className="sla-save"><label>Alasan perubahan * <input required minLength={5} maxLength={500} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Contoh: printing diperpanjang karena mesin baru"/></label>
          <button className="btn primary" disabled={busy||!dirty}>{dirty?'Simpan sebagai versi baru':'Belum ada perubahan'}</button></div>}
      </form>}
      {versions.length>0&&<details><summary>Riwayat versi SLA ({versions.length})</summary>{versions.map(v=><div key={v.version} className="block-row done"><div><b>v{v.version}</b> — {v.change_reason}<br/><small>{String(v.created_at).slice(0,10)}</small></div></div>)}</details>}
    </section>
  </div>;
}
