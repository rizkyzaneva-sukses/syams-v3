import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';

const editable=new Set(['DRAFT','NEEDS_INFO','READY']);

/* Istilah blueprint (poin 4) -> label Indonesia yang dipakai di layar. */
export const ORDER_TYPE_LABELS={SAMPLE_ONLY:'Sample saja',SAMPLE_PRODUCTION:'Sample + produksi',REPEAT_PRODUCTION:'Produksi berulang'};

/* Rincian artikel PO diambil dari articles_json. Urutan kandidat field dipakai
   supaya tetap terbaca kalau draft lama hanya menyimpan jumlah per ukuran. */
export function articleQty(article){
  if(article.qty!=null&&article.qty!=='')return Number(article.qty)||0;
  return Object.values(article.size_breakdown||{}).reduce((sum,value)=>sum+(Number(value)||0),0);
}
export function sizeSummary(articles){
  const sizes=new Set();
  for(const article of articles||[]){
    for(const match of String(article.size_breakdown||'').match(/\b\d{2}\b/g)||[])sizes.add(match);
    if(article.size_breakdown&&typeof article.size_breakdown==='object')Object.keys(article.size_breakdown).forEach(size=>sizes.add(size));
  }
  return [...sizes].sort().join(', ');
}
export function completeStatus(missing,status){
  const list=missing||[];
  if(list.length)return {label:`Kurang ${list.length} item`,tone:'amber'};
  return {label:status==='READY'?'Lengkap — siap dikirim':'Lengkap',tone:'green'};
}

/* Next action, owner, due dan status review Cecep per status PO (satu sumber
   kebenaran, dipakai tabel). Alur backend: DRAFT -> READY -> SUBMITTED ->
   ACCEPTED/REJECTED; NEEDS_INFO dikembalikan Cecep ke Deby. */
export function poQueue(row){
  const due=row.buyer_deadline||null;
  const waiting=row.status==='SUBMITTED';
  const label=status=>status==='ACCEPTED'?'Diterima':status==='REJECTED'?'Ditolak':'Menunggu review';
  if(row.status==='DRAFT'||row.status==='NEEDS_INFO')return {owner:'CMO_SUPPORT (Deby)',action:'Lengkapi data, dokumen dan koreksi dari Cecep',due,review:'Belum diajukan',reviewTone:'gray',waiting};
  if(row.status==='READY')return {owner:'CMO_SUPPORT (Deby)',action:'Kirim draft PO ke Cecep',due,review:'Siap direview Cecep',reviewTone:'blue',waiting};
  if(waiting)return {owner:'CMO_MANAGER (Cecep)',action:'Cecep mereview: terima PO dan aktifkan Order',due,review:'Sedang direview',reviewTone:'amber',waiting};
  return {owner:'CMO_MANAGER (Cecep)',action:row.status==='ACCEPTED'?'Order aktif —lanjut ke alur order':'PO ditolak — minta revisi dokumen buyer',due:row.status==='ACCEPTED'?null:due,review:label(row.status),reviewTone:row.status==='ACCEPTED'?'green':row.status==='REJECTED'?'red':'gray',waiting};
}

/* Reason perbaikan (blueprint poin 4: "reason perbaikan" pada antrean Deby).
   Dirakit HANYA dari field yang benar-benar ada di baris PO supaya Deby tahu apa
   yang harus dibereskan sebelum dikirim ke Cecep:
   - review_note dari penolakan/koreksi Cecep (paling menentukan, tampil pertama);
   - missing_items kalau isinya sudah menandai kekurangan tapi baris masih
     berstatus DRAFT (hasil /check belum dijalankan ulang setelah diperbaiki);
   - catatan follow-up buyer (follow_up_note) yang tersimpan di draft;
   - dokumen PO belum diunggah padahal missing_items kosong, mis. pemeriksaan
     terakhir dilakukan sebelum dokumen masuk tanpa /check ulang sehingga status
     masih DRAFT — Deby tahu yang kurang adalah dokumen buyer;
   - kalau semuanya bersih, kembalikan [] dan pemanggil menampilkan 'Tidak ada'.
   Tidak ada teks yang dikarang di sini; semuanya berasal dari data server. */
