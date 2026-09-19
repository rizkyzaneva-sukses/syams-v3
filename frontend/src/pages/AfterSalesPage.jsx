import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw,MessageSquare,Truck} from 'lucide-react';
import {isOverdue} from '../queue';
import {statusTone} from '../business';

/* Revisi #10 — AFTER SALES (CMO Support / Deby).
   Deby HANYA berkomunikasi: menghubungi buyer, mencatat konfirmasi penerimaan,
   menampung keluhan/permintaan dan mencatat peluang repeat order. Eksekusi
   pengiriman (packing, dispatch, resi, serah terima fisik) milik COO — di sini
   status shipment hanya dibaca, tidak ada aksi kirim/ubah batch.

   Data digabung dari endpoint yang sudah ada (tanpa endpoint baru):
   - /cmo/buyer-crm  → buyer, kontak, komitmen, after_sales, repeat, next action, owner
   - /cmo/deby-today → antrean AFTER_SALES: apa yang belum dikonfirmasi + due
   - /orders         → order_id, buyer, shipment_status, overall_status, buyer_deadline
   - /coo/shipments  → Shipment ID, status batch, tracking, tanggal kirim (read-only)

   CATATAN DATA: API CMO tidak menyediakan tanggal penerimaan terpisah
   ("delivered_at"); batch perlu diverifikasi langsung ke COO. Yang tersedia hanya
   delivery_date milik batch COO, dan sering masih kosong. */

const FOLLOW_UP_TYPES=[
  {key:'SEMUA',label:'Semua'},
  {key:'KONFIRMASI',label:'Konfirmasi penerimaan'},
  {key:'KELUHAN',label:'Keluhan'},
  {key:'PERMINTAAN',label:'Permintaan lain'},
];

/* Keluhan/permintaan buyer. Backend belum punya field khusus, jadi jenis
   keluhan disimpulkan dari angka pada teks feedback (mis. "kurang 5 pcs"). */
function complaintFrame(text){
  if(!text)return {type:'PERMINTAAN',text:'—'};
  const shortfall=/(kurang|belum lengkap|belum diterima|rusak|cacat|reject)/i.test(text);
  return {type:shortfall?'KELUHAN':'PERMINTAAN',text};
}

