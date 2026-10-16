import React,{useEffect,useState} from 'react';
import {api} from '../api';
import ImageUpload from '../components/ImageUpload';

/* Profil perusahaan (khusus CEO / pemilik): nama, kontak, dan LOGO yang dipakai di Proforma Invoice dan SPK. */
export default function CompanyProfilePage(){
  const [form,setForm]=useState(null),[err,setErr]=useState(''),[ok,setOk]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{api('/company/profile').then(setForm).catch(e=>setErr(e.message))},[]);
  const set=(key,value)=>setForm(f=>({...f,[key]:value}));
  async function save(e){
    e.preventDefault();setBusy(true);setErr('');setOk('');
    try{
      const {name,tagline,phone,email,address,logo_image_id}=form;
      setForm(await api('/company/profile',{method:'PUT',body:JSON.stringify({name,tagline,phone,email,address,logo_image_id})}));
      setOk('Profil perusahaan tersimpan. Logo dipakai di dokumen berikutnya.');
    }catch(x){setErr(x.message)}finally{setBusy(false)}
  }
  return <div className="page">
    <div className="page-title"><div><h1>Profil Perusahaan & Logo</h1><p>Muncul di kop Proforma Invoice dan SPK. Hanya pemilik (CEO) yang dapat mengubah.</p></div></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}{ok&&<div className="notice success">{ok}</div>}
    {form&&<form className="panel form-stack" onSubmit={save}>
      <ImageUpload kind="LOGO" label="Logo perusahaan" value={form.logo_image_id} onChange={id=>set('logo_image_id',id)} hint="PNG/JPG/WEBP, maksimal 8 MB. Latar transparan (PNG) paling bagus."/>
      <div className="form-grid">
        <label>Nama perusahaan *<input required maxLength={120} value={form.name||''} onChange={e=>set('name',e.target.value)}/></label>
        <label>Telepon<input maxLength={60} value={form.phone||''} onChange={e=>set('phone',e.target.value)}/></label>
        <label>Email<input type="email" maxLength={120} value={form.email||''} onChange={e=>set('email',e.target.value)}/></label>
      </div>
      <label>Tagline / layanan<input maxLength={200} value={form.tagline||''} onChange={e=>set('tagline',e.target.value)} placeholder="Screen printing, Sewing, Setting, Adfruk service etc."/></label>
      <label>Alamat<textarea rows={2} maxLength={300} value={form.address||''} onChange={e=>set('address',e.target.value)}/></label>
      <div className="modal-foot"><button className="btn primary" disabled={busy}>{busy?'Menyimpan…':'Simpan profil'}</button></div>
    </form>}
  </div>;
}
