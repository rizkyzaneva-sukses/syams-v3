import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {Plus,Edit2,Trash2,X,Check,Search} from 'lucide-react';

const empty={name:'',country:'',contact_name:'',contact_info:'',phone:'',shipping_carrier:'',address:'',notes:''};

export default function CustomerList(){
  const [list,setList]=useState([]),[err,setErr]=useState('');
  const [q,setQ]=useState('');
  const [form,setForm]=useState(null); // null = hidden, {} = new, {..} = edit
  const [saving,setSaving]=useState(false);

  function load(){api('/cmo/customers').then(setList).catch(e=>setErr(e.message))}
  useEffect(load,[]);

  function filtered(){return list.filter(c=>!q||c.name.toLowerCase().includes(q.toLowerCase())||((c.country||'').toLowerCase().includes(q.toLowerCase())))}

  async function save(e){
    e.preventDefault(); setSaving(true);
    try{
      if(form.id){
        await api('/cmo/customers/'+form.id,{method:'PATCH',body:JSON.stringify(form)});
      }else{
        await api('/cmo/customers',{method:'POST',body:JSON.stringify(form)});
      }
      setForm(null); load();
    }catch(x){alert(x.message)}
    setSaving(false);
  }

  async function del(id){
    if(!confirm('Hapus customer ini?')) return;
    try{await api('/cmo/customers/'+id,{method:'DELETE'});load();}catch(x){alert(x.message)}
  }

  const f2=filtered();
  return <div className="page">
    <div className="page-title"><div><h1>Customer / Buyer</h1><p>{list.length} customer terdaftar</p></div>
      <button className="btn primary" onClick={()=>setForm({...empty})}><Plus size={16}/> Tambah</button></div>
    {err&&<div className="notice danger">{err}</div>}
    <div className="search-bar"><Search size={16}/><input placeholder="Cari nama / negara..." value={q} onChange={e=>setQ(e.target.value)}/></div>
    <div className="table-scroll"><table><thead><tr><th>Nama</th><th>Negara</th><th>Kontak</th><th>Telepon/Email</th><th>Catatan</th><th>Aksi</th></tr></thead>
    <tbody>{f2.map(c=><tr key={c.id}><td><b>{c.name}</b></td><td>{c.country||'-'}</td><td>{c.contact_name||'-'}</td><td>{c.contact_info||'-'}</td><td className="td-sm">{c.notes||'-'}</td>
    <td className="td-action"><button className="icon-btn" onClick={()=>setForm({...c})} title="Edit"><Edit2 size={15}/></button><button className="icon-btn danger" onClick={()=>del(c.id)} title="Hapus"><Trash2 size={15}/></button></td></tr>)}
    {f2.length===0&&<tr><td colSpan={6} className="empty">Belum ada data</td></tr>}</tbody></table></div>

    {form&&<div className="modal-bg" onClick={()=>setForm(null)}>
    <div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.id?'Edit':'Tambah'} Customer</h2><button className="icon-btn" onClick={()=>setForm(null)}><X size={18}/></button></div>
      <form onSubmit={save}>
        <label>Nama Customer *<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
        <div className="form-row"><label>Negara<input value={form.country||''} onChange={e=>setForm({...form,country:e.target.value})} placeholder="ID / US / JP..."/></label>
        <label>Nama Kontak<input value={form.contact_name||''} onChange={e=>setForm({...form,contact_name:e.target.value})}/></label></div>
        <div className="form-row"><label>Telepon / Email<input value={form.contact_info||''} onChange={e=>setForm({...form,contact_info:e.target.value})}/></label>
        <label>Nomor ponsel (tampil di SPK)<input maxLength={40} value={form.phone||''} onChange={e=>setForm({...form,phone:e.target.value})}/></label></div>
        <label>Ekspedisi pengiriman<input maxLength={120} value={form.shipping_carrier||''} onChange={e=>setForm({...form,shipping_carrier:e.target.value})} placeholder="mis. JNE Trucking"/></label>
        <label>Alamat<textarea rows={2} value={form.address||''} onChange={e=>setForm({...form,address:e.target.value})}/></label>
        <label>Catatan<textarea rows={2} value={form.notes||''} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={saving}><Check size={14}/> {saving?'Menyimpan...':'Simpan'}</button></div>
      </form>
    </div></div>}
  </div>
}
