import React,{useCallback,useEffect,useState} from 'react';
import {useOutletContext} from 'react-router-dom';
import {api} from '../api';
import MoneyInput from '../components/MoneyInput';
import {formatRupiah,rupiahNumber} from '../money';
import {formatDate,dateInputValue} from '../control';

/* Input hasil produksi harian per karyawan + master karyawan harian. Upah = qty × tarif per pcs (tarif disalin saat dicatat). */
const PROCESSES=['CUTTING','SORTIR','PRINTING','BORDIR','QC S/B','SEWING','ACC','QC','PACKING','LAINNYA'];
const today=()=>dateInputValue(new Date());

export default function CFOProductionPage(){
  const role=useOutletContext()?.me?.role,canWrite=role==='CFO_MANAGER';
  const [tab,setTab]=useState('results'),[workers,setWorkers]=useState([]),[data,setData]=useState(null);
  const [from,setFrom]=useState(()=>{const d=new Date();d.setDate(d.getDate()-6);return dateInputValue(d)}),[workerFilter,setWorkerFilter]=useState('');
  const [form,setForm]=useState({result_date:today(),worker_fk:'',process:'SEWING',qty:'',order_id:'',rate:'',notes:''});
  const [worker,setWorker]=useState({name:'',process:'SEWING',rate_per_pcs:''});
  const [err,setErr]=useState(''),[ok,setOk]=useState(''),[busy,setBusy]=useState(false);

  const load=useCallback(async()=>{
    try{
      const [w,r]=await Promise.all([api('/cfo/workers'),api(`/cfo/production-results?date_from=${from}${workerFilter?'&worker_fk='+workerFilter:''}`)]);
      setWorkers(w);setData(r);setErr('');
    }catch(e){setErr(e.message)}
  },[from,workerFilter]);
  useEffect(()=>{load()},[load]);

  const chosen=workers.find(w=>String(w.id)===String(form.worker_fk));
  function pickWorker(id){const w=workers.find(x=>String(x.id)===id);setForm(f=>({...f,worker_fk:id,process:w?.process||f.process,rate:''}))}
  async function saveResult(e){
    e.preventDefault();setBusy(true);setErr('');setOk('');
    try{
      const body={result_date:form.result_date,worker_fk:Number(form.worker_fk),process:form.process,qty:Number(form.qty),notes:form.notes||null,
        order_id:form.order_id.trim()||null,rate:form.rate!==''?rupiahNumber(form.rate):null};
      const saved=await api('/cfo/production-results',{method:'POST',body:JSON.stringify(body)});
      setOk(`${saved.worker}: ${saved.qty} pcs ${saved.process} = ${formatRupiah(saved.amount)}`);
      setForm(f=>({...f,qty:'',order_id:'',rate:'',notes:''}));await load();
    }catch(x){setErr(x.message)}finally{setBusy(false)}
  }
  async function saveWorker(e){
    e.preventDefault();setErr('');
    try{await api('/cfo/workers',{method:'POST',body:JSON.stringify({name:worker.name,process:worker.process,rate_per_pcs:rupiahNumber(worker.rate_per_pcs)})});setWorker({name:'',process:'SEWING',rate_per_pcs:''});await load()}
    catch(x){setErr(x.message)}
  }
  async function toggle(w){try{await api('/cfo/workers/'+w.id,{method:'PATCH',body:JSON.stringify({is_active:!w.is_active})});await load()}catch(x){setErr(x.message)}}
  async function setRate(w){
    const text=window.prompt(`Tarif per pcs untuk ${w.name} (Rp):`,String(Math.round(w.rate_per_pcs)));
    if(text===null)return;
    try{await api('/cfo/workers/'+w.id,{method:'PATCH',body:JSON.stringify({rate_per_pcs:rupiahNumber(text)})});await load()}catch(x){setErr(x.message)}
  }
  async function remove(r){if(!confirm('Hapus catatan hasil produksi ini?'))return;try{await api('/cfo/production-results/'+r.id,{method:'DELETE'});await load()}catch(x){setErr(x.message)}}

  return <div className="page">
    <div className="page-title"><div><h1>Hasil Produksi & Karyawan Harian</h1><p>Catat hasil kerja tiap karyawan per hari; upah borongan terhitung otomatis (qty × tarif per pcs).</p></div></div>
    <div className="tabs" role="tablist">{[['results','Input Hasil Produksi'],['workers','Master Karyawan Harian']].map(([k,l])=><button key={k} role="tab" aria-selected={tab===k} className={tab===k?'on':''} onClick={()=>setTab(k)}>{l}</button>)}</div>
    {err&&<div className="notice danger" role="alert">{err}</div>}{ok&&<div className="notice success">{ok}</div>}

    {tab==='results'&&<>
      {canWrite&&<form className="panel form-stack" onSubmit={saveResult}>
        <div className="form-grid">
          <label>Tanggal<input type="date" required value={form.result_date} max={today()} onChange={e=>setForm({...form,result_date:e.target.value})}/></label>
          <label>Karyawan *<select required value={form.worker_fk} onChange={e=>pickWorker(e.target.value)}><option value="">Pilih karyawan…</option>{workers.filter(w=>w.is_active).map(w=><option key={w.id} value={w.id}>{w.name}{w.process?` · ${w.process}`:''}</option>)}</select></label>
          <label>Proses<select value={form.process} onChange={e=>setForm({...form,process:e.target.value})}>{PROCESSES.map(p=><option key={p}>{p}</option>)}</select></label>
          <label>Jumlah (pcs) *<input type="number" min="1" required value={form.qty} onChange={e=>setForm({...form,qty:e.target.value})}/></label>
          <label>Order ID<input value={form.order_id} onChange={e=>setForm({...form,order_id:e.target.value})} placeholder="SYM-2610-001 (opsional)"/></label>
          <label>Tarif / pcs<MoneyInput value={form.rate} onChange={v=>setForm({...form,rate:v})} placeholder={chosen?formatRupiah(chosen.rate_per_pcs):'Rp. 0'}/><small>Kosongkan untuk memakai tarif karyawan.</small></label>
        </div>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        <div className="modal-foot"><span className="hint-total">Upah: <b>{formatRupiah((form.rate!==''?rupiahNumber(form.rate):(chosen?.rate_per_pcs||0))*Number(form.qty||0))}</b></span><button className="btn primary" disabled={busy||!workers.length}>{busy?'Menyimpan…':'Simpan hasil'}</button></div>
        {!workers.length&&<small>Belum ada karyawan harian — tambahkan dulu di tab Master Karyawan Harian.</small>}
      </form>}
      <div className="filter-bar"><label className="inline-field">Mulai tanggal <input type="date" value={from} onChange={e=>e.target.value&&setFrom(e.target.value)}/></label>
        <label className="inline-field">Karyawan <select value={workerFilter} onChange={e=>setWorkerFilter(e.target.value)}><option value="">Semua</option>{workers.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label></div>
      {data&&<div className="cards cards-3"><div className="stat blue"><strong>{data.totals.qty}</strong><span>Total pcs</span></div><div className="stat green"><strong>{formatRupiah(data.totals.amount)}</strong><span>Total upah</span></div><div className="stat gray"><strong>{data.by_worker.length}</strong><span>Karyawan tercatat</span></div></div>}
      {data&&data.by_worker.length>0&&<div className="grid-half">
        <section className="panel"><div className="panel-head"><h2>Per karyawan</h2></div><table><thead><tr><th>Karyawan</th><th className="num">Pcs</th><th className="num">Upah</th></tr></thead><tbody>{data.by_worker.map(w=><tr key={w.worker_fk}><td><b>{w.worker}</b></td><td className="num">{w.qty}</td><td className="num">{formatRupiah(w.amount)}</td></tr>)}</tbody></table></section>
        <section className="panel"><div className="panel-head"><h2>Per hari</h2></div><table><thead><tr><th>Tanggal</th><th className="num">Pcs</th><th className="num">Upah</th></tr></thead><tbody>{data.by_day.map(d=><tr key={d.date}><td>{formatDate(d.date)}</td><td className="num">{d.qty}</td><td className="num">{formatRupiah(d.amount)}</td></tr>)}</tbody></table></section></div>}
      <section className="panel flush"><div className="table-scroll"><table><thead><tr><th>Tanggal</th><th>Karyawan</th><th>Proses</th><th>Order</th><th className="num">Pcs</th><th className="num">Tarif</th><th className="num">Upah</th><th></th></tr></thead>
        <tbody>{(data?.rows||[]).map(r=><tr key={r.id}><td>{formatDate(r.result_date)}</td><td><b>{r.worker}</b></td><td>{r.process}</td><td>{r.order_id||'-'}</td><td className="num">{r.qty}</td><td className="num">{formatRupiah(r.rate)}</td><td className="num"><b>{formatRupiah(r.amount)}</b></td><td>{canWrite&&<button className="btn sm" onClick={()=>remove(r)}>Hapus</button>}</td></tr>)}
          {data&&!data.rows.length&&<tr><td colSpan={8} className="empty-cell">Belum ada hasil produksi pada rentang ini.</td></tr>}</tbody></table></div></section>
    </>}

    {tab==='workers'&&<>
      {canWrite&&<form className="panel add-row" onSubmit={saveWorker}>
        <input required placeholder="Nama karyawan" value={worker.name} onChange={e=>setWorker({...worker,name:e.target.value})} aria-label="Nama karyawan"/>
        <select value={worker.process} onChange={e=>setWorker({...worker,process:e.target.value})} aria-label="Bagian">{PROCESSES.map(p=><option key={p}>{p}</option>)}</select>
        <MoneyInput value={worker.rate_per_pcs} onChange={v=>setWorker({...worker,rate_per_pcs:v})} placeholder="Tarif / pcs" aria-label="Tarif per pcs"/>
        <button className="btn primary sm">Tambah karyawan</button></form>}
      <section className="panel flush"><div className="table-scroll"><table><thead><tr><th>Nama</th><th>Bagian</th><th className="num">Tarif / pcs</th><th>Status</th><th></th></tr></thead>
        <tbody>{workers.map(w=><tr key={w.id} className={w.is_active?'':'zero'}><td><b>{w.name}</b></td><td>{w.process||'-'}</td><td className="num">{formatRupiah(w.rate_per_pcs)}</td><td>{w.is_active?'Aktif':'Nonaktif'}</td>
          <td>{canWrite&&<><button className="btn sm" onClick={()=>setRate(w)}>Ubah tarif</button> <button className="btn sm" onClick={()=>toggle(w)}>{w.is_active?'Nonaktifkan':'Aktifkan'}</button></>}</td></tr>)}
          {!workers.length&&<tr><td colSpan={5} className="empty-cell">Belum ada karyawan harian.</td></tr>}</tbody></table></div></section>
    </>}
  </div>;
}
