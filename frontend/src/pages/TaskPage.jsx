import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {Plus,Edit2,Check,CheckCircle,Trash2,X,Search,ClipboardList} from 'lucide-react';

const empty={title:'',assigned_to_id:'',order_fk:'',due_date:'',status:'OPEN'};
const statusOpts=['OPEN','IN_PROGRESS','DONE','CANCELLED'];

export default function TaskPage(){
  const [list,setList]=useState([]),[users,setUsers]=useState([]),[orders,setOrders]=useState([]);
  const [me,setMe]=useState(null);
  const [err,setErr]=useState('');
  const [q,setQ]=useState(''),[filterStatus,setFilterStatus]=useState('');
  const [form,setForm]=useState(null),[saving,setSaving]=useState(false);

  const isPIC=me && ['CMO_SUPPORT','SAMPLE_PIC','PRINTING_PIC','PRODUCTION_PIC','SHIPMENT_ADMIN'].includes(me.role);

  function load(){
    // PIC-level roles are not allowed to read the user directory, and HR roles
    // cannot read orders. Both lists are optional context for the task list, so
    // a 403 on either must degrade gracefully instead of blanking the page.
    Promise.all([api('/tasks'),api('/users').catch(()=>[]),api('/orders').catch(()=>[]),api('/auth/me')]).then(([t,u,o,m])=>{
      setList(t); setUsers(u); setOrders(o); setMe(m);
    }).catch(e=>setErr(e.message));
  }
  useEffect(load,[]);

  // PIC roles only see their own tasks
  function visibleTasks(){
    if(isPIC && me) return list.filter(t=>t.assigned_to_id===me.id);
    return list;
  }

  function filtered(){
    return visibleTasks().filter(t=>{
      if(filterStatus&&t.status!==filterStatus) return false;
      if(!q) return true;
      const s=q.toLowerCase();
      const u=users.find(u=>u.id===t.assigned_to_id);
      return t.title.toLowerCase().includes(s)||((u?.name||'').toLowerCase().includes(s));
    });
  }

  async function save(ev){
    ev.preventDefault(); setSaving(true);
    try{
      const payload={...form,assigned_to_id:form.assigned_to_id?parseInt(form.assigned_to_id):null,order_fk:form.order_fk?parseInt(form.order_fk):null};
      if(form.id){
        await api('/tasks/'+form.id,{method:'PATCH',body:JSON.stringify(payload)});
      }else{
        await api('/tasks',{method:'POST',body:JSON.stringify(payload)});
      }
      setForm(null); load();
    }catch(x){alert(x.message)}
    setSaving(false);
  }

  async function del(id){
    if(!confirm('Hapus task ini?')) return;
    try{await api('/tasks/'+id,{method:'DELETE'});load();}catch(x){alert(x.message)}
  }

  const f2=filtered();
  const openCount=visibleTasks().filter(t=>t.status==='OPEN').length;
  const progressCount=visibleTasks().filter(t=>t.status==='IN_PROGRESS').length;

  function userName(id){const u=users.find(u=>u.id===id);return u?.name||'Unassigned'}
  function orderLabel(id){const o=orders.find(o=>o.id===id);return o?.order_id||''}

  return <div className="page">
    <div className="page-title"><div><h1>{me?.role==='CMO_SUPPORT'?'Tugas Saya':isPIC?'My Tasks':'Task Management'}</h1><p>{openCount} open • {progressCount} in progress{isPIC?' (tugas saya saja)':''}</p></div>
      {!isPIC && <button className="btn primary" onClick={()=>setForm({...empty})}><Plus size={16}/> Tambah Task</button>}</div>
    {err&&<div className="notice danger">{err}</div>}

    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/><input placeholder="Cari judul task, assignee..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">{statusOpts.map(s=><button key={s} className={'pill '+(filterStatus===s?'active '+s.toLowerCase():'')} onClick={()=>setFilterStatus(filterStatus===s?'':s)}>{s.replace('_',' ')}</button>)}</div>
    </div>

    <div className="table-scroll"><table><thead><tr><th>Task</th><th>Assignee</th><th>Order</th><th>Due Date</th><th>Status</th><th>Aksi</th></tr></thead>
    <tbody>{f2.map(t=><tr key={t.id}>
      <td><b>{t.title}</b></td>
      <td>{userName(t.assigned_to_id)}</td>
      <td>{orderLabel(t.order_fk)||'-'}</td>
      <td>{t.due_date||'-'}</td>
      <td><span className={'badge '+(t.status==='OPEN'?'red':t.status==='IN_PROGRESS'?'amber':t.status==='DONE'?'green':'gray')}>{t.status.replace('_',' ')}</span></td>
      <td className="td-action">
        {!isPIC && <button className="icon-btn" onClick={()=>setForm({...t,assigned_to_id:t.assigned_to_id||'',order_fk:t.order_fk||'',due_date:t.due_date||''})} title="Edit"><Edit2 size={15}/></button>}
        {t.status!=='DONE'&&t.status!=='CANCELLED'&&<button className="icon-btn" onClick={async()=>{try{await api('/tasks/'+t.id,{method:'PATCH',body:JSON.stringify({status:isPIC?'DONE':'IN_PROGRESS'})});load()}catch(e){setErr(e.message)}}} title={isPIC?'Selesaikan':'Set In Progress'}><CheckCircle size={15} color="#16a34a"/></button>}
      </td>
    </tr>)}
    {f2.length===0&&<tr><td colSpan={6} className="empty">{isPIC?'Tidak ada task untuk anda':'Tidak ada task'}</td></tr>}</tbody></table></div>

    {form&&<div className="modal-bg" onClick={()=>setForm(null)}>
    <div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.id?'Edit':'Tambah'} Task</h2><button className="icon-btn" onClick={()=>setForm(null)}><X size={18}/></button></div>
      <form onSubmit={save}>
        <label>Judul Task *<input required value={form.title} onChange={e=>setForm({...form,title:e.target.value})} placeholder="Deskripsi task"/></label>
        <div className="form-grid">
          <label>Assignee<select value={form.assigned_to_id} onChange={e=>setForm({...form,assigned_to_id:e.target.value})}><option value="">Belum ditugaskan</option>{users.map(u=><option key={u.id} value={u.id}>{u.name} ({u.role.replace('_',' ')})</option>)}</select></label>
          <label>Order FK<select value={form.order_fk} onChange={e=>setForm({...form,order_fk:e.target.value})}><option value="">Tidak terkait order</option>{orders.map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}</select></label>
          <label>Due Date<input type="date" value={form.due_date} onChange={e=>setForm({...form,due_date:e.target.value})}/></label>
        </div>
        <label>Status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>{statusOpts.map(s=><option key={s}>{s}</option>)}</select></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={saving}><Check size={14}/> {saving?'Menyimpan...':'Simpan'}</button></div>
      </form>
    </div></div>}
  </div>
}