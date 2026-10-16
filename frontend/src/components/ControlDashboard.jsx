import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {capacityTone,loadLabel} from '../control';
import {CapacityBanner} from './CapacityPlanner';

/* Dashboard — gabungan MASTER DASHBOARD dan WIP CAPACITY di sheet lama:
   berapa order & qty aktif, di tahap mana tertahan, jenis pakaian apa, dan siapa yang memegang. */

function Table({title,hint,head,rows,empty}){
  return <section className="panel"><div className="panel-head"><h2>{title}</h2><span>{hint}</span></div>
    <div className="table-scroll"><table><thead><tr>{head.map(h=><th key={h} className={h==='Tahap'||h==='Jenis pakaian'||h==='PIC'?'':'num'}>{h}</th>)}</tr></thead>
      <tbody>{rows.length?rows:<tr><td colSpan={head.length} className="empty-cell">{empty}</td></tr>}</tbody></table></div></section>;
}
const cell=(value,tone)=><td className={'num '+(value>0&&tone?tone+'-cell':'')}>{value}</td>;

export default function ControlDashboard(){
  const [d,setD]=useState(null),[err,setErr]=useState('');
  useEffect(()=>{api('/control/dashboard').then(setD).catch(e=>setErr(e.message))},[]);
  if(err)return <div className="notice danger" role="alert">{err}</div>;
  if(!d)return <p>Memuat…</p>;
  const s=d.summary,a=d.alerts;
  return <div>
    <CapacityBanner banner={d.forecast_banner&&{...d.forecast_banner,text:'FORECAST 14 HARI: '+d.forecast_banner.text}}/>
    <div className="cards cards-6">
      <div className="stat blue"><strong>{s.active_orders}</strong><span>Order aktif</span></div>
      <div className="stat blue"><strong>{s.active_qty}</strong><span>Active qty (pcs)</span></div>
      <div className="stat red"><strong>{s.urgent}</strong><span>Urgent</span></div>
      <div className="stat amber"><strong>{s.attention}</strong><span>Perhatian</span></div>
      <div className="stat gray"><strong>{s.progress}</strong><span>Progres</span></div>
      <div className="stat green"><strong>{s.done}</strong><span>Selesai</span></div>
    </div>
    <section className="panel"><div className="panel-head"><h2>Control alert</h2><span>Yang perlu dikejar hari ini</span></div>
      <table className="alert-table"><thead><tr><th>Alert</th><th className="num">Jumlah</th><th>Artinya</th></tr></thead><tbody>
        <tr><td>Payment outstanding</td>{cell(a.payment_outstanding,'amber')}<td>Order aktif belum lunas</td></tr>
        <tr><td>Deadline forecast urgent</td>{cell(a.deadline_forecast_urgent,'red')}<td>Diperkirakan melewati deadline buyer</td></tr>
        <tr><td>Urgent operation</td>{cell(a.urgent_operation,'red')}<td>Butuh tindakan segera</td></tr>
        <tr><td>Attention operation</td>{cell(a.attention_operation,'amber')}<td>Harus dipantau / dikejar</td></tr>
        <tr><td>Masalah terbuka</td>{cell(a.open_problems,'red')}<td>Problem / block yang belum diselesaikan PIC</td></tr>
      </tbody></table></section>
    <Table title="Forecast 14 hari" hint="Beban tahap bila semua order berjalan sesuai SLA" head={['Tahap','Order','Beban','Load %','Status','PIC']} empty="Belum ada order aktif."
      rows={d.forecast_14d.filter(r=>r.status!=='TIDAK DIPAKAI').map(r=><tr key={r.code} className={r.orders?'':'zero'}><td><b>{r.label}</b></td>{cell(r.orders)}<td className="num">{r.load} <small>{r.unit}</small></td><td className={'num '+({red:'red-cell',amber:'amber-cell'}[capacityTone(r.status)]||'')}>{loadLabel(r.load_pct)}</td><td>{r.status}</td><td>{r.pic||'-'}</td></tr>)}/>
    <div className="grid-half">
      <Table title="WIP per tahap" hint="Order dihitung di tahap sekarang-nya" head={['Tahap','Order','Buyer','Qty','Urgent','Perhatian','Progres']} empty="Belum ada order aktif."
        rows={d.wip_by_stage.map(r=><tr key={r.code} className={r.orders?'':'zero'}><td><b>{r.label}</b></td>{cell(r.orders)}{cell(r.buyers)}{cell(r.qty)}{cell(r.urgent,'red')}{cell(r.attention,'amber')}{cell(r.progress,'green')}</tr>)}/>
      <div>
        <Table title="WIP per jenis pakaian" hint="Qty menurut status order" head={['Jenis pakaian','Order','Qty','Urgent qty','Perhatian qty','Progres qty']} empty="Belum ada order aktif."
          rows={d.wip_by_garment.map(r=><tr key={r.garment}><td><b>{r.garment}</b></td>{cell(r.orders)}{cell(r.qty)}{cell(r.urgent_qty,'red')}{cell(r.attention_qty,'amber')}{cell(r.progress_qty,'green')}</tr>)}/>
        <Table title="Beban per PIC" hint="Breakdown tiap orang" head={['PIC','Order','Qty','Urgent','Perhatian','Progres']} empty="Belum ada pekerjaan aktif."
          rows={d.by_pic.map(r=><tr key={r.pic}><td><b>{r.pic}</b></td>{cell(r.orders)}{cell(r.qty)}{cell(r.urgent,'red')}{cell(r.attention,'amber')}{cell(r.progress,'green')}</tr>)}/>
      </div>
    </div>
  </div>;
}
