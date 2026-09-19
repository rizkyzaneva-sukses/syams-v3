import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {Plus,Search,ExternalLink} from 'lucide-react';
import {FLOW_LABELS as STEP_NAMES,stepAction,missingEvidence,queueSource,isOverdue,slaBadge,handoffStatus,taskId} from '../queue';

const statusCls=v=>(v||'').includes('PAID')||v==='READY'||v==='ACTIVE'||v==='NEW'?'green':(v||'').includes('PARTIAL')?'amber':v==='DELAYED'||v==='HOLD'?'red':'gray';

// Flow step labels — UPPERCASE keys matching backend
const FLOW_STEP_LABELS = {
  ORDER: 'Order Diterima', INVOICE: 'Invoice', PPM: 'PPM', SAMPLE: 'Sample',
  SAMPLE_APPROVED: 'Sample OK', FOLLOW_UP: 'Follow-up', SPK: 'SPK',
  PRODUCTION: 'Produksi', QC: 'QC', SHIPMENT: 'Pengiriman',
  DELIVERED: 'Diterima', CLOSED: 'Selesai',
};

// Valid steps per order type — UPPERCASE
const ORDER_FLOWS = {
  SAMPLE_ONLY:       ['ORDER','INVOICE','PPM','SAMPLE','SAMPLE_APPROVED','FOLLOW_UP','CLOSED'],
  SAMPLE_PRODUCTION: ['ORDER','INVOICE','SAMPLE','SAMPLE_APPROVED','SPK','PRODUCTION','QC','SHIPMENT','DELIVERED','CLOSED'],
  REPEAT_PRODUCTION: ['ORDER','INVOICE','PPM','SPK','PRODUCTION','QC','SHIPMENT','DELIVERED','CLOSED'],
};

/* Label Indonesia untuk tipe order (blueprint poin 6: "order type"). */
export const ORDER_TYPE_LABELS = {SAMPLE_ONLY:'Sample saja', SAMPLE_PRODUCTION:'Sample + produksi', REPEAT_PRODUCTION:'Produksi berulang'};

/* Article yang bisa diulang: pernah diproduksi / sudah melewati sample. */
const REPEATABLE_ARTICLE = ['PRODUCED','DONE','IN_PRODUCTION','SHIPPED'];

export function sizesOf(order){
  return [...new Set((order.articles||[]).flatMap(a=>String(a.size_breakdown||'').match(/\b\d{2}\b/g)||[]))].sort().join(', ');
}

/* Draft Order punya article yang qty-nya masih kosong / nol di semua baris:
   validasi size dan qty belum jalan. */
export function sizeVerified(order){
  const articles = order.articles || [];
  if(!articles.length) return false;
  return articles.every(a=>Number(a.qty) > 0);
}

/* Blueprint poin 6: status review Cecep atas Draft Order. */
export function reviewStatus(order){
  if(order.flow_step === 'CLOSED') return {label:'Diterima — order selesai', tone:'green'};
  if(order.overall_status === 'HOLD') return {label:'Ditahan — menunggu kelengkapan', tone:'red'};
  if(order.flow_step === 'ORDER') return {label:missingEvidence(order).length ? 'Belum diajukan — berkas belum lengkap' : 'Siap direview Cecep', tone:missingEvidence(order).length ? 'amber' : 'blue'};
  return {label:'Diterima — Order aktif', tone:'green'};
}

/* Siapa yang menyiapkan draft (prepared_by Deby, blueprint poin 3 CMO Manager).
   Diambil dari PO intake kalau draft lahir dari PO; kalau tidak, dari
   created_by_id order. Nama diambil dari daftar user kalau tersedia. */
export function preparedBy(order, po, users){
  const id = po?.created_by_id ?? order.created_by_id ?? null;
  const row = (users||[]).find(u=>u.id===id);
  if(row) return {label:row.name, role:row.role, id};
  if(id!=null) return {label:`User ${id}`, role:null, id};
  return {label:'—', role:null, id:null};
}

/* Blueprint poin 6: kenapa draft harus diperbaiki. Diambil dari gate yang
   masih tertahan (uang, material, deadline), bukan dikarang di frontend. */
