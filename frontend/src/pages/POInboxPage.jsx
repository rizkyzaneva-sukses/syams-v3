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

export default function POInboxPage(){
  const role=useRole(),canPrepare=role==='CMO_SUPPORT',canReview=role==='CMO_MANAGER';
  const [rows,setRows]=useState([]),[q,setQ]=useState(''),[err,setErr]=useState(''),[busy,setBusy]=useState(false),[review,setReview]=useState(null);
  async function load(){try{setRows(await api('/cmo/po-intake'));setErr('')}catch(e){setErr(e.message)}}
  useEffect(()=>{load()},[]);
  async function action(id,step){setBusy(true);setErr('');try{await api(`/cmo/po-intake/${id}/${step}`,{method:'POST'});await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function decide(e){e.preventDefault();setBusy(true);setErr('');try{await api(`/cmo/po-intake/${review.id}/review`,{method:'POST',body:JSON.stringify({action:review.action,note:review.note})});setReview(null);await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function download(row){try{const blob=await api(`/cmo/po-intake/${row.id}/document`,{responseType:'blob'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=row.document_name||'po-document';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){setErr(e.message)}}
  const shown=rows.filter(row=>`${row.po_number||''} ${row.buyer||''} ${row.status} ${row.order_id||''} ${row.customer_id??''}`.toLowerCase().includes(q.toLowerCase()));
  return <div className="page">
    <div className="page-title"><div><h1>PO Inbox / Register</h1><p>Deby memeriksa kelengkapan PO dan mengirim draft. Cecep menerima atau menolak; Order aktif hanya setelah diterima.</p></div>{canPrepare&&<Link to="/cmo/po-inbox/new" className="btn primary">Terima PO Baru</Link>}</div>
    {err&&!review&&<div role="alert" className="notice danger">{err}</div>}
    <input aria-label="Cari PO" placeholder="Cari nomor PO, buyer, status, atau Order ID" value={q} onChange={e=>setQ(e.target.value)}/>
    <div className="table-scroll"><table><thead><tr>
      <th>PO ID</th><th>Buyer ID</th><th>Nomor / Tanggal PO</th><th>Dokumen buyer</th><th>Order type</th>
      <th>Currency / Terms</th><th>Jumlah article</th><th>Kelengkapan</th><th>Missing items</th>
      <th>Received at</th><th>Next action</th><th>Due</th><th>Review Cecep</th><th>Aksi</th>
    </tr></thead><tbody>
      {shown.map(row=>{
        const queue=poQueue(row),state=completeStatus(row.missing_items,row.status);
        const totals=(row.articles||[]).map(article=>articleQty(article)).reduce((sum,value)=>sum+value,0);
        return <tr key={row.id}>
          <td><b>PO-{row.id}</b>{row.order_id&&<><br/><Link to={'/orders/'+row.order_id}>{row.order_id}</Link></>}</td>
          <td>{row.buyer||'—'}{row.customer_id!=null&&<><br/><small>Customer ID: {row.customer_id}</small></>}</td>
          <td>{row.po_number||'—'}<br/><small>Deadline buyer {row.buyer_deadline||'belum diisi'}</small></td>
          <td>{row.has_document?<button className="btn sm" onClick={()=>download(row)}>{row.document_name||'Unduh PO'}</button>:'Belum diunggah'}</td>
          <td>{row.order_type?<span className="badge gray">{ORDER_TYPE_LABELS[row.order_type]||row.order_type.replace(/_/g,' ')}</span>:'—'}</td>
          <td><span className="badge gray">—</span><br/><small>Belum ada di master</small></td>
          <td>{(row.articles||[]).length} article<br/><small>{totals} pcs</small>{sizeSummary(row.articles)&&<><br/><small>Size {sizeSummary(row.articles)}</small></>}</td>
          <td><span className={'badge '+state.tone}>{state.label}</span></td>
          <td>{row.missing_items?.length?<span className="badge amber">{row.missing_items.join(', ')}</span>:<span className="badge green">Tidak ada</span>}
            {row.follow_up_note&&<p><small>Follow up: {row.follow_up_note}</small></p>}{row.review_note&&<p><small>Catatan Cecep: {row.review_note}</small></p>}</td>
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
      {!shown.length&&<tr><td colSpan={14} className="empty">Belum ada PO terdaftar.</td></tr>}
    </tbody></table></div>
    {review&&<FormModal title={review.action==='ACCEPT'?'Terima PO dan Aktifkan Order':'Tolak PO'} error={err} busy={busy} onClose={()=>{setReview(null);setErr('')}} onSubmit={decide}><p>{review.action==='ACCEPT'?'Order ID baru akan dibuat dari draft PO ini.':'PO ditolak dan dokumennya tetap tersimpan.'}</p><label>Catatan review<textarea required={review.action==='REJECT'} value={review.note} onChange={e=>setReview({...review,note:e.target.value})}/></label></FormModal>}
  </div>;
}
