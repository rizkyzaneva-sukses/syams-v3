import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {TrendingUp,RefreshCw} from 'lucide-react';

/* Revisi #14 poin 6 / #13 poin 4 — Sales Pipeline & Demand Gap.
   Buyer/Opportunity, stage, expected qty/value, probability, weighted demand,
   Next Action, Next Follow-up, owner, target close, repeat opportunity. */

const money=n=>n==null?'—':'Rp '+Number(n).toLocaleString('id-ID');

function GapCard({gap}){
  if(!gap) return null;
  const tone=gap.verdict==='KAPASITAS CUKUP'?'green':gap.verdict==='BELUM ADA KAPASITAS'?'gray':'red';
  return <section className="panel">
    <div className="panel-head"><h2>Demand Gap</h2><span>Weighted demand vs kapasitas harian</span></div>
    <div className="cards">
      <div className="stat blue"><strong>{gap.weighted_demand_qty}</strong><span>Weighted demand (pcs)</span></div>
      <div className="stat blue"><strong>{gap.capacity_per_day??'—'}</strong><span>Kapasitas / hari (pcs)</span></div>
      <div className={'stat '+tone}><strong>{gap.gap_qty==null?'—':gap.gap_qty}</strong><span>Gap (pcs)</span></div>
    </div>
    <div className={'notice '+(tone==='red'?'danger':tone==='green'?'success':'info')}>
      {gap.verdict}{gap.note?` — ${gap.note}`:''}
    </div>
  </section>;
}

export default function SalesPipelinePage(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);try{setData(await api('/cmo/sales-pipeline'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat pipeline...</div>;

  return <div className="page">
    <div className="page-title">
      <div><h1>Sales Pipeline</h1><p>Buyer, opportunity, weighted demand, dan Demand Gap terhadap kapasitas.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">{(data.stages||[]).map(s=><div className="stat blue" key={s.key}>
      <strong>{s.count}</strong><span>{s.label} · {s.expected_qty} pcs</span>
    </div>)}</div>

    <GapCard gap={data.demand_gap}/>

    <section className="panel">
      <div className="panel-head"><h2>Buyer / Opportunity</h2><span>{data.rows.length} baris</span></div>
      <div className="table-scroll"><table><thead><tr>
        <th>Buyer</th><th>Stage</th><th>Order</th><th>Expected Qty</th>
        <th>Probability</th><th>Weighted</th><th>Nilai</th><th>Margin</th>
        <th>Next Action</th><th>Next Follow-up</th><th>Owner</th><th>Target Close</th><th>Repeat</th>
      </tr></thead><tbody>
        {data.rows.map((r,i)=><tr key={i}>
          <td><b>{r.buyer}</b>{r.country?<><br/><small>{r.country}</small></>:null}</td>
          <td><span className="badge blue">{r.stage_label}</span></td>
          <td>{r.order_id?<Link to={'/orders/'+r.order_id}>{r.order_id}</Link>:'—'}</td>
          <td>{r.expected_qty}</td>
          <td>{r.probability}%</td>
          <td><b>{r.weighted_qty}</b></td>
          <td>{money(r.expected_value)}</td>
          <td>{r.margin_percent==null?'—':r.margin_percent+'%'}</td>
          <td>{r.next_action}</td>
          <td>{r.next_follow_up||'—'}</td>
          <td><span className="badge gray">{r.owner}</span></td>
          <td>{r.target_close||'—'}</td>
          <td>{r.repeat_opportunity?'Ya':'—'}</td>
        </tr>)}
        {!data.rows.length&&<tr><td colSpan={13} className="empty">Belum ada buyer atau order tercatat.</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
}