export function fixReason(order){
  const reasons = [];
  if(order.finance_status && !['PAID','CLEAR','READY'].includes(order.finance_status)) reasons.push(`Gate pembayaran belum lunas (${order.finance_status})`);
  if(order.material_status && !['READY','CLEAR'].includes(order.material_status)) reasons.push(`Material belum siap (${order.material_status})`);
  if(!order.buyer_deadline) reasons.push('Deadline buyer belum diisi');
  if(!order.projected_shipment) reasons.push('Proyeksi shipment belum diisi');
  if(!sizeVerified(order)) reasons.push('Qty/size article belum tervalidasi');
  return reasons;
}

function MiniFlowDots({ order }){
  const steps = ORDER_FLOWS[order.order_type] || ORDER_FLOWS.SAMPLE_PRODUCTION;
  const currentStep = order.flow_step || 'ORDER';
  const currentIdx = steps.indexOf(currentStep);
  const effIdx = currentIdx >= 0 ? currentIdx : 0;

  return (
    <div className="flow-mini" title={FLOW_STEP_LABELS[currentStep]||currentStep}>
      {steps.map((s,i) => (
        <div key={s} className={`flow-dot ${i < effIdx ? 'done' : i === effIdx ? 'current' : ''}`} />
      ))}
    </div>
  );
}