export function fixReasons(row,extra){
  const reasons=[];
  const note=typeof row.review_note==='string'?row.review_note.trim():'';
  const missing=Array.isArray(row.missing_items)?row.missing_items.filter(Boolean):[];
  const followUp=typeof row.follow_up_note==='string'?row.follow_up_note.trim():'';
  const openStatus=row.status==='DRAFT'||row.status==='NEEDS_INFO'||row.status==='READY';
  if(note)reasons.push(row.status==='REJECTED'?`Ditolak Cecep: ${note}`:`Koreksi Cecep: ${note}`);
  if(openStatus&&missing.length)reasons.push('Kurang: '+missing.join(', '));
  if(openStatus&&followUp)reasons.push(`Follow-up buyer: ${followUp}`);
  if(openStatus&&!row.has_document&&!missing.length)reasons.push('Dokumen PO (PDF/JPG/PNG) belum diunggah — Deby perlu unggah dokumen buyer.');
  return [...reasons,...(extra||[]).filter(Boolean)];
}

/* Pintu masuk 'PO Masuk' dari Draft Order (blueprint poin 3 + 4): order yang
   sudah ada dan masih di tahap ORDER, tapi belum punya PO intake tertaut.
   Pencocokan tautan memakai aturan yang sama dengan Draft Order List:
   order_fk === order.id atau order_id === order.order_id. */
export function draftOrdersWithoutPo(orders,intakes){
  const po=Array.isArray(intakes)?intakes:[];
  return (orders||[]).filter(order=>order.flow_step==='ORDER')
    .filter(order=>!po.some(row=>row.order_fk===order.id||(row.order_id&&row.order_id===order.order_id)));
}

export function draftOrderPoPrefill(order){
  const list=order.articles||[];
  const first=list[0]||{};
  return {
    buyer:order.buyer||'',
    order_type:order.order_type||'SAMPLE_PRODUCTION',
    customer_id:order.customer_id??null,
    buyer_deadline:order.buyer_deadline||'',
    notes:order.notes||'',
    articles:list.length&&list.every(article=>article.article_code&&article.qty!=null)
      ?list.map(article=>({article_code:article.article_code,garment_type:article.garment_type||'',id:article.id,production_route:article.production_route||'',qty:article.qty,sample_required:Boolean(article.sample_required),size_breakdown:article.size_breakdown||''}))
      : first.article_code?[{article_code:first.article_code,garment_type:first.garment_type||'',id:first.id,production_route:first.production_route||'',qty:first.qty!=null?first.qty:'',sample_required:Boolean(first.sample_required),size_breakdown:typeof first.size_breakdown==='string'?first.size_breakdown:''}]
      : null,
  };
}