export default function AfterSalesPage(){
  const [crm,setCrm]=useState(null),[today,setToday]=useState(null),[orders,setOrders]=useState([]),[ships,setShips]=useState([]);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false),[q,setQ]=useState(''),[type,setType]=useState('SEMUA');

  async function load(){
    setBusy(true);
    try{
      const [c,t,o]=await Promise.all([api('/cmo/buyer-crm'),api('/cmo/deby-today'),api('/orders')]);
      /* Batch COO dibaca untuk Shipment ID + tracking. Kalau endpoint ini tidak
         tersedia untuk peran CMO, halaman tetap jalan tanpa detail batch. */
      const sh=await api('/coo/shipments').catch(()=>[]);
      setCrm(c);setToday(t);setOrders(o);setShips(Array.isArray(sh)?sh:[]);setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  if(err&&!crm) return <div className="page"><div className="notice danger" role="alert">{err}</div></div>;
  if(!crm) return <div className="page">Memuat After Sales...</div>;

  const orderOf=id=>orders.find(o=>o.id===id)||null;
  const shipmentsOf=id=>ships.filter(s=>s.order_fk===id);
  const batchOf=id=>shipmentsOf(id).slice().sort((a,b)=>b.id-a.id)[0]||null;
  const queue=(today?.queues||[]).find(x=>x.key==='AFTER_SALES');
  const queueRows=queue?.rows||[];
  const tasksOfBuyer=buyer=>queueRows.filter(r=>r.buyer===buyer);

  /* Urutan baris: pengiriman yang sudah jalan lebih dulu (perlu dikonfirmasi),
     lalu buyer lain yang masih dalam pipeline komitmen. */
  const rows=(crm.rows||[]).map(r=>{
    const order=orderOf(r.latest_order_id);
    const batch=batchOf(order?.id);
    const tasks=tasksOfBuyer(r.buyer);
    const q1=tasks[0]||null;
    const delivery=order?.shipment_status||'NOT_READY';
    const deliveredStage=['SHIPPED','DELIVERED'].includes(delivery);
    const confirmed=r.after_sales?.status==='CONFIRMED'||Boolean(r.after_sales?.confirmed_by_customer);
    const due=(r.next_follow_up||order?.buyer_deadline)||null;
    const complaint=complaintFrame(r.after_sales?.feedback);
    return {
      buyer:r.buyer, buyer_id:r.buyer_id, country:r.country, owner:r.owner||'CMO_SUPPORT',
      contact_name:r.contact_name, contact_info:r.contact_info,
      order_id:r.latest_order_id, order_fk:order?.id||null,
      shipment_id:batch?.shipment_no||null, tracking:batch?.tracking_no||null,
      shipment_status:delivery, batch_status:batch?.status||null,
      delivered_at:batch?.delivery_date||null, shipped_at:batch?.shipped_date||null,
      deliveredStage, confirmed,
      confirmed_by:r.after_sales?.confirmed_by_customer||null,
      confirmation_date:r.after_sales?.confirmation_date||null,
      feedback:r.after_sales?.feedback||null,
      follow_up_type:complaint.type,
      repeat:Boolean(r.repeat_opportunity),
      next_action:q1?.next_action||r.next_action||'—',
      task_id:q1?.task_id||null,
      missing:q1?.missing||null,
      due, handoff:q1?.handoff||'Closing customer & operasional',
      source:q1?.source||'Aliran order',
      updated_at:q1?.updated_at||null,
      commitment:r.customer_commitment,
    };
  }).sort((a,b)=>(b.deliveredStage-a.deliveredStage)||(Number(b.confirmed)-Number(a.confirmed))||String(a.buyer).localeCompare(String(b.buyer)));

  const term=q.trim().toLowerCase();
  const filtered=rows.filter(r=>{
    if(type!=='SEMUA'&&r.follow_up_type!==type)return false;
    return !term||[r.buyer,r.order_id,r.shipment_id,r.tracking,r.feedback,r.next_action,r.contact_name]
      .some(v=>String(v||'').toLowerCase().includes(term));
  });

  const waiting=rows.filter(r=>r.deliveredStage&&!r.confirmed);
  const confirmed=rows.filter(r=>r.confirmed);
  const overdue=rows.filter(r=>isOverdue(r.due));
  const repeats=rows.filter(r=>r.repeat);
  const complaints=rows.filter(r=>r.follow_up_type==='KELUHAN');

  return <div className="page">
    <div className="page-title">
      <div><h1>After Sales</h1><p>Komunikasi pasca-pengiriman: konfirmasi penerimaan buyer, keluhan, permintaan, dan peluang repeat order.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards compact">
      <div className={'stat '+(waiting.length?'amber':'green')}><strong>{waiting.length}</strong><span>Menunggu konfirmasi buyer</span></div>
      <div className="stat green"><strong>{confirmed.length}</strong><span>Sudah dikonfirmasi</span></div>
      <div className={'stat '+(overdue.length?'red':'green')}><strong>{overdue.length}</strong><span>Follow-up lewat due</span></div>
      <div className={'stat '+(complaints.length?'amber':'green')}><strong>{complaints.length}</strong><span>Keluhan / permintaan</span></div>
      <div className="stat blue"><strong>{repeats.length}</strong><span>Peluang repeat order</span></div>
    </div>

    <div className="notice info">
      <MessageSquare size={14}/> Deby di sini <b>hanya berkomunikasi</b> dan mencatat hasilnya.
      Eksekusi pengiriman — packing, dispatch, resi, dan serah terima fisik — milik COO,
      jadi kolom batch/pengiriman di bawah bersifat informasi (read-only).
      {queue?.handoff?<> Handoff berikutnya: <b>{queue.handoff}</b>.</>:null}
      {!ships.length?<> Detail batch COO tidak terbaca dari peran ini, sehingga Shipment ID bertanda “—”.</>:null}
    </div>

    <div className="filter-bar">
      <div className="search-bar"><MessageSquare size={16}/><input aria-label="Cari after sales" placeholder="Cari buyer, order, shipment, resi, feedback..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">{FOLLOW_UP_TYPES.map(t=><button key={t.key}
        className={'pill '+(type===t.key?'active blue':'')} onClick={()=>setType(t.key)}>{t.label}</button>)}</div>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>Buyer</th><th>Order ID</th><th>Shipment ID</th><th>delivered_at</th>
      <th>Konfirmasi Buyer</th><th>Jenis Follow-up</th><th>Keluhan / Permintaan</th>
      <th>Next Action</th><th>Due</th><th>Peluang Repeat</th><th>PIC</th>
    </tr></thead>
      <tbody>{filtered.map(r=><tr key={r.buyer}>
        <td>
          <b>{r.buyer}</b><br/>
          <small>{r.country||'—'}</small>
          {r.contact_name?<><br/><small>{r.contact_name}{r.contact_info?` · ${r.contact_info}`:''}</small></>:null}
        </td>
        <td>{r.order_id?<Link to={'/orders/'+r.order_id}>{r.order_id}</Link>:'—'}
          <br/><span className={'badge '+statusTone(r.shipment_status)}>{r.shipment_status}</span></td>
        <td>{r.shipment_id
          ?<><b>{r.shipment_id}</b><br/><small>{r.batch_status||'—'}{r.tracking?` · ${r.tracking}`:''}</small></>
          :<><span className="badge gray">—</span><br/><small>batch belum dibuat COO</small></>}</td>
        <td>{r.delivered_at
          ?<span className="badge green">{r.delivered_at}</span>
          :r.shipped_at
            ?<><span className="badge amber">belum dikonfirmasi COO</span><br/><small>dikirim {r.shipped_at}</small></>
            :<span className="badge gray">belum jalan</span>}</td>
        <td>{r.confirmed
          ?<><span className="badge green">CONFIRMED</span><br/>
             <small>{r.confirmed_by||'—'}{r.confirmation_date?` · ${r.confirmation_date}`:''}</small></>
          :r.deliveredStage
            ?<span className="badge amber">Menunggu konfirmasi</span>
            :<span className="badge gray">Belum ada pengiriman</span>}</td>
        <td><span className={'badge '+(r.follow_up_type==='KELUHAN'?'red':'blue')}>{r.follow_up_type}</span></td>
        <td style={{whiteSpace:'normal',maxWidth:280}}>{r.feedback||(r.missing||'—')}</td>
        <td style={{whiteSpace:'normal',maxWidth:260}}>{r.next_action}
          {r.task_id?<><br/><small>{r.task_id} · {r.missing||'—'}</small></>:null}</td>
        <td>{r.due
          ?(isOverdue(r.due)?<span className="badge red">{r.due} · lewat</span>:<span className="badge amber">{r.due}</span>)
          :'—'}</td>
        <td>{r.repeat?<span className="badge green">Ya</span>:<span className="badge gray">—</span>}</td>
        <td><span className={'badge '+(r.owner==='CMO_SUPPORT'?'blue':'gray')}>{r.owner}</span>
          {r.handoff?<><br/><small>{r.handoff}</small></>:null}</td>
      </tr>)}
      {!filtered.length&&<tr><td colSpan={11} className="empty">Tidak ada baris after sales untuk filter ini.</td></tr>}
      </tbody></table></div>

    <section className="panel">
      <div className="panel-head">
        <h2>Antrean After Sales &ldquo;Hari Ini&rdquo;</h2>
        <span>{(queue?.rows||[]).length} tugas · owner {queue?.owner||'CMO_SUPPORT'}</span>
      </div>
      {queueRows.length?<div className="table-scroll"><table><thead><tr>
        <th>Task ID</th><th>Buyer</th><th>Order</th><th>Shipment Status</th><th>Data Kurang</th>
        <th>Next Action</th><th>Owner</th><th>Due</th><th>Source</th><th>Updated</th>
      </tr></thead>
        <tbody>{queueRows.map(t=><tr key={t.task_id}>
          <td><b>{t.task_id}</b></td>
          <td>{t.buyer||'—'}</td>
          <td>{t.order_id?<Link to={'/orders/'+t.order_id}>{t.order_id}</Link>:'—'}</td>
          <td><span className={'badge '+statusTone(t.status)}>{t.status||'—'}</span></td>
          <td><span className="badge amber">{t.missing||'—'}</span></td>
          <td>{t.next_action}</td>
          <td><span className="badge blue">{t.owner}</span></td>
          <td>{t.due?(isOverdue(t.due)?<span className="badge red">{t.due} · lewat</span>:t.due):'—'}</td>
          <td><small>{t.source||'—'}</small></td>
          <td><small>{t.updated_at?new Date(t.updated_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
        </tr>)}</tbody></table></div>
        :<p className="empty">Tidak ada pengiriman yang menunggu komunikasi Deby saat ini.</p>}
      <p style={{fontSize:12,color:'#64748b',marginTop:6}}>
        <Truck size={12}/> Antrean ini diisi dari order berstatus SHIPPED/DELIVERED yang belum punya konfirmasi buyer.
        Baris hilang setelah COO mencatat konfirmasi penerimaan.
      </p>
    </section>
  </div>;
}
