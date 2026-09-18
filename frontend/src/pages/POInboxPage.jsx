import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';

const editable=new Set(['DRAFT','NEEDS_INFO','READY']);

export default function POInboxPage(){
  const role=useRole(),canPrepare=role==='CMO_SUPPORT',canReview=role==='CMO_MANAGER';
  const [rows,setRows]=useState([]),[q,setQ]=useState(''),[err,setErr]=useState(''),[busy,setBusy]=useState(false),[review,setReview]=useState(null);
  async function load(){try{setRows(await api('/cmo/po-intake'));setErr('')}catch(e){setErr(e.message)}}
  useEffect(()=>{load()},[]);
  async function action(id,step){setBusy(true);setErr('');try{await api(`/cmo/po-intake/${id}/${step}`,{method:'POST'});await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function decide(e){e.preventDefault();setBusy(true);setErr('');try{await api(`/cmo/po-intake/${review.id}/review`,{method:'POST',body:JSON.stringify({action:review.action,note:review.note})});setReview(null);await load()}catch(e){setErr(e.message)}finally{setBusy(false)}}
  async function download(row){try{const blob=await api(`/cmo/po-intake/${row.id}/document`,{responseType:'blob'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=row.document_name||'po-document';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){setErr(e.message)}}
  const shown=rows.filter(row=>`${row.po_number||''} ${row.buyer||''} ${row.status} ${row.order_id||''}`.toLowerCase().includes(q.toLowerCase()));
  return <div className="page">
    <div className="page-title"><div><h1>PO Inbox / Register</h1><p>Deby memeriksa kelengkapan PO dan mengirim draft. Cecep menerima atau menolak; Order aktif hanya setelah diterima.</p></div>{canPrepare&&<Link to="/cmo/po-inbox/new" className="btn primary">Terima PO Baru</Link>}</div>
    {err&&!review&&<div role="alert" className="notice danger">{err}</div>}
    <input aria-label="Cari PO" placeholder="Cari nomor PO, buyer, status, atau Order ID" value={q} onChange={e=>setQ(e.target.value)}/>
    <div className="table-scroll"><table><thead><tr><th>PO</th><th>Buyer</th><th>Status</th><th>Kelengkapan / Follow up</th><th>Dokumen</th><th>Order</th><th>Aksi</th></tr></thead><tbody>
      {shown.map(row=><tr key={row.id}>
        <td><b>{row.po_number||`Draft #${row.id}`}</b><br/><small>Diterima {row.received_at}</small></td>
        <td>{row.buyer||'—'}</td>
        <td><span className={'badge '+(row.status==='ACCEPTED'?'green':row.status==='REJECTED'?'red':row.status==='READY'?'blue':'amber')}>{row.status}</span></td>
        <td>{row.missing_items?.length?<span>{row.missing_items.join(', ')}</span>:<span>Lengkap</span>}{row.follow_up_note&&<p><small>Follow up: {row.follow_up_note}</small></p>}{row.review_note&&<p><small>Review: {row.review_note}</small></p>}</td>
        <td>{row.has_document?<button className="btn sm" onClick={()=>download(row)}>{row.document_name||'Unduh PO'}</button>:'Belum diunggah'}</td>
        <td>{row.order_id?<Link to={'/orders/'+row.order_id}>{row.order_id}</Link>:'—'}</td>
        <td className="td-action">
          {canPrepare&&editable.has(row.status)&&<><Link className="btn sm" to={`/cmo/po-inbox/${row.id}/edit`}>Edit / Follow up</Link><button className="btn sm" disabled={busy} onClick={()=>action(row.id,'check')}>Cek Kelengkapan</button>{row.status==='READY'&&<button className="btn sm primary" disabled={busy} onClick={()=>action(row.id,'submit')}>Kirim ke Cecep</button>}</>}
          {canReview&&row.status==='SUBMITTED'&&<><button className="btn sm primary" onClick={()=>setReview({id:row.id,action:'ACCEPT',note:''})}>Terima & Aktifkan Order</button><button className="btn sm" onClick={()=>setReview({id:row.id,action:'REJECT',note:''})}>Tolak</button></>}
        </td>
      </tr>)}
      {!shown.length&&<tr><td colSpan={7} className="empty">Belum ada PO terdaftar.</td></tr>}
    </tbody></table></div>
    {review&&<FormModal title={review.action==='ACCEPT'?'Terima PO dan Aktifkan Order':'Tolak PO'} error={err} busy={busy} onClose={()=>{setReview(null);setErr('')}} onSubmit={decide}><p>{review.action==='ACCEPT'?'Order ID baru akan dibuat dari draft PO ini.':'PO ditolak dan dokumennya tetap tersimpan.'}</p><label>Catatan review<textarea required={review.action==='REJECT'} value={review.note} onChange={e=>setReview({...review,note:e.target.value})}/></label></FormModal>}
  </div>;
}
