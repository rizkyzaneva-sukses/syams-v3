import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import FormModal from '../components/FormModal';
import {matchesSearch,statusTone} from '../business';
import {slaBadge,taskId,quotationHandoff} from '../queue';

const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID');
const blank={quotation_no:'',order_fk:'',status:'DRAFT',valid_until:'',notes:'',payment_plan:'',currency:'IDR',pricing_lines:[]};
function rowsFor(order,quote){
 let existing=[];
 try{existing=JSON.parse(quote?.pricing_breakdown||'[]')}catch{}
 return (order?.articles||[]).map(a=>({article_id:a.id,article_code:a.article_code,qty:a.qty,
   unit_price:existing.find(x=>x.article_id===a.id)?.unit_price||'',
   unit_hpp:existing.find(x=>x.article_id===a.id)?.unit_hpp||''}));
}
/* Blueprint poin 7: quotation belum lengkap kalau harga tiap article belum
   diisi. Dipakai untuk kolom kelengkapan tanpa memanggil endpoint baru. */
export function quotationComplete(quote){
  let lines=[];try{lines=JSON.parse(quote?.pricing_breakdown||'[]')}catch{}
  return Array.isArray(lines)&&lines.length>0&&lines.every(l=>Number(l.unit_price)>0&&l.unit_hpp!=null&&l.unit_hpp!=='');
}
/* Next action, owner Deby/Cecep, dan buyer response per status quotation. */
export function quotationQueue(quote){
  const yyyy_mm_dd=new Date().toISOString().slice(0,10),expired=Boolean(quote.valid_until&&quote.valid_until<yyyy_mm_dd);
  if(quote.status==='DRAFT'&&quote.approved_by_id)return {next:'Terbitkan penawaran dan catat pengiriman',owner:'CMO_SUPPORT (Deby)',response:'Belum dikirim — harga siap'};
  if(quote.status==='DRAFT')return {next:'Hitung harga per article, kirim ke CFO',owner:'CMO_SUPPORT (Deby)',response:'Belum dikirim'};
  if(quote.status==='SENT')return {next:expired?'Perbarui masa berlaku lalu kirim ulang':'Tunggu balasan buyer, catat hasilnya',owner:'CMO_SUPPORT (Deby)',response:expired?'Kedaluwarsa tanpa balasan':'Sudah dikirim — menunggu buyer'};
  if(quote.status==='APPROVED')return {next:'Kirim penawaran resmi ke buyer, catat balasan',owner:'CMO_SUPPORT (Deby)',response:'Disetujui CFO — belum dikirim ke buyer'};
  return {next:'Perbaiki harga dan kirim ulang',owner:'CMO_SUPPORT (Deby)',response:'Ditolak CFO'};
}

/* Status handoff per-order quotation (blueprint REF-DEBY poin 7): kontraknya
   ada di `../queue.js` (quotationHandoff) — satu kosakata dengan antrean PO
   Inbox dan Draft Order. */

