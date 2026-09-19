import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';

const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID');
const BUCKETS=[['all','Semua'],['not_due','Belum jatuh tempo'],['d1_30','1–30 hari'],['d31_60','31–60 hari'],['d_over_60','> 60 hari']];
const ACTIONS={NONE:'—',REMIND:'Pengingat',FOLLOW_UP:'Follow-up',ESCALATE_CMO:'Eskalasi CMO',ESCALATE_CEO:'Eskalasi CEO',RE_VERIFY:'Verifikasi ulang bukti'};
const tone=v=>({'PAID':'green','OPEN':'','PARTIAL':'amber','OVERDUE':'amber','CRITICAL':'red','NOT_RECEIVED':'','OUTSTANDING':'amber'}[v]||'');
const cmoView=r=>['CMO_MANAGER','CMO_SUPPORT'].includes(r);

export default function CFOReceivablesPage(){
 const role=useRole(),isCmo=cmoView(role),canAp=!isCmo;
 const [ar,setAr]=useState(null),[ap,setAp]=useState(null),[tab,setTab]=useState('ar');
 const [bucket,setBucket]=useState('all'),[buyer,setBuyer]=useState(''),[onlyOut,setOnlyOut]=useState(false);
 const [vendorType,setVendorType]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 async function load(){
   setLoading(true);
   try{
     const qs=new URLSearchParams();if(bucket!=='all')qs.set('bucket',bucket);if(buyer.trim())qs.set('buyer',buyer.trim());if(onlyOut)qs.set('only_outstanding','true');
     const jobs=[api('/cfo/ar-aging'+(qs.toString()?'?'+qs:''))];
     if(canAp){const pq=new URLSearchParams();if(vendorType)pq.set('vendor_type',vendorType);jobs.push(api('/cfo/ap-summary'+(pq.toString()?'?'+pq:'')));}
     const [a,p]=await Promise.all(jobs);setAr(a);if(canAp)setAp(p);setError('');
   }catch(e){setError(e.message)}finally{setLoading(false)}
 }
 useEffect(()=>{load()},[bucket,onlyOut,vendorType]);
 return <div className="page">
  <div className="page-title"><div><h1>AR & Collection · AP</h1><p>Aging piutang per buyer, antrean collection, dan hutang supplier/makloon terpisah.</p></div>{!isCmo&&<button className="btn" onClick={load}>Muat ulang</button>}</div>
  {error&&<div className="notice danger" role="alert">{error}</div>}
  {!isCmo&&<div className="tabs"><button className={'btn'+(tab==='ar'?' primary':'')} onClick={()=>setTab('ar')}>AR & Collection</button><button className={'btn'+(tab==='ap'?' primary':'')} onClick={()=>setTab('ap')}>AP Supplier & Makloon</button></div>}

  {(isCmo||tab==='ar')&&<>
   <div className="filters">
    <label>Bucket<select aria-label="Filter bucket" value={bucket} onChange={e=>setBucket(e.target.value)}>{BUCKETS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
    <label>Buyer<input aria-label="Filter buyer" placeholder="Nama buyer" value={buyer} onChange={e=>setBuyer(e.target.value)} onKeyDown={e=>e.key==='Enter'&&load()}/></label>
    <label><input type="checkbox" checked={onlyOut} onChange={e=>setOnlyOut(e.target.checked)}/> Hanya outstanding</label>
    <button className="btn primary" onClick={load}>Terapkan</button>
   </div>
   {loading&&!ar?<p>Memuat...</p>:ar&&<>
    <section className="panel"><h2>Ringkasan Aging</h2>
     <div className="stats">
      <div className="stat"><span>Total Tagihan</span><b>{money(ar.summary.total_amount)}</b></div>
      <div className="stat"><span>Terbayar</span><b>{money(ar.summary.total_paid)}</b></div>
      <div className="stat"><span>Outstanding</span><b>{money(ar.summary.total_outstanding)}</b></div>
      <div className="stat"><span>Jatuh Tempo</span><b>{ar.summary.overdue_count}</b></div>
      <div className="stat"><span>Kritis &gt;60</span><b>{ar.summary.critical_count}</b></div>
     </div>
     <div className="table-scroll"><table><thead><tr><th>Aging</th><th>Jumlah Invoice</th><th>Outstanding</th></tr></thead><tbody>{ar.summary.buckets.map(b=><tr key={b.bucket}><td>{b.label}</td><td>{b.invoice_count}</td><td>{money(b.outstanding)}</td></tr>)}</tbody></table></div>
     {!!ar.summary.invoices_with_unverified_payment.length&&<div className="notice danger">Bukti bayar belum lengkap: {ar.summary.invoices_with_unverified_payment.join(', ')}</div>}
    </section>
    <section className="panel"><h2>Aging per Buyer</h2><div className="table-scroll"><table><thead><tr><th>Buyer</th><th>Invoice</th><th>Belum JT</th><th>1–30</th><th>31–60</th><th>&gt;60</th><th>Outstanding</th></tr></thead><tbody>{ar.by_buyer.map(b=><tr key={b.buyer}><td>{b.buyer}</td><td>{b.invoice_count}</td><td>{money(b.not_due)}</td><td>{money(b.d1_30)}</td><td>{money(b.d31_60)}</td><td>{money(b.d_over_60)}</td><td>{money(b.outstanding)}</td></tr>)}{!ar.by_buyer.length&&<tr><td colSpan={7}>Tidak ada piutang pada filter ini.</td></tr>}</tbody></table></div></section>
    <section className="panel"><h2>Antrean Collection</h2><div className="table-scroll"><table><thead><tr><th>Buyer / Order</th><th>Invoice</th><th>Total</th><th>Terbayar</th><th>Outstanding</th><th>Jatuh Tempo</th><th>Promised</th><th>Aging</th><th>Next Action</th><th>Owner</th><th>Status</th></tr></thead><tbody>{ar.rows.map(r=><tr key={r.invoice_id}><td>{r.buyer||'—'}<br/>{r.order_id||'—'}</td><td>{r.invoice_no}</td><td>{money(r.amount)}</td><td>{money(r.paid)}</td><td>{money(r.outstanding)}</td><td>{r.due_date||'—'}{r.days_overdue?<><br/><small>{r.days_overdue} hari</small></>:null}</td><td>{r.promised_date||'—'}</td><td>{r.aging_label}</td><td>{isCmo?(ACTIONS[r.next_action]||'—'):(ACTIONS[r.next_action]||r.next_action)}</td><td>{r.owner||'—'}</td><td><span className={'badge '+tone(r.status)}>{r.status}</span></td></tr>)}{!ar.rows.length&&<tr><td colSpan={11}>Tidak ada invoice pada filter ini.</td></tr>}</tbody></table></div></section>
    <section className="panel"><h2>Bukti Pembayaran</h2>{ar.rows.filter(r=>r.payment_count).map(r=><div className="article" key={r.invoice_id}><b>{r.invoice_no}</b><span>{r.paid>=r.amount?'Terverifikasi':'Sebagian'}</span><small>{r.unverified_payment_count?`${r.unverified_payment_count} pembayaran tanpa referensi bukti`:'Semua pembayaran punya referensi'}</small></div>)}{!ar.rows.some(r=>r.payment_count)&&<p>Belum ada pembayaran tercatat.</p>}</section>
   </>}
  </>}

  {!isCmo&&tab==='ap'&&<>
   <div className="filters">
    <label>Jenis Partner<select aria-label="Filter vendor" value={vendorType} onChange={e=>setVendorType(e.target.value)}><option value="">Semua</option><option value="SUPPLIER">Supplier</option><option value="MAKLOON">Makloon</option></select></label>
    <button className="btn primary" onClick={load}>Terapkan</button>
   </div>
   {loading&&!ap?<p>Memuat...</p>:ap&&<>
    <section className="panel"><h2>Ringkasan AP</h2>
     <div className="stats">
      <div className="stat"><span>Supplier Outstanding</span><b>{money(ap.summary.supplier.outstanding)}</b><small>{ap.summary.supplier.count} PO</small></div>
      <div className="stat"><span>Makloon Outstanding</span><b>{money(ap.summary.makloon.outstanding)}</b><small>{ap.summary.makloon.count} PO</small></div>
      <div className="stat"><span>Total Outstanding</span><b>{money(ap.summary.total.outstanding)}</b></div>
      <div className="stat"><span>Terlambat</span><b>{money(ap.summary.overdue_outstanding)}</b></div>
      <div className="stat"><span>Jatuh Tempo 7 Hari</span><b>{money(ap.summary.cash_plan.next_7_days)}</b></div>
     </div>
    </section>
    <section className="panel"><h2>Cash Plan</h2><div className="table-scroll"><table><thead><tr><th>Kategori</th><th>Nilai</th></tr></thead><tbody><tr><td>Terlambat</td><td>{money(ap.summary.cash_plan.overdue)}</td></tr><tr><td>7 hari ke depan</td><td>{money(ap.summary.cash_plan.next_7_days)}</td></tr><tr><td><b>Total wajib dibayar</b></td><td><b>{money(ap.summary.cash_plan.total_due)}</b></td></tr></tbody></table></div></section>
    <section className="panel"><h2>AP per Vendor</h2><div className="table-scroll"><table><thead><tr><th>Vendor</th><th>Jenis</th><th>PO</th><th>Nilai</th><th>Terbayar</th><th>Outstanding</th></tr></thead><tbody>{ap.by_vendor.map(v=><tr key={v.vendor}><td>{v.vendor}</td><td><span className={'badge '+(v.vendor_type==='MAKLOON'?'amber':'blue')}>{v.vendor_type}</span></td><td>{v.po_count}</td><td>{money(v.amount)}</td><td>{money(v.paid)}</td><td>{money(v.outstanding)}</td></tr>)}{!ap.by_vendor.length&&<tr><td colSpan={6}>Tidak ada PO pada filter ini.</td></tr>}</tbody></table></div></section>
    <section className="panel"><h2>Register AP</h2><div className="table-scroll"><table><thead><tr><th>AP ID / PO</th><th>Jenis</th><th>Supplier</th><th>Order</th><th>Nilai</th><th>Terbayar</th><th>Outstanding</th><th>Jadwal</th><th>Jatuh Tempo</th><th>Approval</th><th>Status</th></tr></thead><tbody>{ap.rows.map(r=><tr key={r.po_id}><td>{r.ap_id}<br/><small>{r.po_no}</small></td><td><span className={'badge '+(r.vendor_type==='MAKLOON'?'amber':'blue')}>{r.vendor_type}</span></td><td>{r.supplier||'—'}<br/><small>{r.item||''}</small></td><td>{r.order_id||'—'}</td><td>{money(r.amount)}</td><td>{money(r.paid)}</td><td>{money(r.outstanding)}</td><td>{r.payment_schedule}</td><td>{r.due_date||'—'}</td><td>{r.approval_status}</td><td><span className={'badge '+tone(r.status)}>{r.status}</span></td></tr>)}{!ap.rows.length&&<tr><td colSpan={11}>Belum ada purchase order.</td></tr>}</tbody></table></div></section>
   </>}
  </>}
 </div>;
}