export default function POInboxPage(){
  const role=useRole(),canPrepare=role==='CMO_SUPPORT',canReview=role==='CMO_MANAGER';
  const [rows,setRows]=useState([]),[drafts,setDrafts]=useState([]),[draftErr,setDraftErr]=useState(''),[q,setQ]=useState(''),[err,setErr]=useState(''),[busy,setBusy]=useState(false),[review,setReview]=useState(null);
  async function load(){
    try{setRows(await api('/cmo/po-intake'));setErr('')}catch(e){setErr(e.message)}
    /* Daftar order draft untuk pintu masuk PO Masuk. Order yang tidak boleh
       dibaca peran ini cukup dilewati, jangan mematikan seluruh halaman. */
    try{setDrafts(await api('/orders'));setDraftErr('')}catch(e){setDraftErr(e.message)}
  }
  useEffect(()=>{load()},[]);
  async function action(id,step){setBusy(true);setErr('');try{await api(`/cmo/po-intake/${id}/${step}`,{method:'POST'});await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function decide(e){e.preventDefault();setBusy(true);setErr('');try{await api(`/cmo/po-intake/${review.id}/review`,{method:'POST',body:JSON.stringify({action:review.action,note:review.note})});setReview(null);await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function download(row){try{const blob=await api(`/cmo/po-intake/${row.id}/document`,{responseType:'blob'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=row.document_name||'po-document';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){setErr(e.message)}}
  /* PO MASUK (blueprint poin 4 + poin 3): kolom PO ID, Buyer ID, nomor/tanggal
     PO, buyer document, order type, currency/terms, jumlah article,
     completeness, missing items, received_at, next action, due, review Cecep.
     Setiap baris membuka Buyer/Order/Article terkait (poin 3). */
  const shown=rows.filter(row=>`${row.po_number||''} ${row.buyer||''} ${row.status} ${row.order_id||''} ${row.customer_id??''} ${(row.articles||[]).map(a=>a.article_code).join(' ')}`.toLowerCase().includes(q.toLowerCase()));
  const orderDrafts=draftOrdersWithoutPo(drafts,rows);
  const shownDrafts=orderDrafts.filter(order=>`${order.order_id||''} ${order.buyer||''} ${order.order_type||''} ${order.customer_id??''} ${(order.articles||[]).map(a=>a.article_code).join(' ')}`.toLowerCase().includes(q.toLowerCase()));
  return <div className="page">
    <div className="page-title"><div><h1>PO Inbox / Register</h1><p>Deby memeriksa kelengkapan PO dan mengirim draft. Cecep menerima atau menolak; Order aktif hanya setelah diterima.</p></div>{canPrepare&&<Link to="/cmo/po-inbox/new" className="btn primary">Terima PO Baru</Link>}</div>
    {err&&!review&&<div role="alert" className="notice danger">{err}</div>}
    <input aria-label="Cari PO" placeholder="Cari nomor PO, buyer, artikel, status, Order ID, atau Draft Order" value={q} onChange={e=>setQ(e.target.value)}/>
    <div className="table-scroll"><table><thead><tr>
      <th>PO ID</th><th>Buyer ID</th><th>Nomor / Tanggal PO</th><th>Article ID</th><th>Dokumen buyer</th><th>Order type</th>
      <th>Currency / Terms</th><th>Jumlah article</th><th>Kelengkapan</th><th>Missing items</th>
      <th>Reason perbaikan</th><th>Received at</th><th>Next action</th><th>Due</th><th>Review Cecep</th><th>Aksi</th>
    </tr></thead><tbody>
      {shown.map(row=>{
        const queue=poQueue(row),state=completeStatus(row.missing_items,row.status);
        const totals=(row.articles||[]).map(article=>articleQty(article)).reduce((sum,value)=>sum+value,0);
        const fixes=fixReasons(row);
        return <tr key={row.id}>
          <td><b>PO-{row.id}</b>{row.order_id&&<><br/><Link to={'/orders/'+row.order_id}>{row.order_id}</Link></>}</td>
          <td>{row.buyer||'—'}{row.customer_id!=null&&<><br/><small>Customer ID: {row.customer_id}</small></>}</td>
          <td>{row.po_number||'—'}<br/><small>Deadline buyer {row.buyer_deadline||'belum diisi'}</small></td>
          <td>{(row.articles||[]).length?<ul style={{margin:0,paddingLeft:16}}>{row.articles.map((article,index)=><li key={index}>{article.article_code||'(kode kosong)'} · {articleQty(article)} pcs{article.sample_required?<small> · sample</small>:null}</li>)}</ul>:'—'}</td>
          <td>{row.has_document?<button className="btn sm" onClick={()=>download(row)}>{row.document_name||'Unduh PO'}</button>:'Belum diunggah'}</td>
          <td>{row.order_type?<span className="badge gray">{ORDER_TYPE_LABELS[row.order_type]||row.order_type.replace(/_/g,' ')}</span>:'—'}</td>
          <td><span className="badge gray">{row.currency||'—'}</span><br/><small>{row.payment_terms||'Terms belum diisi'}</small></td>
          <td>{(row.articles||[]).length} article<br/><small>{totals} pcs</small>{sizeSummary(row.articles)&&<><br/><small>Size {sizeSummary(row.articles)}</small></>}</td>
          <td><span className={'badge '+state.tone}>{state.label}</span></td>
          <td>{row.missing_items?.length?<span className="badge amber">{row.missing_items.join(', ')}</span>:<span className="badge green">Tidak ada</span>}
            {row.follow_up_note&&<p><small>Follow up: {row.follow_up_note}</small></p>}{row.review_note&&<p><small>Catatan Cecep: {row.review_note}</small></p>}</td>
          <td>{fixes.length?<span className="badge amber">{fixes.join(' · ')}</span>:<span className="badge green">Tidak ada</span>}</td>
          <td>{row.received_at||'—'}<br/><small>Diinput Deby · {row.created_at||'—'}</small></td>
          <td>{queue.action}</td>
          <td>{queue.due?queue.due:'—'}</td>
          <td><span className={'badge '+queue.reviewTone}>{queue.review}</span>{row.reviewed_at&&<><br/><small>{row.reviewed_at}</small></>}</td>
          <td className="td-action">
            {canPrepare&&editable.has(row.status)&&<><Link className="btn sm" to={`/cmo/po-inbox/${row.id}/edit`}>Edit / Follow up</Link><button className="btn sm" disabled={busy} onClick={()=>action(row.id,'check')}>Cek Kelengkapan</button>{row.status==='READY'&&<button className="btn sm primary" disabled={busy} onClick={()=>action(row.id,'submit')}>Kirim ke Cecep</button>}</>}
            {canReview&&row.status==='SUBMITTED'&&<><button className="btn sm primary" onClick={()=>setReview({id:row.id,action:'ACCEPT',note:''})}>Terima &amp; Aktifkan Order</button><button className="btn sm" onClick={()=>setReview({id:row.id,action:'REJECT',note:''})}>Tolak</button></>}
          </td>
        </tr>;
      })}
      {!shown.length&&<tr><td colSpan={16} className="empty">Belum ada PO terdaftar.</td></tr>}
    </tbody></table></div>
    {/* Pintu masuk 'PO Masuk' dari Draft Order (blueprint poin 3 & 4): order yang
        sudah ada di sistem tapi belum punya PO intake tertaut. Keputusan accept/
        reject dan activate Order tetap milik Cecep di tabel di atas; di sini Deby
        hanya menyiapkan PO intake-nya. */}
    {draftErr&&<div role="alert" className="notice danger">Daftar order draft tidak bisa dimuat: {draftErr}</div>}
    {canPrepare&&<section className="panel">
      <div className="panel-head"><h2>Order draft tanpa PO — pintu masuk PO Masuk</h2></div>
      <p>Order yang sudah dibuat tapi belum punya PO intake tertaut ({shownDrafts.length} order). Buat PO intake-nya supaya Deby bisa cek kelengkapan dan mengirimkannya ke Cecep untuk diaktifkan.</p>
      <div className="table-scroll"><table><thead><tr>
        <th>Draft Order ID</th><th>Buyer ID</th><th>Draft Order type</th><th>Article ID</th><th>Jumlah article</th><th>Kelengkapan draft</th><th>Deadline buyer</th><th>Next action</th><th>Aksi</th>
      </tr></thead><tbody>
        {shownDrafts.map(order=>{
          const prefill=draftOrderPoPrefill(order);
          const ready=Boolean(prefill.articles);
          const totals=(order.articles||[]).reduce((sum,article)=>sum+Number(article.qty||0),0);
          return <tr key={order.id}>
            <td><Link to={'/orders/'+order.order_id}><b>{order.order_id}</b></Link></td>
            <td>{order.buyer||'—'}{order.customer_id!=null&&<><br/><small>Customer ID: {order.customer_id}</small></>}</td>
            <td>{order.order_type?<span className="badge gray">{ORDER_TYPE_LABELS[order.order_type]||order.order_type.replace(/_/g,' ')}</span>:'—'}</td>
            <td>{(order.articles||[]).length?<ul style={{margin:0,paddingLeft:16}}>{order.articles.map(article=><li key={article.id}>{article.article_code||'(kode kosong)'} · {article.qty} pcs</li>)}</ul>:'Belum ada article'}</td>
            <td>{(order.articles||[]).length} article<br/><small>{totals} pcs</small></td>
            <td>{ready?<span className="badge blue">Siap dibuatkan PO intake</span>:<span className="badge amber">Article/kode belum lengkap — lengkapi dulu di Draft Order</span>}</td>
            <td>{order.buyer_deadline||'—'}</td>
            <td>Buat PO intake, unggah dokumen buyer, lalu Cek Kelengkapan dan kirim ke Cecep</td>
            <td className="td-action">{ready?<Link className="btn sm primary" to="/cmo/po-inbox/new" state={{draftOrder:order.id,prefill}}>Buat PO Masuk</Link>:<Link className="btn sm" to={'/orders/'+order.order_id}>Lengkapi draft order</Link>}</td>
          </tr>;
        })}
        {!shownDrafts.length&&<tr><td colSpan={9} className="empty">Tidak ada order draft tanpa PO{q?` untuk pencarian “${q}”`:''}. Semua order yang ada sudah punya PO intake tertaut.</td></tr>}
      </tbody></table></div>
    </section>}
    {review&&<FormModal title={review.action==='ACCEPT'?'Terima PO dan Aktifkan Order':'Tolak PO'} error={err} busy={busy} onClose={()=>{setReview(null);setErr('')}} onSubmit={decide}><p>{review.action==='ACCEPT'?'Order ID baru akan dibuat dari draft PO ini.':'PO ditolak dan dokumennya tetap tersimpan.'}</p><label>Catatan review<textarea required={review.action==='REJECT'} value={review.note} onChange={e=>setReview({...review,note:e.target.value})}/></label></FormModal>}
  </div>;
}