export default function QuotationPage(){
 const role=useRole(),isCMO=['CMO_MANAGER','CMO_SUPPORT'].includes(role),manager=role==='CMO_MANAGER',isCFO=role==='CFO_MANAGER',isCEO=role==='CEO';
 const [list,setList]=useState([]),[orders,setOrders]=useState([]),[policy,setPolicy]=useState(null),[form,setForm]=useState(null),[decision,setDecision]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[query,setQuery]=useState('');
 async function load(){try{const [quotes,allOrders]=await Promise.all([api('/cmo/quotations'),api('/orders')]);setList(quotes);setOrders(allOrders);setError('');if(['CEO','CFO_MANAGER','CMO_MANAGER'].includes(role)){try{setPolicy(await api('/config/business-policy'))}catch{setPolicy(null)}}}catch(e){setError(e.message)}}
 useEffect(()=>{load()},[role]);
 function openQuote(q){const order=orders.find(o=>o.id===q.order_fk);setError('');setForm({...blank,...q,pricing_lines:rowsFor(order,q)});}
 function selectOrder(id){const order=orders.find(o=>o.id===Number(id));setForm(f=>({...f,order_fk:id,pricing_lines:rowsFor(order)}));}
 function updateLine(index,key,value){setForm(f=>({...f,pricing_lines:f.pricing_lines.map((line,i)=>i===index?{...line,[key]:value}:line)}));}
 async function save(e){e.preventDefault();setBusy(true);setError('');try{
   if(isCFO){await api(`/cmo/quotations/${form.id}`,{method:'PATCH',body:JSON.stringify({status:form.status,approval_reason:form.approval_reason})})}
   else {const payload={status:form.status,valid_until:form.valid_until,notes:form.notes,payment_plan:form.payment_plan,currency:form.currency||'IDR',
     pricing_lines:form.pricing_lines.map(({article_id,unit_price,unit_hpp})=>({article_id,unit_price:Number(unit_price),unit_hpp:Number(unit_hpp)}))};
     if(!form.id)Object.assign(payload,{quotation_no:form.quotation_no,order_fk:Number(form.order_fk)});
     await api('/cmo/quotations'+(form.id?'/'+form.id:''),{method:form.id?'PATCH':'POST',body:JSON.stringify(payload)})}
   setForm(null);await load();
 }catch(x){setError(x.message)}finally{setBusy(false)}}
 async function approveLimit(e){e.preventDefault();setBusy(true);setError('');try{await api(`/ceo/quotations/${decision.id}/approve-limit`,{method:'POST',body:JSON.stringify({reason:decision.reason})});setDecision(null);await load()}catch(x){setError(x.message)}finally{setBusy(false)}}
 async function remove(id){if(!confirm('Hapus quotation ini?'))return;try{await api(`/cmo/quotations/${id}`,{method:'DELETE'});await load()}catch(e){setError(e.message)}}
 const selected=orders.find(o=>o.id===Number(form?.order_fk));
 const total=form?.pricing_lines.reduce((n,line)=>n+line.qty*Number(line.unit_price||0),0)||0;
 const hpp=form?.pricing_lines.reduce((n,line)=>n+line.qty*Number(line.unit_hpp||0),0)||0;
 return <div className="page"><div className="page-title"><div><h1>Pricing & Quotation</h1><p>Harga, HPP dan margin dihitung per artikel sebelum approval.</p></div>{isCMO&&<button className="btn primary" onClick={()=>openQuote(blank)}>Tambah Quotation</button>}</div>
 {error&&!form&&!decision&&<div className="notice danger" role="alert">{error}</div>}{!policy&&['CEO','CFO_MANAGER','CMO_MANAGER'].includes(role)&&<div className="notice danger">Kebijakan pricing dan DP belum diatur CEO; approval akan tertahan.</div>}
 <input aria-label="Cari quotation" placeholder="Cari nomor quotation" value={query} onChange={e=>setQuery(e.target.value)}/>
 <div className="table-scroll"><table><thead><tr><th>Task ID</th><th>Quotation ID / version</th><th>Buyer / Opportunity</th><th>Draft Order / Order</th><th>Article ID</th><th>Currency</th><th>Pricing output CFO</th><th>Proposed price</th><th>Validity / SLA internal</th><th>Status Prepare Deby</th><th>Approval / Send Cecep</th><th>Data / bukti yang kurang</th><th>Source / evidence</th><th>Sent at</th><th>Buyer response</th><th>Handoff</th><th>Updated at</th><th>Aksi</th></tr></thead><tbody>{list.filter(q=>matchesSearch(q,query,['quotation_no','notes'])).map(q=>{
  const order=orders.find(o=>o.id===q.order_fk),queue=quotationQueue(q),complete=quotationComplete(q);
  let lines=[];try{lines=JSON.parse(q.pricing_breakdown||'[]')}catch{}
  const missingQuote=[];
  if(!lines.length)missingQuote.push('Rincian harga per article');
  else if(!complete)missingQuote.push('Harga/HPP belum lengkap di semua article');
  if(!q.payment_plan)missingQuote.push('Payment plan');
  if(!q.valid_until)missingQuote.push('Masa berlaku');
  if(!order)missingQuote.push('Order tertaut');
  if(order&&!q.approved_by_id&&q.status==='DRAFT')missingQuote.push('Keputusan CFO');
  const tid=q.task_id||taskId('QUOTATION',q.quotation_no||q.id),sla=slaBadge(q.valid_until),handoff=quotationHandoff(q);
  return <tr key={q.id}>
  <td><b>{tid}</b></td>
  <td><b>{q.quotation_no}</b><br/><small>v{q.id} · dibuat {q.created_at||'—'}</small></td>
  <td>{order?.buyer||'—'}<br/><small>{order?.order_type?order.order_type.replace(/_/g,' '):'Order belum tertaut'} · {order?.buyer_deadline?'deadline '+order.buyer_deadline:'deadline belum diisi'}</small></td>
  <td>{order?<><Link to={'/orders/'+order.order_id}><b>{order.order_id}</b></Link><br/><small>Draft Order ID {order.id}</small></>:<small>Order belum tertaut</small>}</td>
  <td>{lines.length?lines.map(line=><div key={line.article_id}>{line.article_code||('Article '+line.article_id)} <small>· {line.qty} pcs</small></div>):'—'}</td>
  <td><span className="badge gray">{q.currency||'IDR'}</span><br/><small>Mata uang penawaran</small></td>
 <td><span className={'badge '+(complete?'green':'amber')}>{complete?'Harga per article lengkap':'Harga per article belum lengkap'}</span><br/><small>HPP {money(q.hpp_total)} · Margin {money(q.margin_amount)} ({Number(q.margin_percent||0)}%)</small></td>
 <td>{money(q.amount)}<br/><small>{q.payment_plan||'Payment plan belum diisi'}</small></td>
 <td>{q.valid_until?<><span className={'badge '+sla.tone}>{sla.label}</span><br/><small>s/d {q.valid_until}</small></>:<span className="badge gray">Tanpa due date</span>}</td>
 <td><span className="badge blue">{queue.owner}</span><br/><small>{queue.next}</small></td>
 <td>{q.ceo_approved_by_id?<span className="badge green">Disetujui CEO (di atas limit)</span>:q.status==='APPROVED'?<span className="badge green">Disetujui CFO</span>:q.status==='REJECTED'?<span className="badge red">Ditolak CFO</span>:<span className="badge amber">Menunggu keputusan CFO</span>}{q.ceo_approval_reason&&<><br/><small>CEO: {q.ceo_approval_reason}</small></>}{q.approval_reason&&<><br/><small>CFO: {q.approval_reason}</small></>}</td>
 <td>{missingQuote.length?<span className="badge amber">{missingQuote.join(' · ')}</span>:<span className="badge green">Tidak ada</span>}</td>
  <td><small>{lines.length?`Harga per article (${lines.length} baris) + HPP`:'Belum ada rincian harga'}</small><br/><small>Payment plan: {q.payment_plan?'ada':'belum diisi'}</small></td>
 <td><span className={'badge '+statusTone(q.status)}>{q.status}</span><br/><small>{q.sent_at?'Dikirim '+q.sent_at:q.status==='SENT'?'Terkirim — waktu kirim belum tercatat':'Belum pernah dikirim'}</small></td>
 <td><small>{queue.response}</small></td>
 <td><span className={'badge '+handoff.tone}>{handoff.owner}</span><br/><small>{handoff.label}</small><br/><small>Berikutnya: {handoff.to}</small></td>
 <td><small>{q.updated_at||'—'}</small></td>
 <td>{manager&&q.status!=='APPROVED'&&<button className="btn" onClick={()=>openQuote(q)}>Edit</button>}{isCFO&&q.status!=='APPROVED'&&<button className="btn" onClick={()=>openQuote(q)}>Review CFO</button>}{isCEO&&policy&&Number(q.amount)>Number(policy.cfo_quotation_limit)&&!q.ceo_approved_by_id&&<button className="btn" onClick={()=>setDecision({id:q.id,reason:''})}>Approve Limit</button>}{manager&&q.status!=='APPROVED'&&<button className="btn" onClick={()=>remove(q.id)}>Hapus</button>}</td></tr>;})}{!list.length&&<tr><td colSpan={18}>Belum ada quotation.</td></tr>}</tbody></table></div>
 {form&&<FormModal title={isCFO?'Review CFO':form.id?'Edit Quotation':'Quotation Baru'} onClose={()=>setForm(null)} onSubmit={save} busy={busy} error={error}>{isCFO?<><p>Penjualan {money(form.amount)} · HPP {money(form.hpp_total)} · Margin {Number(form.margin_percent||0)}%</p><label>Keputusan<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option value="DRAFT">DRAFT</option><option value="APPROVED">APPROVED</option><option value="REJECTED">REJECTED</option></select></label><label>Alasan CFO<textarea required value={form.approval_reason||''} onChange={e=>setForm({...form,approval_reason:e.target.value})}/></label></>:<><label>Nomor Quotation<input required disabled={Boolean(form.id)} value={form.quotation_no} onChange={e=>setForm({...form,quotation_no:e.target.value})}/></label><label>Order<select required disabled={Boolean(form.id)} value={form.order_fk} onChange={e=>selectOrder(e.target.value)}><option value="">Pilih order</option>{orders.map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}</select></label><label>Currency<input maxLength={8} value={form.currency||'IDR'} onChange={e=>setForm({...form,currency:e.target.value.toUpperCase()})}/></label>{selected&&<section className="panel"><h2>Harga dan HPP per artikel</h2>{form.pricing_lines.map((line,i)=><div className="form-grid" key={line.article_id}><span>{line.article_code} · {line.qty} pcs</span><label>Harga/unit<input type="number" min="0.01" step="0.01" required value={line.unit_price} onChange={e=>updateLine(i,'unit_price',e.target.value)}/></label><label>HPP/unit<input type="number" min="0" step="0.01" required value={line.unit_hpp} onChange={e=>updateLine(i,'unit_hpp',e.target.value)}/></label></div>)}<p>Penjualan {money(total)} · HPP {money(hpp)} · Margin {total?((total-hpp)/total*100).toFixed(2):'0'}%</p></section>}<label>Payment Plan<textarea required value={form.payment_plan||''} onChange={e=>setForm({...form,payment_plan:e.target.value})}/></label><label>Berlaku Sampai<input type="date" value={form.valid_until||''} onChange={e=>setForm({...form,valid_until:e.target.value})}/></label><label>Status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option>DRAFT</option><option>SENT</option></select></label><label>Catatan<textarea value={form.notes||''} onChange={e=>setForm({...form,notes:e.target.value})}/></label></>}</FormModal>}
 {decision&&<FormModal title="Persetujuan CEO di atas limit" onClose={()=>setDecision(null)} onSubmit={approveLimit} busy={busy} error={error}><label>Alasan keputusan<textarea required value={decision.reason} onChange={e=>setDecision({...decision,reason:e.target.value})}/></label></FormModal>}</div>;
}
