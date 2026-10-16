import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';

/* Modul Inventory/Purchasing (workspace Riadi) — BLUEPRINT §3.4 & PRD §6.
   Mengikuti pola AccountingPage persis: money format, tabel, filter-bar,
   pill tabs, form modal. Saldo stok datang dari server (turunan dari
   stock_movements), bukan dihitung di UI. */

const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:0});
const num=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2});
const TODAY=new Date().toISOString().slice(0,10);
const MASTER_WRITE=['COO_MANAGER','PRODUCTION_PIC'];
const APPROVE=['COO_MANAGER','CFO_MANAGER'];
const CATEGORIES=['KAIN','BENANG','AKSESORIS','KEMASAN','TINTA'];
const LOCATION_TYPES={WAREHOUSE:'Gudang',STAGING:'Staging',QUARANTINE:'Karantina',PRODUCTION:'Produksi'};
const TONE=status=>({
  READY:'green',POSTED:'green',APPROVED:'green',RELEASED:'green',ACTIVE:'green',
  PARTIAL:'amber',SUBMITTED:'amber',DRAFT:'amber',PENDING:'amber',NOT_REQUESTED:'gray',
  BLOCKED:'red',REJECTED:'red',CANCELLED:'red',
}[status]||'gray');

export default function InventoryPage(){
 const role=useRole();
 const canWrite=MASTER_WRITE.includes(role);
 const canApprove=APPROVE.includes(role);
 const canRelease=role==='COO_MANAGER';
 const [tab,setTab]=useState('material');
 const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
 const [data,setData]=useState({});

 function load(key,path){
   return api(path).then(r=>setData(d=>({...d,[key]:r}))).catch(e=>setErr(e.message));
 }
 useEffect(()=>{
   setErr('');
   if(tab==='material')load('materials','/inventory/materials');
   if(tab==='stok'){load('stock','/inventory/stock');load('low','/inventory/stock/low');load('materials','/inventory/materials');load('locations','/inventory/locations')}
   if(tab==='supplier')load('suppliers','/inventory/suppliers');
   if(tab==='pr'){load('prs','/inventory/purchase-requests');load('materials','/inventory/materials')}
   if(tab==='gr'){load('grs','/inventory/goods-receipts');load('materials','/inventory/materials');load('locations','/inventory/locations')}
   if(tab==='gate'){load('gates','/inventory/material-gates')}
 },[tab]);

 async function action(fn,reload){
   setBusy(true);setErr('');
   try{await fn();if(reload)load(reload[0],reload[1])}catch(e){setErr(e.message)}finally{setBusy(false)}
 }
 const seed=()=>action(()=>api('/inventory/seed',{method:'POST'}),['materials','/inventory/materials']);

 const TABS=[['material','Material'],['stok','Stok'],['supplier','Supplier'],['pr','Purchase Request'],['gr','Goods Receipt'],['gate','Material Gate']];

 return <div className="page">
  <div className="page-title">
    <div><h1>Inventory &amp; Purchasing</h1><p>Master material, stok per lokasi, purchase request, penerimaan barang, dan Material Gate — semuanya dari transaksi nyata.</p></div>
    {['COO_MANAGER','CFO_MANAGER'].includes(role)&&<div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
      <button className="btn" onClick={seed} disabled={busy}>Isi Data Awal</button>
    </div>}
  </div>
  {err&&<div className="notice danger" role="alert">{err}</div>}

  <div className="filter-bar">
    <div className="filter-pills" style={{flexWrap:'wrap'}}>
      {TABS.map(([k,l])=><button key={k} className={'pill'+(tab===k?' active open':'')} onClick={()=>setTab(k)}>{l}</button>)}
    </div>
  </div>

  {tab==='material'&&<MaterialPanel materials={data.materials} canWrite={canWrite} onChanged={()=>load('materials','/inventory/materials')}/>}
  {tab==='stok'&&<StokPanel stock={data.stock} low={data.low} materials={data.materials} locations={data.locations} canWrite={canWrite||canApprove} onChanged={()=>{load('stock','/inventory/stock');load('low','/inventory/stock/low')}}/>}
  {tab==='supplier'&&<SupplierPanel suppliers={data.suppliers} canWrite={canWrite} onChanged={()=>load('suppliers','/inventory/suppliers')}/>}
  {tab==='pr'&&<PRPanel prs={data.prs} materials={data.materials} canWrite={canWrite||canApprove} canApprove={canApprove} onChanged={()=>load('prs','/inventory/purchase-requests')}/>}
  {tab==='gr'&&<GRPanel grs={data.grs} materials={data.materials} locations={data.locations} canWrite={canWrite||canApprove} canPost={canApprove} onChanged={()=>load('grs','/inventory/goods-receipts')}/>}
  {tab==='gate'&&<GatePanel gates={data.gates} canApprove={canApprove} canRelease={canRelease} onChanged={()=>load('gates','/inventory/material-gates')}/>}
 </div>;
}

