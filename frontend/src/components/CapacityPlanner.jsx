import React,{useCallback,useEffect,useState} from 'react';
import {api} from '../api';
import {capacityTone,dateInputValue,loadLabel,plannerQuery} from '../control';

/* Capacity Planner — tab CAPACITY PLANNER di sheet lama: kapan kita masih bisa menerima order baru
   untuk jahit, sablon, bordir, dan seterusnya. Pilih rentang tanggal; kapasitas = kapasitas harian × hari. */

const TONE_CLASS={red:'cap-red',amber:'cap-amber',green:'cap-green',gray:'cap-gray'};

export function CapacityBanner({banner}){
  return banner?<div className={'cap-banner '+banner.tone}>{banner.tone==='red'?'🔴':banner.tone==='amber'?'🟡':'🟢'} {banner.text}</div>:null;
}

export default function CapacityPlanner(){
  const [start,setStart]=useState(()=>dateInputValue(new Date())),[end,setEnd]=useState(()=>{const d=new Date();d.setDate(d.getDate()+29);return dateInputValue(d)});
  const [data,setData]=useState(null),[feed,setFeed]=useState(null),[err,setErr]=useState('');
  const load=useCallback(()=>{
    if(!start||!end||end<start){setErr('Tanggal akhir tidak boleh sebelum tanggal mulai');return}
    setErr('');api(plannerQuery(start,end)).then(setData).catch(e=>setErr(e.message));
  },[start,end]);
  useEffect(()=>{load()},[load]);
  useEffect(()=>{api('/control/capacity-feed').then(setFeed).catch(()=>{})},[]);

  return <div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    <section className="panel planner-inputs"><label>Mulai<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
      <label>Sampai<input type="date" value={end} min={start} onChange={e=>setEnd(e.target.value)}/></label>
      <div className="days"><b>{data?.days??'-'}</b><span>hari kalender</span></div>
      <small>Kapasitas periode = kapasitas harian × jumlah hari. Beban = pekerjaan yang sedang berada di tahap itu sekarang.</small></section>
    <CapacityBanner banner={data?.banner}/>
    <section className="panel flush"><div className="table-scroll"><table className="planner-table">
      <thead><tr><th>Tahap</th><th className="num">Order aktif</th><th className="num">Beban</th><th className="num">Kapasitas / hari</th><th className="num">Kapasitas periode</th><th>Load</th><th className="num">Tersedia</th><th>Status / aksi</th><th>PIC</th></tr></thead>
      <tbody>{(data?.rows||[]).map(r=><tr key={r.code} className={TONE_CLASS[capacityTone(r.status)]}>
        <td><b>{r.label}</b></td><td className="num">{r.orders}</td><td className="num">{r.load_amount} <small>{r.unit}</small></td>
        <td className="num">{r.daily_capacity} <small>{r.unit}</small></td><td className="num">{r.period_capacity}</td>
        <td><div className="load-bar" title={loadLabel(r.load_pct)}><span style={{width:Math.min(r.load_pct,100)+'%'}}/></div><small>{loadLabel(r.load_pct)}</small></td>
        <td className="num">{r.available}</td><td><b>{r.status}</b><br/><small>{r.action}</small></td><td>{r.pic||'-'}</td></tr>)}</tbody></table></div></section>

    {feed&&<section className="panel"><div className="panel-head"><h2>Sisa kapasitas untuk order baru</h2><span>Untuk CMO — patokan kapasitas {feed.basis} ({feed.daily_capacity} pcs/hari)</span></div>
      <div className="table-scroll"><table><thead><tr><th>Dalam</th><th className="num">Kapasitas</th><th className="num">Sudah terisi</th><th className="num">Masih bisa diterima</th><th className="num">WIP sekarang</th><th className="num">Cutting</th><th className="num">Printing</th><th className="num">Sewing</th></tr></thead>
        <tbody>{feed.rows.map(r=><tr key={r.horizon_days}><td><b>{r.horizon_days} hari</b></td><td className="num">{r.available_capacity}</td><td className="num">{r.confirmed_load}</td>
          <td className="num"><b>{r.free_capacity}</b> pcs</td><td className="num">{r.current_wip}</td><td className="num">{loadLabel(r.cutting_load_pct)}</td><td className="num">{loadLabel(r.printing_load_pct)}</td><td className="num">{loadLabel(r.sewing_load_pct)}</td></tr>)}</tbody></table></div></section>}
  </div>;
}
