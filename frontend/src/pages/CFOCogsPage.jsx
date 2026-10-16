import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {formatRupiah} from '../money';
import {formatDate} from '../control';

/* Analisa COGS mingguan: bahan terpakai + biaya produksi + upah borongan, dibagi output pcs (QC/Packing). */
export default function CFOCogsPage(){
  const [weeks,setWeeks]=useState(8),[data,setData]=useState(null),[err,setErr]=useState('');
  useEffect(()=>{api('/cfo/cogs-weekly?weeks='+weeks).then(setData).catch(e=>setErr(e.message))},[weeks]);
  const rows=data?.rows||[];
  const latest=rows.find(r=>r.cogs_per_pcs!=null);
  return <div className="page">
    <div className="page-title"><div><h1>Analisa COGS Mingguan</h1><p>{data?.basis||'Memuat…'}. Bahan dari pemakaian material, biaya produksi dari input biaya, upah dari hasil produksi karyawan.</p></div>
      <label className="inline-field">Tampilkan <select value={weeks} onChange={e=>setWeeks(Number(e.target.value))}>{[4,8,12,26].map(n=><option key={n} value={n}>{n} minggu</option>)}</select></label></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {latest&&<div className="cards cards-3"><div className="stat blue"><strong>{formatRupiah(latest.cogs_per_pcs)}</strong><span>COGS per pcs · minggu {formatDate(latest.week_start)}</span></div>
      <div className="stat gray"><strong>{formatRupiah(latest.total_cogs)}</strong><span>Total COGS minggu itu</span></div><div className="stat gray"><strong>{latest.output_pcs}</strong><span>Output (pcs)</span></div></div>}
    <section className="panel flush"><div className="table-scroll"><table className="cogs-table"><thead><tr><th>Minggu</th><th className="num">Bahan</th><th className="num">Biaya produksi</th><th className="num">Upah borongan</th><th className="num">Total COGS</th><th className="num">Output (pcs)</th><th className="num">COGS / pcs</th><th className="num">Perubahan</th></tr></thead>
      <tbody>{rows.map(r=><tr key={r.week_start} className={r.total_cogs===0?'zero':''}><td><b>{formatDate(r.week_start)}</b> – {formatDate(r.week_end)}</td><td className="num">{formatRupiah(r.material)}</td><td className="num">{formatRupiah(r.conversion)}</td><td className="num">{formatRupiah(r.wages)}</td>
        <td className="num"><b>{formatRupiah(r.total_cogs)}</b></td><td className="num">{r.output_pcs}</td><td className="num">{r.cogs_per_pcs!=null?<b>{formatRupiah(r.cogs_per_pcs)}</b>:'-'}</td>
        <td className={'num '+(r.change_pct>0?'red-cell':r.change_pct<0?'green-cell':'')}>{r.change_pct!=null?(r.change_pct>0?'+':'')+r.change_pct+'%':'-'}</td></tr>)}
        {data&&!rows.length&&<tr><td colSpan={8} className="empty-cell">Belum ada data.</td></tr>}</tbody></table></div></section>
    <p className="muted-note">Naik (merah) berarti COGS per pcs lebih mahal dari minggu sebelumnya yang punya output. Minggu tanpa output tidak dihitung per pcs.</p>
  </div>;
}