export default function OrderList(){
  const [orders,setOrders]=useState([]);
  const [err,setErr]=useState('');
  const [q,setQ]=useState('');
  const [flowFilter,setFlowFilter]=useState('');
  const [source,setSource]=useState([]);
  const [quotes,setQuotes]=useState([]);
  const [users,setUsers]=useState([]);

  /* PO sumber hanya tampil untuk peran yang boleh membaca PO Inbox; kalau
     ditolak, kolom PO source diisi tanda hubung, bukan halaman jadi error. */
  useEffect(()=>{
    api('/orders').then(setOrders).catch(e=>setErr(e.message));
    api('/cmo/po-intake').then(setSource).catch(()=>setSource([]));
    api('/cmo/quotations').then(setQuotes).catch(()=>setQuotes([]));
    api('/users').then(setUsers).catch(()=>setUsers([]));
  },[]);

  const allFlowSteps = [...new Set(orders.map(o=>o.flow_step).filter(Boolean))].sort();

  function filtered(){
    return orders.filter(o=>{
      const matchQ = !q || (()=>{
        const s=q.toLowerCase();
        return o.order_id.toLowerCase().includes(s)||o.buyer.toLowerCase().includes(s)||(o.articles||[]).some(a=>a.article_code.toLowerCase().includes(s));
      })();
      const matchFlow = !flowFilter || o.flow_step === flowFilter;
      return matchQ && matchFlow;
    });
  }

  const f2=filtered();

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Order Management</h1>
          <p>{orders.length} order tercatat</p>
        </div>
        <Link to="/cmo/po-inbox/new" className="btn primary"><Plus size={16}/> Terima PO Baru</Link>
      </div>

      {err&&<div className="notice danger">{err}</div>}

      <div className="filter-bar">
        <div className="search-bar" style={{flex:1}}>
          <Search size={16}/>
          <input placeholder="Cari Order ID, Buyer, Article..." value={q} onChange={e=>setQ(e.target.value)}/>
        </div>
      </div>

      {allFlowSteps.length > 0 && (
        <div className="flow-filter">
          <button className={`pill ${flowFilter===''?'active in_progress':''}`} onClick={()=>setFlowFilter('')}>All</button>
          {allFlowSteps.map(step=>(
            <button key={step} className={`pill ${flowFilter===step?'active in_progress':''}`} onClick={()=>setFlowFilter(step)}>
              {FLOW_STEP_LABELS[step]||step}
            </button>
          ))}
        </div>
      )}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Task ID</th><th>Draft Order ID</th><th>Buyer ID</th><th>PO source</th><th>Tipe</th><th>Repeat</th>
              <th>Article ID</th><th>Size / Qty tervalidasi</th><th>Deadline buyer</th><th>Quotation</th><th>Kelengkapan</th>
              <th>Prepared by</th><th>Review Cecep</th><th>Reason perbaikan</th><th>Tahap</th><th>Total Qty</th><th>Status</th>
              <th>Yang Kurang</th><th>Next Action</th><th>Owner</th><th>Due / SLA internal</th><th>Handoff</th><th>Sumber</th><th>Updated at</th><th></th>
            </tr>
          </thead>
          <tbody>
            {f2.map(o=>{
              const act=stepAction(o.flow_step);
              const missing=missingEvidence(o);
              const po=source.find(row=>row.order_fk===o.id||(row.order_id&&row.order_id===o.order_id));
              const quote=quotes.filter(row=>row.order_fk===o.id).sort((a,b)=>b.id-a.id)[0];
              const review=reviewStatus(o);
              const fixes=fixReason(o);
              const repeatable=(o.articles||[]).filter(a=>REPEATABLE_ARTICLE.includes(a.production_status)).length;
              const sizes=sizesOf(o);
              const prep=preparedBy(o,po,users);
              /* Kolom wajib antrean (REF-DEBY poin 3): Task ID, SLA internal dan
                 status handoff per-order. SLA dihitung dari deadline buyer yang
                 dipakai sebagai tenggat internal order ini. */
              const tid=o.task_id||taskId('ORDER',o.order_id);
              const sla=slaBadge(o.buyer_deadline);
              const handoff=handoffStatus({queue:act,closed:o.flow_step==='CLOSED'});
              return <tr key={o.id}>
                <td><b>{tid}</b></td>
                <td><Link to={'/orders/'+o.order_id}><b>{o.order_id}</b></Link></td>
                <td>Customer ID: {o.customer_id??'—'}<br/><small>{o.buyer}</small></td>
                <td>{po?<><Link to="/cmo/po-inbox"><b>{po.po_number||'Draft PO #'+po.id}</b></Link><br/><small>{po.received_at} · {po.document_name||'tanpa dokumen'}</small></>:<small>Tidak tertaut PO (dibuat langsung di Order Create)</small>}</td>
                <td><span className="badge gray">{ORDER_TYPE_LABELS[o.order_type]||o.order_type?.replace(/_/g,' ')}</span></td>
                <td>{repeatable?<span className="badge green">{repeatable} article repeatable</span>:<span className="badge gray">Belum ada</span>}</td>
                <td>{(o.articles||[]).length?(o.articles||[]).map(a=><div key={a.id}>{a.article_code||'(kode kosong)'} <small>· {a.qty} pcs · {a.production_status}</small></div>):'—'}</td>
                <td>{sizeVerified(o)?<><span className="badge green">Tervalidasi</span>{sizes&&<><br/><small>Size {sizes}</small></>}</>:<span className="badge amber">Belum tervalidasi</span>}</td>
                <td>{o.buyer_deadline?(isOverdue(o.buyer_deadline)?<span className="badge red">{o.buyer_deadline} · lewat</span>:o.buyer_deadline):'—'}</td>
                <td>{quote?<span className="badge gray">{quote.quotation_no}<br/>v{quote.id}</span>:<small>Belum ada quotation</small>}</td>
                <td>{missing.length?<span className="badge amber">{missing.join(', ')}</span>:<span className="badge green">Lengkap</span>}</td>
                <td><span className="badge gray">{prep.label}</span>{prep.role&&<><br/><small>{prep.role}</small></>}</td>
                <td><span className={'badge '+review.tone}>{review.label}</span></td>
                <td>{fixes.length?<small>{fixes.join('; ')}</small>:<span className="badge green">Tidak ada</span>}</td>
                <td><Link to={'/orders/'+o.order_id}><span className="badge blue">{STEP_NAMES[o.flow_step]||o.flow_step||'—'}</span></Link></td>
                <td>{o.articles?.reduce((s,a)=>s+a.qty,0)||0}</td>
                <td><span className={'badge '+statusCls(o.overall_status)}>{o.overall_status}</span></td>
                <td>{missing.length?<span className="badge amber">{missing.join(', ')}</span>:<span className="badge green">Lengkap</span>}</td>
                <td>{act.action}</td>
                <td><span className="badge gray">{act.owner}</span></td>
                <td>{o.buyer_deadline?<><span className={'badge '+sla.tone}>{sla.label}</span><br/><small>{o.buyer_deadline}</small></>:<span className="badge gray">Tanpa due date</span>}</td>
                <td><span className={'badge '+handoff.tone}>{handoff.owner}</span><br/><small>Berikutnya: {handoff.to}</small></td>
                <td><small>{queueSource(o)}</small></td>
                <td><small>{o.updated_at?new Date(o.updated_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
                <td><Link to={'/orders/'+o.order_id} className="icon-btn" title="Detail"><ExternalLink size={15}/></Link></td>
              </tr>;
            })}
            {f2.length===0&&<tr><td colSpan={25} className="empty">Tidak ada order ditemukan</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
