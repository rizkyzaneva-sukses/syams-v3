import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {formatRupiah} from '../money';
import {formatDate,dateInputValue} from '../control';

/* Data pembelian bahan (kain/benang/aksesoris) dan stok per kategori beserta nilai persediaan. */
const CATEGORIES=[['KAIN','Kain'],['BENANG','Benang / Sewing'],['AKSESORIS','Aksesoris'],['KEMASAN','Packing']];
const GROUP_LABEL={KAIN:'Stok Kain',BENANG:'Stok Benang / Sewing',AKSESORIS:'Stok Aksesoris & Packing'};

export default function CFOMaterialsPage({mode='purchases'}){
  const [category,setCategory]=useState('KAIN'),[from,setFrom]=useState(()=>{const d=new Date();d.setDate(d.getDate()-30);return dateInputValue(d)});
  const [purchases,setPurchases]=useState(null),[stock,setStock]=useState(null),[err,setErr]=useState('');
  useEffect(()=>{
    setErr('');
    if(mode==='purchases')api(`/cfo/material-purchases?category=${category}&date_from=${from}`).then(setPurchases).catch(e=>setErr(e.message));
    else api('/cfo/stock-summary').then(setStock).catch(e=>setErr(e.message));
  },[mode,category,from]);

  if(mode==='stock')return <div className="page">
    <div className="page-title"><div><h1>Stok Bahan</h1><p>Kain, benang/sewing, dan aksesoris/packing beserta nilai persediaannya.</p></div><Link className="btn" to="/inventory">Kelola stok di Inventory</Link></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {stock&&<><div className="cards cards-4">{stock.groups.map(g=><div key={g.group} className={'stat '+(g.below_reorder?'amber':'blue')}><strong>{formatRupiah(g.total_value)}</strong><span>{GROUP_LABEL[g.group]} · {g.item_count} item{g.below_reorder?` · ${g.below_reorder} di bawah titik pesan`:''}</span></div>)}
      <div className="stat green"><strong>{formatRupiah(stock.total_value)}</strong><span>Total persediaan</span></div></div>
      {stock.groups.map(g=><section className="panel flush" key={g.group}><div className="panel-head pad"><h2>{GROUP_LABEL[g.group]}</h2><span>{formatRupiah(g.total_value)}</span></div>
        <div className="table-scroll"><table><thead><tr><th>Kode</th><th>Nama</th><th>Kategori</th><th className="num">Stok</th><th className="num">Harga standar</th><th className="num">Nilai</th><th>Status</th></tr></thead>
          <tbody>{g.items.map(i=><tr key={i.material_id} className={i.below_reorder?'cap-amber':''}><td>{i.code}</td><td><b>{i.name}</b></td><td>{i.category}</td><td className="num">{i.qty} {i.unit}</td><td className="num">{formatRupiah(i.standard_cost)}</td><td className="num">{formatRupiah(i.value)}</td><td>{i.below_reorder?<b>Segera pesan</b>:'Aman'}</td></tr>)}
            {!g.items.length&&<tr><td colSpan={7} className="empty-cell">Belum ada stok tercatat.</td></tr>}</tbody></table></div></section>)}</>}
  </div>;

  return <div className="page">
    <div className="page-title"><div><h1>Data Pembelian Bahan</h1><p>Dari penerimaan barang (GR) yang sudah diposting: tanggal, supplier, qty, harga, dan total per minggu.</p></div></div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    <div className="filter-bar"><div className="seg" role="group" aria-label="Kategori">{CATEGORIES.map(([k,l])=><button key={k} type="button" className={category===k?'on':''} onClick={()=>setCategory(k)}>{l}</button>)}</div>
      <label className="inline-field">Mulai tanggal <input type="date" value={from} onChange={e=>e.target.value&&setFrom(e.target.value)}/></label></div>
    {purchases&&<><div className="cards cards-3"><div className="stat blue"><strong>{formatRupiah(purchases.total_amount)}</strong><span>Total pembelian</span></div><div className="stat gray"><strong>{purchases.rows.length}</strong><span>Baris penerimaan</span></div><div className="stat gray"><strong>{purchases.weekly.length}</strong><span>Minggu</span></div></div>
      {purchases.weekly.length>0&&<section className="panel"><div className="panel-head"><h2>Per minggu</h2><span>Senin–Minggu</span></div><table><thead><tr><th>Minggu mulai</th><th className="num">Qty</th><th className="num">Total</th></tr></thead><tbody>{purchases.weekly.map(w=><tr key={w.week_start}><td>{formatDate(w.week_start)}</td><td className="num">{w.qty}</td><td className="num"><b>{formatRupiah(w.amount)}</b></td></tr>)}</tbody></table></section>}
      <section className="panel flush"><div className="table-scroll"><table><thead><tr><th>Tanggal</th><th>No GR</th><th>Supplier</th><th>Bahan</th><th className="num">Qty</th><th className="num">Reject</th><th className="num">Harga</th><th className="num">Total</th></tr></thead>
        <tbody>{purchases.rows.map((r,i)=><tr key={i}><td>{formatDate(r.received_date)}</td><td>{r.gr_no}</td><td>{r.supplier||'-'}</td><td><b>{r.material}</b><br/><small>{r.code}</small></td><td className="num">{r.qty} {r.unit}</td><td className="num">{r.rejected||''}</td><td className="num">{formatRupiah(r.unit_cost)}</td><td className="num"><b>{formatRupiah(r.amount)}</b></td></tr>)}
          {!purchases.rows.length&&<tr><td colSpan={8} className="empty-cell">Belum ada penerimaan {category.toLowerCase()} pada rentang ini.</td></tr>}</tbody></table></div></section></>}
  </div>;
}
