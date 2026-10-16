import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {capacityTone,formatDate,loadLabel,riskTone} from '../control';
import {CapacityBanner} from './CapacityPlanner';

/* Forecast Engine — tab FORECAST ENGINE di sheet lama: tiap order diproyeksikan dari tahap sekarang
   sampai SHIPPING memakai SLA, lalu dibandingkan dengan deadline buyer; dan beban tiap tahap 7/14/30 hari ke depan. */

const RISK_LABEL={URGENT:'URGENT — diperkirakan telat',PERHATIAN:'PERHATIAN — mepet deadline',AMAN:'AMAN','TANPA DEADLINE':'Tanpa deadline'};

export default function ForecastEngine(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[open,setOpen]=useState(null);
  useEffect(()=>{api('/control/forecast').then(setData).catch(e=>setErr(e.message))},[]);
  if(err)return <div className="notice danger" role="alert">{err}</div>;
  if(!data)return <p>Memuat…</p>;
  const c=data.risk_counts;
  return <div>
    <CapacityBanner banner={data.banner}/>
    <div className="cards cards-4">
      <div className="stat red"><strong>{c.URGENT}</strong><span>Diperkirakan telat</span></div>
      <div className="stat amber"><strong>{c.PERHATIAN}</strong><span>Mepet deadline</span></div>
      <div className="stat green"><strong>{c.AMAN}</strong><span>Aman</span></div>
      <div className="stat gray"><strong>{c['TANPA DEADLINE']}</strong><span>Tanpa deadline</span></div>
    </div>
    <section className="panel flush"><div className="panel-head pad"><h2>Proyeksi per order</h2><span>Klik baris untuk melihat tanggal tiap tahap</span></div>
      <div className="table-scroll"><table className="forecast-table"><thead><tr><th>Risiko</th><th>Order</th><th>Buyer</th><th>Article</th><th className="num">Qty</th><th>Tahap sekarang</th><th>Tahap berikut</th><th>Mulai tahap berikut</th><th>Estimasi kirim</th><th>Deadline</th><th className="num">Sisa hari</th></tr></thead>
        <tbody>{data.orders.map(o=><React.Fragment key={o.order_id}>
          <tr className={'risk-row '+riskTone(o.risk)} onClick={()=>setOpen(open===o.order_id?null:o.order_id)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')setOpen(open===o.order_id?null:o.order_id)}}>
            <td><b title={RISK_LABEL[o.risk]}>{o.risk}</b></td><td><Link to={'/orders/'+o.order_id} onClick={e=>e.stopPropagation()}>{o.order_id}</Link></td><td>{o.buyer}</td><td>{o.articles.join(', ')}</td>
            <td className="num">{o.qty}</td><td>{o.current_stage_label}</td><td>{o.next_stage_label||'-'}</td><td>{formatDate(o.est_next_date)}</td><td><b>{formatDate(o.est_finish)}</b></td><td>{formatDate(o.deadline)}</td><td className="num">{o.days_to_deadline??'-'}</td></tr>
          {open===o.order_id&&<tr className="dates-row"><td colSpan={11}><div className="stage-dates">{Object.entries(o.stage_dates).map(([code,date])=><span key={code}><small>{code.replace('_','/')}</small><b>{formatDate(date)}</b></span>)}</div></td></tr>}
        </React.Fragment>)}
        {!data.orders.length&&<tr><td colSpan={11} className="empty-cell">Belum ada order aktif untuk diproyeksikan.</td></tr>}</tbody></table></div></section>

    <section className="panel flush"><div className="panel-head pad"><h2>Beban tiap tahap ke depan</h2><span>Order dihitung pada saat mencapai tahap itu</span></div>
      <div className="table-scroll"><table><thead><tr><th>Tahap</th><th className="num">Kapasitas / hari</th><th className="num">7 hari</th><th className="num">14 hari</th><th className="num">30 hari</th><th>Status 14 hari</th><th>PIC</th></tr></thead>
        <tbody>{data.stages.map(s=><tr key={s.code} className={'cap-'+capacityTone(s.status)}><td><b>{s.label}</b></td><td className="num">{s.daily_capacity} <small>{s.unit}</small></td>
          {[7,14,30].map(h=><td key={h} className="num">{s[`load_${h}d`]} <small>({loadLabel(s[`load_pct_${h}d`])})</small></td>)}
          <td><b>{s.status}</b><br/><small>{s.action}</small></td><td>{s.pic||'-'}</td></tr>)}</tbody></table></div></section>
  </div>;
}
