import React,{useEffect,useState} from 'react';
import {useRole} from '../components/Access';
import {api} from '../api';
import {Plus,Edit2,X,Check,Search,Truck} from 'lucide-react';

const empty={shipment_fk:'',confirmed_by_customer:'',feedback:'',status:'PENDING'};
const statusOpts=['PENDING','CONFIRMED','ISSUE'];

export default function DeliveryPage(){
  const canWrite=useRole()==='CMO_MANAGER';
  const [list,setList]=useState([]),[shipments,setShipments]=useState([]);
  const [err,setErr]=useState('');
  const [q,setQ]=useState(''),[filterStatus,setFilterStatus]=useState('');
  const [form,setForm]=useState(null),[saving,setSaving]=useState(false);

  function load(){Promise.all([api('/coo/deliveries'),api('/coo/shipments')]).then(([d,s])=>{setList(d);setShipments(s)}).catch(e=>setErr(e.message))}
  useEffect(load,[]);

  function filtered(){
    return list.filter(d=>{
      if(filterStatus&&d.status!==filterStatus) return false;
      if(!q) return true;
      const s=q.toLowerCase();
      const shipNo=shipmentLabel(d.shipment_fk).toLowerCase();
      return shipNo.includes(s)||(d.confirmed_by_customer||'').toLowerCase().includes(s)||(d.feedback||'').toLowerCase().includes(s);
    });
  }

  async function save(ev){
    ev.preventDefault(); setSaving(true);
    try{
      const payload={...form,shipment_fk:form.shipment_fk?parseInt(form.shipment_fk):null};
      if(form.id){
        await api('/cmo/delivery-confirmations/'+form.id,{method:'PATCH',body:JSON.stringify(payload)});
      }else{
        await api('/cmo/delivery-confirmations',{method:'POST',body:JSON.stringify(payload)});
      }
      setForm(null); load();
    }catch(x){alert(x.message)}
    setSaving(false);
  }

  const f2=filtered();
  function shipmentLabel(id){const s=shipments.find(s=>s.id===id);return s?(s.shipment_no||'Shipment #'+id):'-'}

  const totalCount=list.length;
  const pendingCount=list.filter(d=>d.status==='PENDING').length;
  const confirmedCount=list.filter(d=>d.status==='CONFIRMED').length;
  const issueCount=list.filter(d=>d.status==='ISSUE').length;

  return <div className="page">
    <div className="page-title"><div><h1><Truck size={22}/> Konfirmasi Penerimaan Customer</h1><p>{totalCount} konfirmasi penerimaan</p></div>
      {canWrite&&<button className="btn primary" onClick={()=>setForm({...empty})}><Plus size={16}/> Tambah Konfirmasi</button>}</div>
    {err&&<div className="notice danger">{err}</div>}
    <div className="cards">
      <div className="stat blue"><strong>{totalCount}</strong><span>Total Konfirmasi</span></div>
      <div className="stat amber"><strong>{pendingCount}</strong><span>PENDING</span></div>
      <div className="stat green"><strong>{confirmedCount}</strong><span>CONFIRMED</span></div>
      <div className="stat red"><strong>{issueCount}</strong><span>ISSUE</span></div>
    </div>
    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/><input placeholder="Cari shipment, customer..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">{statusOpts.map(s=><button key={s} className={'pill '+(filterStatus===s?'active '+s.toLowerCase():'')} onClick={()=>setFilterStatus(filterStatus===s?'':s)}>{s}</button>)}</div>
    </div>
    <div className="table-scroll"><table><thead><tr><th>Shipment</th><th>Serah Terima Fisik</th><th>Confirmed By</th><th>Feedback</th><th>Konfirmasi Customer</th><th>Aksi</th></tr></thead>
    <tbody>{f2.map(d=><tr key={d.id}>
      <td><b>{shipmentLabel(d.shipment_fk)}</b></td>
      <td>{shipments.find(s=>s.id===d.shipment_fk)?.status||'-'}</td>
      <td>{d.confirmed_by_customer||'-'}</td>
      <td className="td-ellipsis">{d.feedback||'-'}</td>
      <td><span className={'badge '+(d.status==='CONFIRMED'?'green':d.status==='ISSUE'?'red':'amber')}>{d.status}</span></td>
      <td className="td-action">
        {canWrite&&d.status!=='CONFIRMED'&&<button className="icon-btn" onClick={()=>setForm({...d,shipment_fk:d.shipment_fk||'',confirmed_by_customer:d.confirmed_by_customer||'',feedback:d.feedback||''})} title="Edit konfirmasi"><Edit2 size={15}/></button>}
      </td>
    </tr>)}
    {f2.length===0&&<tr><td colSpan={6} className="empty">Belum ada konfirmasi penerimaan</td></tr>}</tbody></table></div>
    {form&&<div className="modal-bg" onClick={()=>setForm(null)}>
    <div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.id?'Edit':'Tambah'} Konfirmasi Customer</h2><button className="icon-btn" onClick={()=>setForm(null)}><X size={18}/></button></div>
      <form onSubmit={save}>
        <div className="form-grid">
          <label>Shipment *<select required value={form.shipment_fk} onChange={e=>setForm({...form,shipment_fk:e.target.value})}>
            <option value="">Pilih shipment...</option>{shipments.filter(s=>['SHIPPED','DELIVERED'].includes(s.status)).map(s=><option key={s.id} value={s.id}>{s.shipment_no||'Shipment #'+s.id} ({s.status})</option>)}
          </select></label>
          <label>Status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>{statusOpts.map(s=><option key={s}>{s}</option>)}</select></label>
        </div>
        <label>Tanggal Konfirmasi<input type="date" required={form.status==='CONFIRMED'} value={form.confirmation_date||''} onChange={e=>setForm({...form,confirmation_date:e.target.value})}/></label>
        <label>Confirmed By Customer<input required={form.status==='CONFIRMED'} value={form.confirmed_by_customer||''} onChange={e=>setForm({...form,confirmed_by_customer:e.target.value})} placeholder="Nama customer yang konfirmasi"/></label>
        <label>Feedback<textarea rows={3} value={form.feedback||''} onChange={e=>setForm({...form,feedback:e.target.value})} placeholder="Feedback dari customer..."/></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={saving}><Check size={14}/> {saving?'Menyimpan...':'Simpan'}</button></div>
      </form>
    </div></div>}
  </div>
}