const StatusBadge=({s})=><span className={'badge '+TONE(s)}>{s}</span>;

// ── Material ────────────────────────────────────────────────────────────────
function MaterialPanel({materials,canWrite,onChanged}){
  const [form,setForm]=useState(null);
  const [cat,setCat]=useState('');
  const rows=useMemo(()=>(materials||[]).filter(m=>!cat||m.category===cat),[materials,cat]);
  async function save(){
    await api('/inventory/materials',{method:'POST',body:JSON.stringify({
      code:form.code,name:form.name,category:form.category||null,unit:form.unit||'pcs',
      min_stock:Number(form.min_stock||0),reorder_point:Number(form.reorder_point||0),
      standard_cost:Number(form.standard_cost||0)})});
    setForm(null);onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({code:'',name:'',category:'KAIN',unit:'pcs',min_stock:'0',reorder_point:'0',standard_cost:'0'})} style={{marginBottom:14}}>+ Material</button>}
    {form&&<section className="panel"><h2>Material Baru</h2>
      <div className="form-grid">
        <label>Kode<input value={form.code} onChange={e=>setForm({...form,code:e.target.value})}/></label>
        <label>Nama<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
        <label>Kategori<select value={form.category} onChange={e=>setForm({...form,category:e.target.value})}>
          <option value="">—</option>{CATEGORIES.map(c=><option key={c} value={c}>{c}</option>)}</select></label>
        <label>Satuan<input value={form.unit} onChange={e=>setForm({...form,unit:e.target.value})}/></label>
        <label>Min Stok<input type="number" value={form.min_stock} onChange={e=>setForm({...form,min_stock:e.target.value})}/></label>
        <label>Reorder Point<input type="number" value={form.reorder_point} onChange={e=>setForm({...form,reorder_point:e.target.value})}/></label>
        <label>Harga Standar<input type="number" value={form.standard_cost} onChange={e=>setForm({...form,standard_cost:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan</button></div>
    </section>}
    <section className="panel">
      <div className="panel-head"><h2>Master Material</h2>
        <select value={cat} onChange={e=>setCat(e.target.value)}>
          <option value="">Semua kategori</option>{CATEGORIES.map(c=><option key={c} value={c}>{c}</option>)}</select></div>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Nama</th><th>Kategori</th><th>Satuan</th><th style={{textAlign:'right'}}>Min</th><th style={{textAlign:'right'}}>Reorder</th><th style={{textAlign:'right'}}>Harga Std</th><th>Status</th></tr></thead>
        <tbody>{rows.map(m=><tr key={m.id}><td>{m.code}</td><td>{m.name}</td>
          <td>{m.category?<span className="badge gray">{m.category}</span>:'—'}</td><td>{m.unit}</td>
          <td style={{textAlign:'right'}}>{num(m.min_stock)}</td><td style={{textAlign:'right'}}>{num(m.reorder_point)}</td>
          <td style={{textAlign:'right'}}>{money(m.standard_cost)}</td>
          <td><StatusBadge s={m.is_active?'ACTIVE':'CANCELLED'}/></td></tr>)}
        {!rows.length&&<tr><td colSpan={8}>Belum ada material. Klik &quot;Isi Data Awal&quot;.</td></tr>}</tbody>
      </table></div>
    </section>
  </>;
}

// ── Stok ────────────────────────────────────────────────────────────────────
function StokPanel({stock,low,materials,locations,canWrite,onChanged}){
  const [form,setForm]=useState(null);
  const noMaster=!(materials||[]).length||!(locations||[]).length;
  const formValid=form&&form.material_id&&form.location_id&&Number(form.qty)>0;
  async function save(){
    if(!form.material_id||!form.location_id){alert('Material dan lokasi wajib dipilih.');return}
    if(!(Number(form.qty)>0)){alert('Qty harus lebih dari 0.');return}
    await api('/inventory/movements',{method:'POST',body:JSON.stringify({
      material_id:Number(form.material_id),location_id:Number(form.location_id),
      movement_type:form.movement_type,qty:Number(form.qty),
      unit_cost:form.unit_cost?Number(form.unit_cost):null,reason:form.reason||null})});
    setForm(null);onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" disabled={noMaster}
       title={noMaster?'Isi master material & lokasi dulu (tombol "Isi Data Awal").':undefined}
       onClick={()=>setForm({material_id:'',location_id:'',movement_type:'RECEIPT',qty:'',unit_cost:'',reason:''})} style={{marginBottom:14}}>+ Movement Stok</button>}
    {canWrite&&noMaster&&<p style={{color:'#b45309',fontSize:12,marginBottom:10}}>Master material/lokasi masih kosong — jalankan <b>Isi Data Awal</b> dulu sebelum mencatat movement.</p>}
    {form&&<section className="panel"><h2>Movement Stok</h2>
      <div className="form-grid">
        <label>Material<select value={form.material_id} onChange={e=>setForm({...form,material_id:e.target.value})}>
          <option value="">— pilih —</option>{(materials||[]).map(m=><option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}</select></label>
        <label>Lokasi<select value={form.location_id} onChange={e=>setForm({...form,location_id:e.target.value})}>
          <option value="">— pilih —</option>{(locations||[]).map(l=><option key={l.id} value={l.id}>{l.code} · {l.name}</option>)}</select></label>
        <label>Jenis<select value={form.movement_type} onChange={e=>setForm({...form,movement_type:e.target.value})}>
          {['RECEIPT','RETURN','ADJUSTMENT_IN','TRANSFER_IN','PRODUCTION_RETURN','ISSUE','ALLOCATION_ISSUE','TRANSFER_OUT','SCRAP','ADJUSTMENT_OUT'].map(t=><option key={t} value={t}>{t}</option>)}</select></label>
        <label>Qty<input type="number" value={form.qty} onChange={e=>setForm({...form,qty:e.target.value})}/></label>
        <label>Unit Cost<input type="number" value={form.unit_cost} onChange={e=>setForm({...form,unit_cost:e.target.value})}/></label>
        <label>Alasan (wajib utk ADJUSTMENT)<input value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" disabled={!formValid} onClick={()=>save().catch(e=>alert(e.message))}>Simpan</button></div>
    </section>}

    <section className="panel">
      <div className="panel-head"><h2>Stok di Bawah Reorder Point</h2>
        <span className="badge red">{low?.length||0} material</span></div>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Material</th><th>Satuan</th><th style={{textAlign:'right'}}>Saldo</th><th style={{textAlign:'right'}}>Reorder</th><th style={{textAlign:'right'}}>Kekurangan</th></tr></thead>
        <tbody>{(low||[]).map(r=><tr key={r.material_id} style={{background:'#fff5f5'}}>
          <td>{r.material_code}</td><td>{r.material_name}</td><td>{r.unit}</td>
          <td style={{textAlign:'right',color:'#dc2626',fontWeight:700}}>{num(r.qty)}</td>
          <td style={{textAlign:'right'}}>{num(r.reorder_point)}</td>
          <td style={{textAlign:'right',color:'#dc2626'}}>{num(r.shortage)}</td></tr>)}
        {!low?.length&&<tr><td colSpan={6}>Semua material di atas titik pesan ulang.</td></tr>}</tbody>
      </table></div>
    </section>

    <section className="panel"><h2>Saldo per Material per Lokasi</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Material</th><th>Lokasi</th><th style={{textAlign:'right'}}>Saldo</th><th style={{textAlign:'right'}}>Reorder</th><th>Kondisi</th></tr></thead>
        <tbody>{(stock||[]).map((r,i)=><tr key={i}>
          <td>{r.material_code} · {r.material_name}</td><td>{r.location_code||'—'}</td>
          <td style={{textAlign:'right',color:r.below_reorder?'#dc2626':undefined,fontWeight:r.below_reorder?700:undefined}}>{num(r.qty)}</td>
          <td style={{textAlign:'right'}}>{num(r.reorder_point)}</td>
          <td>{r.below_reorder?<span className="badge red">RENDAH</span>:<span className="badge green">OK</span>}</td></tr>)}
        {!stock?.length&&<tr><td colSpan={5}>Belum ada pergerakan stok.</td></tr>}</tbody>
      </table></div>
    </section>
  </>;
}

// ── Supplier ────────────────────────────────────────────────────────────────
function SupplierPanel({suppliers,canWrite,onChanged}){
  const [form,setForm]=useState(null);
  async function save(){
    await api('/inventory/suppliers',{method:'POST',body:JSON.stringify({
      code:form.code,name:form.name,vendor_type:form.vendor_type,
      contact_person:form.contact_person||null,phone:form.phone||null,
      lead_time_days:form.lead_time_days?Number(form.lead_time_days):null,
      payment_terms:form.payment_terms||null})});
    setForm(null);onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({code:'',name:'',vendor_type:'SUPPLIER',contact_person:'',phone:'',lead_time_days:'',payment_terms:''})} style={{marginBottom:14}}>+ Supplier</button>}
    {form&&<section className="panel"><h2>Supplier Baru</h2>
      <div className="form-grid">
        <label>Kode<input value={form.code} onChange={e=>setForm({...form,code:e.target.value})}/></label>
        <label>Nama<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
        <label>Tipe<select value={form.vendor_type} onChange={e=>setForm({...form,vendor_type:e.target.value})}>
          {['SUPPLIER','MAKLOON','LOGISTIK'].map(t=><option key={t} value={t}>{t}</option>)}</select></label>
        <label>Kontak<input value={form.contact_person} onChange={e=>setForm({...form,contact_person:e.target.value})}/></label>
        <label>Telepon<input value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></label>
        <label>Lead Time (hari)<input type="number" value={form.lead_time_days} onChange={e=>setForm({...form,lead_time_days:e.target.value})}/></label>
        <label>Termin<input value={form.payment_terms} onChange={e=>setForm({...form,payment_terms:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan</button></div>
    </section>}
    <section className="panel"><h2>Daftar Supplier</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Nama</th><th>Tipe</th><th>Kontak</th><th>Telepon</th><th style={{textAlign:'right'}}>Lead Time</th><th>Termin</th><th>Status</th></tr></thead>
        <tbody>{(suppliers||[]).map(s=><tr key={s.id}><td>{s.code}</td><td>{s.name}</td>
          <td><span className="badge gray">{s.vendor_type}</span></td><td>{s.contact_person||'—'}</td><td>{s.phone||'—'}</td>
          <td style={{textAlign:'right'}}>{s.lead_time_days??'—'}</td><td>{s.payment_terms||'—'}</td>
          <td><StatusBadge s={s.is_active?'ACTIVE':'CANCELLED'}/></td></tr>)}
        {!suppliers?.length&&<tr><td colSpan={8}>Belum ada supplier.</td></tr>}</tbody>
      </table></div>
    </section>
  </>;
}

// ── Purchase Request ────────────────────────────────────────────────────────
function PRPanel({prs,materials,canWrite,canApprove,onChanged}){
  const [form,setForm]=useState(null);
  const line=()=>({material_id:'',qty:'',estimated_unit_cost:''});
  async function save(){
    await api('/inventory/purchase-requests',{method:'POST',body:JSON.stringify({
      required_date:form.required_date||null,priority:form.priority,notes:form.notes||null,
      lines:form.lines.filter(l=>l.material_id).map(l=>({material_id:Number(l.material_id),qty:Number(l.qty||0),estimated_unit_cost:l.estimated_unit_cost?Number(l.estimated_unit_cost):null}))})});
    setForm(null);onChanged();
  }
  async function doAction(id,path,body){
    await api(`/inventory/purchase-requests/${id}/${path}`,{method:'POST',body:body?JSON.stringify(body):undefined});
    onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({required_date:TODAY,priority:'NORMAL',notes:'',lines:[line()]})} style={{marginBottom:14}}>+ Purchase Request</button>}
    {form&&<section className="panel"><h2>Purchase Request Baru</h2>
      <div className="form-grid">
        <label>Tanggal Dibutuhkan<input type="date" value={form.required_date} onChange={e=>setForm({...form,required_date:e.target.value})}/></label>
        <label>Prioritas<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>
          {['LOW','NORMAL','URGENT'].map(p=><option key={p} value={p}>{p}</option>)}</select></label>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      </div>
      <div className="table-scroll"><table><thead><tr><th>Material</th><th>Qty</th><th>Estimasi Harga</th><th/></tr></thead>
        <tbody>{form.lines.map((l,i)=><tr key={i}>
          <td><select value={l.material_id} onChange={e=>upd(i,{material_id:e.target.value})}>
            <option value="">— pilih —</option>{(materials||[]).map(m=><option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}</select></td>
          <td><input type="number" value={l.qty} onChange={e=>upd(i,{qty:e.target.value})}/></td>
          <td><input type="number" value={l.estimated_unit_cost} onChange={e=>upd(i,{estimated_unit_cost:e.target.value})}/></td>
          <td>{form.lines.length>1&&<button className="icon-btn danger" onClick={()=>setForm({...form,lines:form.lines.filter((_,j)=>j!==i)})}>×</button>}</td>
        </tr>)}</tbody></table></div>
      <div className="form-actions">
        <button className="btn" onClick={()=>setForm({...form,lines:[...form.lines,line()]})}>+ Baris</button>
        <button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan (Draft)</button>
      </div>
    </section>}
    <section className="panel"><h2>Daftar Purchase Request</h2>
      {!prs?<p>Memuat...</p>:<div className="table-scroll"><table>
        <thead><tr><th>No PR</th><th>Prioritas</th><th style={{textAlign:'right'}}>Estimasi</th><th>Dibutuhkan</th><th>Status</th><th>Aksi</th></tr></thead>
        <tbody>{prs.map(pr=><React.Fragment key={pr.id}>
          <tr><td>{pr.pr_no}</td><td><span className="badge gray">{pr.priority}</span></td>
            <td style={{textAlign:'right'}}>{money(pr.total_estimated)}</td>
            <td>{pr.required_date||'—'}</td><td><StatusBadge s={pr.status}/></td>
            <td>
              {canWrite&&pr.status==='DRAFT'&&<button className="btn sm" onClick={()=>doAction(pr.id,'submit').catch(x=>alert(x.message))}>Submit</button>}
              {canApprove&&pr.status==='SUBMITTED'&&<>
                <button className="btn sm" onClick={()=>doAction(pr.id,'approve').catch(x=>alert(x.message))}>Approve</button>
                <button className="btn sm" onClick={()=>{const r=prompt('Alasan tolak:');if(r)doAction(pr.id,'reject',{reason:r}).catch(x=>alert(x.message))}}>Tolak</button></>}
              {canApprove&&pr.status==='APPROVED'&&<button className="btn sm" onClick={()=>doAction(pr.id,'convert-to-po').catch(x=>alert(x.message))}>→ PO</button>}
            </td></tr>
          {pr.lines.map((l,i)=><tr key={pr.id+'-'+i} style={{background:'#fbfcfe'}}>
            <td/><td/><td style={{textAlign:'right',color:'#64748b'}}>{num(l.qty)} {l.unit||''} × {money(l.estimated_unit_cost)}</td>
            <td style={{paddingLeft:8,color:'#64748b'}} colSpan={2}>{l.material_code} · {l.material_name}</td><td/></tr>)}
        </React.Fragment>)}
        {!prs.length&&<tr><td colSpan={6}>Belum ada purchase request.</td></tr>}</tbody>
      </table></div>}
    </section>
  </>;
  function upd(i,patch){setForm(f=>({...f,lines:f.lines.map((l,j)=>j===i?{...l,...patch}:l)}))}
}

// ── Goods Receipt ───────────────────────────────────────────────────────────
function GRPanel({grs,materials,locations,canWrite,canPost,onChanged}){
  const [form,setForm]=useState(null);
  const line=()=>({material_id:'',location_id:'',qty_ordered:'',qty_received:'',qty_rejected:'0',unit_cost:''});
  async function save(){
    await api('/inventory/goods-receipts',{method:'POST',body:JSON.stringify({
      received_date:form.received_date||null,evidence_ref:form.evidence_ref||null,notes:form.notes||null,
      lines:form.lines.filter(l=>l.material_id&&l.location_id).map(l=>({material_id:Number(l.material_id),location_id:Number(l.location_id),
        qty_ordered:Number(l.qty_ordered||0),qty_received:Number(l.qty_received||0),qty_rejected:Number(l.qty_rejected||0),
        unit_cost:l.unit_cost?Number(l.unit_cost):null}))})});
    setForm(null);onChanged();
  }
  async function post(id){
    await api(`/inventory/goods-receipts/${id}/post`,{method:'POST'});
    onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({received_date:TODAY,evidence_ref:'',notes:'',lines:[line()]})} style={{marginBottom:14}}>+ Goods Receipt</button>}
    {form&&<section className="panel"><h2>Goods Receipt Baru</h2>
      <div className="form-grid">
        <label>Tanggal Terima<input type="date" value={form.received_date} onChange={e=>setForm({...form,received_date:e.target.value})}/></label>
        <label>Bukti Faktur/Surat Jalan<input value={form.evidence_ref} onChange={e=>setForm({...form,evidence_ref:e.target.value})}/></label>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      </div>
      <div className="table-scroll"><table><thead><tr><th>Material</th><th>Lokasi</th><th>Qty Pesan</th><th>Qty Terima</th><th>Qty Reject</th><th>Harga</th><th/></tr></thead>
        <tbody>{form.lines.map((l,i)=><tr key={i}>
          <td><select value={l.material_id} onChange={e=>upd(i,{material_id:e.target.value})}>
            <option value="">—</option>{(materials||[]).map(m=><option key={m.id} value={m.id}>{m.code}</option>)}</select></td>
          <td><select value={l.location_id} onChange={e=>upd(i,{location_id:e.target.value})}>
            <option value="">—</option>{(locations||[]).map(x=><option key={x.id} value={x.id}>{x.code}</option>)}</select></td>
          <td><input type="number" value={l.qty_ordered} onChange={e=>upd(i,{qty_ordered:e.target.value})}/></td>
          <td><input type="number" value={l.qty_received} onChange={e=>upd(i,{qty_received:e.target.value})}/></td>
          <td><input type="number" value={l.qty_rejected} onChange={e=>upd(i,{qty_rejected:e.target.value})}/></td>
          <td><input type="number" value={l.unit_cost} onChange={e=>upd(i,{unit_cost:e.target.value})}/></td>
          <td>{form.lines.length>1&&<button className="icon-btn danger" onClick={()=>setForm({...form,lines:form.lines.filter((_,j)=>j!==i)})}>×</button>}</td>
        </tr>)}</tbody></table></div>
      <div className="form-actions">
        <button className="btn" onClick={()=>setForm({...form,lines:[...form.lines,line()]})}>+ Baris</button>
        <button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan (Draft)</button>
      </div>
    </section>}
    <section className="panel"><h2>Daftar Goods Receipt</h2>
      {!grs?<p>Memuat...</p>:<div className="table-scroll"><table>
        <thead><tr><th>No GR</th><th>Tanggal</th><th>Status</th><th style={{textAlign:'right'}}>Baris</th><th>Bukti</th><th>Aksi</th></tr></thead>
        <tbody>{grs.map(gr=><React.Fragment key={gr.id}>
          <tr><td>{gr.gr_no}</td><td>{gr.received_date||'—'}</td><td><StatusBadge s={gr.status}/></td>
            <td style={{textAlign:'right'}}>{gr.lines.length}</td><td>{gr.evidence_ref||'—'}</td>
            <td>{canPost&&gr.status==='DRAFT'&&<button className="btn sm" onClick={()=>post(gr.id).catch(x=>alert(x.message))}>Posting Stok</button>}
              {gr.status==='POSTED'&&<span className="badge green">STOK DITAMBAH</span>}</td></tr>
          {gr.lines.map((l,i)=><tr key={gr.id+'-'+i} style={{background:'#fbfcfe'}}>
            <td/><td/><td/><td style={{textAlign:'right',color:'#64748b'}}>{num(l.qty_received)} {l.unit||''}</td>
            <td style={{paddingLeft:8,color:'#64748b'}} colSpan={2}>{l.material_code} · {l.material_name} @ {l.location_code}</td></tr>)}
        </React.Fragment>)}
        {!grs.length&&<tr><td colSpan={6}>Belum ada goods receipt.</td></tr>}</tbody>
      </table></div>}
    </section>
  </>;
  function upd(i,patch){setForm(f=>({...f,lines:f.lines.map((l,j)=>j===i?{...l,...patch}:l)}))}
}

// ── Material Gate ───────────────────────────────────────────────────────────
function GatePanel({gates,canApprove,canRelease,onChanged}){
  const [orderId,setOrderId]=useState('');
  async function evaluate(){
    await api('/inventory/material-gates/evaluate',{method:'POST',body:JSON.stringify({order_fk:Number(orderId)})});
    onChanged();
  }
  async function doAction(id,path,body){
    await api(`/inventory/material-gates/${id}/${path}`,{method:'POST',body:body?JSON.stringify(body):undefined});
    onChanged();
  }
  return <>
    <section className="panel">
      <div className="panel-head"><h2>Evaluasi Material Gate</h2>
        {canApprove&&<div style={{display:'flex',gap:8,alignItems:'center'}}>
          <input placeholder="id order (angka)" value={orderId} onChange={e=>setOrderId(e.target.value)} style={{width:140}}/>
          <button className="btn primary" disabled={!orderId} onClick={()=>evaluate().catch(e=>alert(e.message))}>Evaluasi Order</button>
        </div>}</div>
      <p style={{color:'#64748b',margin:'6px 0 0'}}>READY = kebutuhan BOM terpenuhi; PARTIAL = sebagian; NOT_REQUESTED = belum ada alokasi.</p>
    </section>
    <section className="panel"><h2>Daftar Material Gate</h2>
      {!gates?<p>Memuat...</p>:<div className="table-scroll"><table>
        <thead><tr><th>Artikel</th><th>Order</th><th style={{textAlign:'right'}}>Qty Artikel</th><th style={{textAlign:'right'}}>Dibutuhkan</th><th style={{textAlign:'right'}}>Teralokasi</th><th style={{textAlign:'right'}}>Kekurangan</th><th>Status</th><th>Aksi</th></tr></thead>
        <tbody>{gates.map(g=><tr key={g.id}>
          <td>{g.article_code||'—'}</td><td>{g.order_id||'—'}</td>
          <td style={{textAlign:'right'}}>{g.article_qty??'—'}</td>
          <td style={{textAlign:'right'}}>{num(g.required_qty)}</td>
          <td style={{textAlign:'right'}}>{num(g.allocated_qty)}</td>
          <td style={{textAlign:'right',color:g.shortage_qty>0?'#dc2626':undefined}}>{num(g.shortage_qty)}</td>
          <td><StatusBadge s={g.status}/>{g.block_reason&&<div style={{fontSize:11,color:'#dc2626'}}>{g.block_reason}</div>}</td>
          <td>{canRelease&&g.status==='READY'&&<button className="btn sm" onClick={()=>doAction(g.id,'release').catch(x=>alert(x.message))}>Release</button>}
            {canApprove&&g.status!=='BLOCKED'&&<button className="btn sm" onClick={()=>{const r=prompt('Alasan blokir:');if(r)doAction(g.id,'block',{reason:r}).catch(x=>alert(x.message))}}>Blokir</button>}</td>
        </tr>)}
        {!gates.length&&<tr><td colSpan={8}>Belum ada material gate. Evaluasi sebuah order untuk membuatnya.</td></tr>}</tbody>
      </table></div>}
    </section>
  </>;
}
