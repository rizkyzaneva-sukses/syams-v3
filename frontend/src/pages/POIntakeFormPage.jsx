import React,{useEffect,useState} from 'react';
import {Link,useNavigate,useParams,useLocation} from 'react-router-dom';
import {api} from '../api';
import {currencyOptions, DEFAULT_CURRENCY} from '../currency';
import SizeBreakdownInput from '../components/SizeBreakdownInput';
import ExtraSizeInput from '../components/ExtraSizeInput';
import ImageUpload from '../components/ImageUpload';

const blankArticle={article_code:'',garment_type:'',qty:'',size_breakdown:'',sample_required:false,production_route:'',extra_size:'',design_image_id:null,size_chart_image_id:null,fabric_type:'',print_type:'',embroidery_type:'',material_color:'',packaging:'OPP',label_note:'',zipper_note:'',finishing_note:''};
const blank={po_number:'',buyer:'',order_type:'SAMPLE_PRODUCTION',buyer_deadline:'',notes:'',follow_up_note:'',currency:DEFAULT_CURRENCY,payment_terms:'',articles:[{...blankArticle}]};

export default function POIntakeFormPage(){
  const {poId}=useParams(),nav=useNavigate(),{state}=useLocation();
  /* Pintu masuk dari PO Inbox (draft order tanpa PO, blueprint REF-DEBY poin 3-4):
     draft order yang diklik Deby sudah mengisi data yang diketahui (buyer, tipe
     order, deadline, article) sehingga Deby tinggal melengkapi nomor PO dan
     dokumen buyer. Hanya dipakai untuk pembuatan baru, tidak menimpa mode edit. */
  const seed=!poId&&state?.draftOrder?state:{};
  const [form,setForm]=useState(seed.prefill?{...blank,...seed.prefill}:blank),[file,setFile]=useState(null),[existing,setExisting]=useState(null),[busy,setBusy]=useState(false),[err,setErr]=useState(''),[garments,setGarments]=useState([]);
  useEffect(()=>{if(!poId)return;api(`/cmo/po-intake/${poId}`).then(row=>{setExisting(row);setForm({...blank,...row,articles:row.articles?.length?row.articles:[{...blankArticle}]})}).catch(e=>setErr(e.message))},[poId]);
  useEffect(()=>{api('/control/garment-types?active_only=true').then(setGarments).catch(()=>{})},[]);
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
        <label>Tipe order *<select value={form.order_type||''} onChange={e=>setForm({...form,order_type:e.target.value})}><option value="SAMPLE_ONLY">Sample saja</option><option value="SAMPLE_PRODUCTION">Sample + produksi</option><option value="REPEAT_PRODUCTION">Produksi saja</option></select></label>
        <label>Deadline buyer *<input required type="date" value={form.buyer_deadline||''} onChange={e=>setForm({...form,buyer_deadline:e.target.value})}/></label>
        <label>Currency<select value={(form.currency||DEFAULT_CURRENCY).toUpperCase()} onChange={e=>setForm({...form,currency:e.target.value})}><option value="">Pilih mata uang</option>{currencyOptions(form.currency).map(code=><option key={code} value={code}>{code}</option>)}</select></label>
        <label>Terms pembayaran<input maxLength={255} value={form.payment_terms||''} onChange={e=>setForm({...form,payment_terms:e.target.value})} placeholder="DP 30%, pelunasan sebelum kirim"/></label>
        <label>Dokumen PO *<input type="file" accept="application/pdf,image/png,image/jpeg" required={!poId&&!existing?.has_document} onChange={e=>setFile(e.target.files?.[0]||null)}/><small>PDF, PNG, atau JPG, maksimal 10 MB.</small></label>
      </div>
      <label>Catatan PO<textarea rows={3} value={form.notes||''} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      <label>Catatan follow-up buyer<textarea rows={2} value={form.follow_up_note||''} onChange={e=>setForm({...form,follow_up_note:e.target.value})}/></label>
      <section><div className="panel-head"><h2>Article</h2><button type="button" className="btn" onClick={()=>setForm({...form,articles:[...form.articles,{...blankArticle}]})}>Tambah article</button></div>
        {form.articles.map((article,index)=><div className="form-grid" key={index} style={{padding:'12px 0',borderTop:index?'1px solid #e2e8f0':undefined}}>
          <label>Kode article *<input required value={article.article_code||''} onChange={e=>setArticle(index,'article_code',e.target.value)}/></label>
          <label>Jenis pakaian<select value={article.garment_type||''} onChange={e=>setArticle(index,'garment_type',e.target.value)}><option value="">Pilih jenis pakaian</option>{article.garment_type&&!garments.some(g=>g.name===article.garment_type)&&<option value={article.garment_type}>{article.garment_type}</option>}{garments.map(g=><option key={g.id} value={g.name}>{g.name}</option>)}</select></label>
          <label>Qty *<input required min="1" type="number" value={article.qty||''} onChange={e=>setArticle(index,'qty',e.target.value)}/></label>
          <label>Size breakdown</label>
          <SizeBreakdownInput value={article.size_breakdown} onChange={v=>setArticle(index,'size_breakdown',v)}/>
          <label>Extra size (spare internal untuk reject)</label>
          <ExtraSizeInput value={article.extra_size} onChange={v=>setArticle(index,'extra_size',v)}/>
          <ImageUpload kind="DESIGN" label="Gambar desain / mockup" value={article.design_image_id} onChange={id=>setArticle(index,'design_image_id',id)} hint="Dipakai di SPK. Unggah gambar, bukan link Drive."/>
          <ImageUpload kind="SIZE_CHART" label="Size chart (opsional)" value={article.size_chart_image_id} onChange={id=>setArticle(index,'size_chart_image_id',id)}/>
          <label>Jenis kain<input maxLength={120} value={article.fabric_type||''} onChange={e=>setArticle(index,'fabric_type',e.target.value)} placeholder="mis. 16S CKP"/></label>
          <label>Jenis sablon<input maxLength={120} value={article.print_type||''} onChange={e=>setArticle(index,'print_type',e.target.value)} placeholder="mis. PLASTISOL"/></label>
          <label>Jenis bordir<input maxLength={120} value={article.embroidery_type||''} onChange={e=>setArticle(index,'embroidery_type',e.target.value)} placeholder="- bila tidak ada"/></label>
          <label>Warna material<input maxLength={120} value={article.material_color||''} onChange={e=>setArticle(index,'material_color',e.target.value)} placeholder="mis. BLACK"/></label>
          <label>Packaging<select value={article.packaging||''} onChange={e=>setArticle(index,'packaging',e.target.value)}><option value="OPP">OPP</option><option value="ZIPLOCK">ZIPLOCK</option><option value="">Lainnya / tidak ada</option></select></label>
          <label>Label / hantag<input maxLength={200} value={article.label_note||''} onChange={e=>setArticle(index,'label_note',e.target.value)} placeholder="mis. LABEL LEHER"/></label>
          <label>Zipper / headzip<input maxLength={200} value={article.zipper_note||''} onChange={e=>setArticle(index,'zipper_note',e.target.value)}/></label>
          <label>Finishing lainnya<input maxLength={300} value={article.finishing_note||''} onChange={e=>setArticle(index,'finishing_note',e.target.value)}/></label>
          <label><input type="checkbox" checked={Boolean(article.sample_required)} onChange={e=>setArticle(index,'sample_required',e.target.checked)}/> Perlu sample</label>
          {form.articles.length>1&&<button type="button" className="btn danger" onClick={()=>setForm({...form,articles:form.articles.filter((_,i)=>i!==index)})}>Hapus article</button>}
        </div>)}
      </section>
      <div className="modal-foot"><Link className="btn" to="/cmo/po-inbox">Batal</Link><button className="btn primary" disabled={busy}>{busy?'Menyimpan...':'Simpan PO Draft'}</button></div>
    </form>
  </div>;
}
