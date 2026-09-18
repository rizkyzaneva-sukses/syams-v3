import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {Plus,Search,ExternalLink} from 'lucide-react';

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

  useEffect(()=>{api('/orders').then(setOrders).catch(e=>setErr(e.message))},[]);

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
              <th>Order ID</th><th>Buyer</th><th>Tipe</th><th>Articles</th>
              <th>Total Qty</th><th>Deadline</th><th>Flow</th>
              <th>Finance</th><th>Material</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {f2.map(o=>(
              <tr key={o.id}>
                <td><Link to={'/orders/'+o.order_id}><b>{o.order_id}</b></Link></td>
                <td>{o.buyer}</td>
                <td><span className="badge gray">{o.order_type?.replace(/_/g,' ')}</span></td>
                <td>{o.articles?.map(a=>a.article_code).join(', ')||'-'}</td>
                <td>{o.articles?.reduce((s,a)=>s+a.qty,0)||0}</td>
                <td>{o.buyer_deadline||'-'}</td>
                <td>
                  <Link to={'/orders/'+o.order_id} style={{display:'flex',flexDirection:'column',gap:4,textDecoration:'none',color:'inherit'}}>
                    <MiniFlowDots order={o}/>
                    <span style={{fontSize:11,color:'#64748b'}}>{FLOW_STEP_LABELS[o.flow_step]||o.flow_step||'-'}</span>
                  </Link>
                </td>
                <td><span className={'badge '+statusCls(o.finance_status)}>{o.finance_status}</span></td>
                <td><span className={'badge '+statusCls(o.material_status)}>{o.material_status}</span></td>
                <td><span className={'badge '+statusCls(o.overall_status)}>{o.overall_status}</span></td>
                <td><Link to={'/orders/'+o.order_id} className="icon-btn" title="Detail"><ExternalLink size={15}/></Link></td>
              </tr>
            ))}
            {f2.length===0&&<tr><td colSpan={11} className="empty">Tidak ada order ditemukan</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
