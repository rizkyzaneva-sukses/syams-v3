import React,{useEffect,useState} from 'react';
import {useOutletContext} from 'react-router-dom';
import {api} from '../api';
import MoneyInput from '../components/MoneyInput';

export default function BOMCostPage(){
  const [orders,setOrders]=useState([]),[orderId,setOrderId]=useState(''),[bom,setBom]=useState([]),[usage,setUsage]=useState([]),[cost,setCost]=useState(null),[error,setError]=useState('');
  const [item,setItem]=useState({article_id:'',material_name:'',unit:'m',qty_per_unit:'',planned_unit_cost:''});
  const [consume,setConsume]=useState({bom_item_id:'',qty:'',actual_unit_cost:'',evidence_ref:''});
  const [extra,setExtra]=useState({article_id:'',category:'LABOR',amount:'',evidence_ref:''}),[reviewEvidence,setReviewEvidence]=useState('');
  const {me}=useOutletContext();const role=me?.role;
  async function refresh(id=orderId){try{setError('');const [b,u,c]=await Promise.all([api('/coo/bom?order_fk='+id),api('/coo/material-consumptions?order_fk='+id),api('/coo/actual-cost/'+id)]);setBom(b);setUsage(u);setCost(c)}catch(e){setError(e.message)}}
  useEffect(()=>{api('/orders').then(o=>{setOrders(o);if(o.length)setOrderId(String(o[0].id))}).catch(e=>setError(e.message))},[]);
  useEffect(()=>{if(orderId)refresh(orderId)},[orderId]);
  async function saveItem(e){e.preventDefault();try{await api('/coo/bom',{method:'POST',body:JSON.stringify({...item,article_id:Number(item.article_id),qty_per_unit:Number(item.qty_per_unit),planned_unit_cost:Number(item.planned_unit_cost)})});setItem({...item,material_name:'',qty_per_unit:'',planned_unit_cost:''});refresh()}catch(x){setError(x.message)}}
  async function saveUsage(e){e.preventDefault();try{await api('/coo/material-consumptions',{method:'POST',body:JSON.stringify({...consume,bom_item_id:Number(consume.bom_item_id),qty:Number(consume.qty),actual_unit_cost:Number(consume.actual_unit_cost)})});setConsume({...consume,qty:'',actual_unit_cost:'',evidence_ref:''});refresh()}catch(x){setError(x.message)}}
  async function saveExtra(e){e.preventDefault();try{await api('/coo/production-costs',{method:'POST',body:JSON.stringify({...extra,article_id:Number(extra.article_id),amount:Number(extra.amount)})});setExtra({...extra,amount:'',evidence_ref:''});refresh()}catch(x){setError(x.message)}}
  async function verifyCost(e){e.preventDefault();try{await api('/cfo/orders/'+orderId+'/cost-review',{method:'POST',body:JSON.stringify({evidence_ref:reviewEvidence})});setReviewEvidence('');refresh()}catch(x){setError(x.message)}}
  const order=orders.find(o=>o.id===Number(orderId));
  const canPlan=role==='COO_MANAGER',canRecord=canPlan||role==='PRODUCTION_PIC',canExtra=canPlan||role==='CFO_MANAGER';
  return <div className="page"><div className="page-title"><div><h1>BOM & Biaya Material Aktual</h1><p>Biaya aktual berasal dari pemakaian material yang memiliki bukti.</p></div></div>
    {error&&<div className="notice danger">{error}</div>}
    <section className="panel"><label>Order<select value={orderId} onChange={e=>setOrderId(e.target.value)}>{orders.map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}</select></label></section>
    {canPlan&&<section className="panel"><h2>Tambah kebutuhan BOM per artikel</h2><form onSubmit={saveItem} className="form-grid">
      <label>Artikel<select required value={item.article_id} onChange={e=>setItem({...item,article_id:e.target.value})}><option value="">Pilih artikel</option>{order?.articles?.map(a=><option key={a.id} value={a.id}>{a.article_code} ({a.qty} pcs)</option>)}</select></label>
      <label>Material<input required value={item.material_name} onChange={e=>setItem({...item,material_name:e.target.value})}/></label>
      <label>Satuan<input required value={item.unit} onChange={e=>setItem({...item,unit:e.target.value})}/></label>
      <label>Qty per pcs<input type="number" min="0.0001" step="any" required value={item.qty_per_unit} onChange={e=>setItem({...item,qty_per_unit:e.target.value})}/></label>
      <label>Biaya rencana per satuan<MoneyInput required value={item.planned_unit_cost} onChange={v=>setItem({...item,planned_unit_cost:v})}/></label>
      <button className="btn primary">Simpan BOM</button></form></section>}
    <section className="panel"><h2>BOM</h2><div className="table-scroll"><table><thead><tr><th>Artikel</th><th>Material</th><th>Qty/pcs</th><th>Satuan</th><th>Biaya rencana/satuan</th></tr></thead><tbody>{bom.map(b=><tr key={b.id}><td>{order?.articles?.find(a=>a.id===b.article_id)?.article_code}</td><td>{b.material_name}</td><td>{b.qty_per_unit}</td><td>{b.unit}</td><td>{b.planned_unit_cost}</td></tr>)}</tbody></table></div></section>
    {canRecord&&<section className="panel"><h2>Catat pemakaian aktual</h2><form onSubmit={saveUsage} className="form-grid">
      <label>Item BOM<select required value={consume.bom_item_id} onChange={e=>setConsume({...consume,bom_item_id:e.target.value})}><option value="">Pilih item</option>{bom.map(b=><option key={b.id} value={b.id}>{order?.articles?.find(a=>a.id===b.article_id)?.article_code} — {b.material_name}</option>)}</select></label>
      <label>Qty dipakai<input type="number" min="0.0001" step="any" required value={consume.qty} onChange={e=>setConsume({...consume,qty:e.target.value})}/></label>
      <label>Biaya aktual per satuan<MoneyInput required value={consume.actual_unit_cost} onChange={v=>setConsume({...consume,actual_unit_cost:v})}/></label>
      <label>Referensi bukti<input required value={consume.evidence_ref} onChange={e=>setConsume({...consume,evidence_ref:e.target.value})} placeholder="Nomor gudang / dokumen"/></label>
      <button className="btn primary">Catat pemakaian</button></form></section>}
    {canExtra&&<section className="panel"><h2>Biaya tenaga kerja & overhead</h2><form onSubmit={saveExtra} className="form-grid">
      <label>Artikel<select required value={extra.article_id} onChange={e=>setExtra({...extra,article_id:e.target.value})}><option value="">Pilih artikel</option>{order?.articles?.map(a=><option key={a.id} value={a.id}>{a.article_code}</option>)}</select></label>
      <label>Kategori<select value={extra.category} onChange={e=>setExtra({...extra,category:e.target.value})}><option>LABOR</option><option>OVERHEAD</option><option>OTHER</option></select></label>
      <label>Jumlah biaya<MoneyInput required value={extra.amount} onChange={v=>setExtra({...extra,amount:v})}/></label>
      <label>Referensi bukti<input required value={extra.evidence_ref} onChange={e=>setExtra({...extra,evidence_ref:e.target.value})}/></label>
      <button className="btn primary">Catat biaya</button></form></section>}
    {role==='CFO_MANAGER'&&<section className="panel"><h2>Verifikasi total biaya oleh CFO</h2><p>Pastikan seluruh material, upah dan overhead telah dicatat. Jika kategori biaya bernilai nol, sebutkan dalam bukti review.</p><form onSubmit={verifyCost}><label>Referensi review<input required value={reviewEvidence} onChange={e=>setReviewEvidence(e.target.value)} placeholder="Nomor laporan costing dan asumsi nol"/></label><button className="btn primary">Verifikasi biaya</button></form></section>}
    <section className="panel"><h2>Ringkasan HPP aktual</h2><p>Material: {cost?.actual_material_cost??'-'} · Upah & overhead: {cost?.labor_overhead_cost??'-'} · Total: {cost?.actual_total_cost??'-'}</p><p>Pemakaian material: {cost?.cost_complete?'Lengkap':'Belum lengkap'} · Review CFO: {cost?.cost_verified?'Terverifikasi':'Belum terverifikasi'}</p><p>Margin aktual: {cost?.actual_margin_percent!=null?`${cost.actual_margin_percent}% (${cost.actual_margin})`:'Belum tersedia'}</p><div className="table-scroll"><table><thead><tr><th>Artikel</th><th>Rencana material</th><th>Material aktual</th><th>Upah/overhead</th><th>Aktual total</th><th>Material lengkap</th></tr></thead><tbody>{cost?.articles?.map(a=><tr key={a.article_id}><td>{a.article_code}</td><td>{a.planned_material_cost}</td><td>{a.actual_material_cost}</td><td>{a.labor_overhead_cost}</td><td>{a.actual_total_cost}</td><td>{a.cost_complete?'Ya':'Belum'}</td></tr>)}</tbody></table></div><p>{usage.length} transaksi pemakaian tercatat.</p></section>
  </div>
}
