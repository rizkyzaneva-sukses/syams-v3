import React,{useEffect,useState} from 'react';
import {Link,useNavigate,useParams,useLocation} from 'react-router-dom';
import {api} from '../api';

const blankArticle={article_code:'',garment_type:'',qty:'',size_breakdown:'',sample_required:false,production_route:''};
const blank={po_number:'',buyer:'',order_type:'SAMPLE_PRODUCTION',buyer_deadline:'',notes:'',follow_up_note:'',articles:[{...blankArticle}]};

export default function POIntakeFormPage(){
  const {poId}=useParams(),nav=useNavigate(),{state}=useLocation();
  /* Pintu masuk dari PO Inbox (draft order tanpa PO, blueprint REF-DEBY poin 3-4):
     draft order yang diklik Deby sudah mengisi data yang diketahui (buyer, tipe
     order, deadline, article) sehingga Deby tinggal melengkapi nomor PO dan
     dokumen buyer. Hanya dipakai untuk pembuatan baru, tidak menimpa mode edit. */
  const seed=!poId&&state?.draftOrder?state:{};
  const [form,setForm]=useState(seed.prefill?{...blank,...seed.prefill}:blank),[file,setFile]=useState(null),[existing,setExisting]=useState(null),[busy,setBusy]=useState(false),[err,setErr]=useState('');
  useEffect(()=>{if(!poId)return;api(`/cmo/po-intake/${poId}`).then(row=>{setExisting(row);setForm({...blank,...row,articles:row.articles?.length?row.articles:[{...blankArticle}]})}).catch(e=>setErr(e.message))},[poId]);
  const setArticle=(index,key,value)=>setForm(current=>({...current,articles:current.articles.map((article,i)=>i===index?{...article,[key]:value}:article)}));
  async function save(event){
    event.preventDefault();setBusy(true);setErr('');
    const payload={...form,articles:form.articles.map(article=>({...article,qty:Number(article.qty)}))};
    try{
      const row=poId?await api(`/cmo/po-intake/${poId}`,{method:'PATCH',body:JSON.stringify(payload)}):await api('/cmo/po-intake',{method:'POST',body:JSON.stringify(payload)});
      if(file){const data=new FormData();data.append('document',file);await api(`/cmo/po-intake/${row.id}/document`,{method:'POST',body:data});}
      nav('/cmo/po-inbox');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  return <div className="page">
    <div className="page-title"><div><Link to="/cmo/po-inbox" className="back-link">← Kembali ke PO Inbox</Link><h1>{poId?'Edit PO Draft':'Terima PO Baru'}</h1><p>Deby menyiapkan data dan dokumen; Order belum dibuat sampai Cecep menerima PO.</p></div></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {seed.draftOrder&&<div className="notice">PO intake dibuat dari Draft Order <b>{seed.prefill?.order_id||('#'+seed.draftOrder)}</b>. Data buyer, article, dan deadline diisi dari draft order — lengkapi nomor PO dan dokumen buyer, lalu simpan.</div>}
    {existing?.has_document&&<div className="notice">Dokumen saat ini: <b>{existing.document_name}</b>. Unggah file baru hanya jika perlu mengganti dokumen.</div>}
    <form onSubmit={save} className="panel form-stack">
      <div className="form-grid">
        <label>Nomor PO *<input required value={form.po_number||''} onChange={e=>setForm({...form,po_number:e.target.value})}/></label>
        <label>Buyer *<input required value={form.buyer||''} onChange={e=>setForm({...form,buyer:e.target.value})}/></label>
        <label>Tipe order *<select value={form.order_type||''} onChange={e=>setForm({...form,order_type:e.target.value})}><option value="SAMPLE_ONLY">Sample saja</option><option value="SAMPLE_PRODUCTION">Sample + produksi</option><option value="REPEAT_PRODUCTION">Produksi berulang</option></select></label>
        <label>Deadline buyer *<input required type="date" value={form.buyer_deadline||''} onChange={e=>setForm({...form,buyer_deadline:e.target.value})}/></label>
        <label>Dokumen PO *<input type="file" accept="application/pdf,image/png,image/jpeg" required={!poId&&!existing?.has_document} onChange={e=>setFile(e.target.files?.[0]||null)}/><small>PDF, PNG, atau JPG, maksimal 10 MB.</small></label>
      </div>
      <label>Catatan PO<textarea rows={3} value={form.notes||''} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      <label>Catatan follow-up buyer<textarea rows={2} value={form.follow_up_note||''} onChange={e=>setForm({...form,follow_up_note:e.target.value})}/></label>
      <section><div className="panel-head"><h2>Article</h2><button type="button" className="btn" onClick={()=>setForm({...form,articles:[...form.articles,{...blankArticle}]})}>Tambah article</button></div>
        {form.articles.map((article,index)=><div className="form-grid" key={index} style={{padding:'12px 0',borderTop:index?'1px solid #e2e8f0':undefined}}>
          <label>Kode article *<input required value={article.article_code||''} onChange={e=>setArticle(index,'article_code',e.target.value)}/></label>
          <label>Jenis garment<input value={article.garment_type||''} onChange={e=>setArticle(index,'garment_type',e.target.value)}/></label>
          <label>Qty *<input required min="1" type="number" value={article.qty||''} onChange={e=>setArticle(index,'qty',e.target.value)}/></label>
          <label>Size breakdown<input value={article.size_breakdown||''} onChange={e=>setArticle(index,'size_breakdown',e.target.value)} placeholder="S:10, M:20"/></label>
          <label>Rute produksi {form.order_type==='SAMPLE_ONLY'?'(opsional)':'*'}<input required={form.order_type!=='SAMPLE_ONLY'} value={article.production_route||''} onChange={e=>setArticle(index,'production_route',e.target.value)} placeholder="Cutting > Sewing > QC"/></label>
          <label><input type="checkbox" checked={Boolean(article.sample_required)} onChange={e=>setArticle(index,'sample_required',e.target.checked)}/> Perlu sample</label>
          {form.articles.length>1&&<button type="button" className="btn danger" onClick={()=>setForm({...form,articles:form.articles.filter((_,i)=>i!==index)})}>Hapus article</button>}
        </div>)}
      </section>
      <div className="modal-foot"><Link className="btn" to="/cmo/po-inbox">Batal</Link><button className="btn primary" disabled={busy}>{busy?'Menyimpan...':'Simpan PO Draft'}</button></div>
    </form>
  </div>;
}
