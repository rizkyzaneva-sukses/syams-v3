import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';

/* BLUEPRINT §3.1/§3.2 — Lead/Opportunity + Sales Target (workspace Cecep/Deby).
   Tiga tab:
   - Leads: daftar + filter (status/source/owner), form tambah, tombol konversi
     ke Opportunity.
   - Pipeline: tabel/kanban per stage dengan nilai & probabilitas, tombol Win/Lose.
   - Target: tabel target vs aktual per periode (aktual dari order yang ada).

   Hak tulis ditegakkan juga di server: lead/opportunity = CMO_MANAGER/CMO_SUPPORT,
   sales target = CFO_MANAGER. UI hanya menyembunyikan tombol; server tetap menolak. */

const money=n=>n==null?'—':'Rp '+Number(n).toLocaleString('id-ID',{maximumFractionDigits:0});
const TODAY=new Date().toISOString().slice(0,10);
const THIS_PERIOD=TODAY.slice(0,7);

const CRM_WRITE=['CMO_MANAGER','CMO_SUPPORT'];
const TARGET_WRITE=['CFO_MANAGER'];

const LEAD_SOURCES=['REFERRAL','WEBSITE','WHATSAPP','EXHIBITION','COLD_CALL','REPEAT','LAINNYA'];
const LEAD_STATUSES=['NEW','CONTACTED','QUALIFIED','UNQUALIFIED','CONVERTED'];
const STAGES=['PROSPECT','QUALIFICATION','PROPOSAL','NEGOTIATION','WON','LOST'];
const STAGE_TONE={PROSPECT:'gray',QUALIFICATION:'blue',PROPOSAL:'amber',NEGOTIATION:'amber',WON:'green',LOST:'red'};

export default function CRMPage(){
  const role=useRole();
  const canCrm=CRM_WRITE.includes(role);
  const canTarget=TARGET_WRITE.includes(role);
  const [tab,setTab]=useState('leads');
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [users,setUsers]=useState([]);
  const ownerName=id=>users.find(u=>u.id===id)?.name||id||'—';

  useEffect(()=>{api('/users').then(setUsers).catch(()=>setUsers([]))},[]);

  return <div className="page">
    <div className="page-title">
      <div><h1>CRM — Lead &amp; Pipeline</h1>
        <p>Lead source, pipeline dari prospek, dan target penjualan per PIC.</p></div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="filter-bar"><div className="filter-pills">
      {[['leads','Leads'],['pipeline','Pipeline'],['target','Target']].map(([k,l])=>
        <button key={k} className={'pill'+(tab===k?' active open':'')} onClick={()=>setTab(k)}>{l}</button>)}
    </div></div>

    {tab==='leads'&&<LeadsTab canWrite={canCrm} users={users} ownerName={ownerName} setErr={setErr} setBusy={setBusy}/>}
    {tab==='pipeline'&&<PipelineTab canWrite={canCrm} users={users} ownerName={ownerName} setErr={setErr} setBusy={setBusy}/>}
    {tab==='target'&&<TargetTab canWrite={canTarget} users={users} ownerName={ownerName} setErr={setErr} setBusy={setBusy}/>}
  </div>;
}

/* ── Tab Leads ─────────────────────────────────────────────────────────────── */
function LeadsTab({canWrite,ownerName,setErr,setBusy}){
  const [rows,setRows]=useState([]),[filters,setFilters]=useState({status:'',source:'',owner_id:''});
  const [form,setForm]=useState(null);

  async function load(){
    setBusy(true);setErr('');
    try{
      const qs=new URLSearchParams(Object.entries(filters).filter(([,v])=>v!=='')).toString();
      const d=await api('/crm/leads'+(qs?'?'+qs:''));
      setRows(d.rows||[]);
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[filters.status,filters.source,filters.owner_id]);

  async function save(){
    await api('/crm/leads',{method:'POST',body:JSON.stringify({
      source:form.source,company_name:form.company_name,contact_name:form.contact_name,
      phone:form.phone,email:form.email,city:form.city||null,
      interested_product:form.interested_product||null,
      estimated_value:Number(form.estimated_value||0),status:form.status,
      owner_id:form.owner_id?Number(form.owner_id):null,
      next_followup_date:form.next_followup_date||null,notes:form.notes||null,
    })});
    setForm(null);load();
  }
  async function convert(id){
    if(!window.confirm('Konversi lead ini menjadi Opportunity?'))return;
    setBusy(true);setErr('');
    try{await api('/crm/leads/'+id+'/convert',{method:'POST',body:JSON.stringify({})});load()}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  return <>
    {canWrite&&!form&&<button className="btn primary" style={{marginBottom:14}}
      onClick={()=>setForm({source:'LAINNYA',company_name:'',contact_name:'',phone:'',email:'',
        city:'',interested_product:'',estimated_value:'0',status:'NEW',owner_id:'',
        next_followup_date:'',notes:''})}>+ Lead Baru</button>}

    {form&&<section className="panel"><h2>Lead Baru</h2>
      <div className="form-grid">
        <label>Sumber<select value={form.source} onChange={e=>setForm({...form,source:e.target.value})}>
          {LEAD_SOURCES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label>Perusahaan<input value={form.company_name} onChange={e=>setForm({...form,company_name:e.target.value})}/></label>
        <label>Kontak<input value={form.contact_name} onChange={e=>setForm({...form,contact_name:e.target.value})}/></label>
        <label>Telepon<input value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></label>
        <label>Email<input value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label>
        <label>Kota<input value={form.city} onChange={e=>setForm({...form,city:e.target.value})}/></label>
        <label>Produk Diminati<input value={form.interested_product} onChange={e=>setForm({...form,interested_product:e.target.value})}/></label>
        <label>Estimasi Nilai<input type="number" value={form.estimated_value} onChange={e=>setForm({...form,estimated_value:e.target.value})}/></label>
        <label>Status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>
          {LEAD_STATUSES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label>PIC<input value={form.owner_id} onChange={e=>setForm({...form,owner_id:e.target.value})} placeholder="user id (opsional)"/></label>
        <label>Follow-up Berikutnya<input type="date" value={form.next_followup_date} onChange={e=>setForm({...form,next_followup_date:e.target.value})}/></label>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>setErr(e.message))}>Simpan</button></div>
    </section>}

    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Status
        <select value={filters.status} onChange={e=>setFilters({...filters,status:e.target.value})}>
          <option value="">semua</option>{LEAD_STATUSES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Sumber
        <select value={filters.source} onChange={e=>setFilters({...filters,source:e.target.value})}>
          <option value="">semua</option>{LEAD_SOURCES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>PIC ID
        <input value={filters.owner_id} onChange={e=>setFilters({...filters,owner_id:e.target.value})}/></label>
    </div>

    <section className="panel">
      <div className="panel-head"><h2>Daftar Lead</h2><span>{rows.length} baris</span></div>
      <div className="table-scroll"><table><thead><tr>
        <th>No Lead</th><th>Sumber</th><th>Perusahaan</th><th>Kontak</th><th>Kota</th>
        <th>Produk</th><th style={{textAlign:'right'}}>Estimasi</th><th>Status</th>
        <th>PIC</th><th>Follow-up</th>{canWrite&&<th>Aksi</th>}
      </tr></thead><tbody>
        {rows.map(r=><tr key={r.id}>
          <td><b>{r.lead_no}</b></td>
          <td><span className="badge gray">{r.source}</span></td>
          <td>{r.company_name}</td>
          <td>{r.contact_name}<br/><small>{r.phone} · {r.email}</small></td>
          <td>{r.city||'—'}</td>
          <td>{r.interested_product||'—'}</td>
          <td style={{textAlign:'right'}}>{money(r.estimated_value)}</td>
          <td><span className={'badge '+(r.status==='CONVERTED'?'green':r.status==='UNQUALIFIED'?'red':'blue')}>{r.status}</span></td>
          <td>{r.owner_name||ownerName(r.owner_id)}</td>
          <td>{r.next_followup_date||'—'}</td>
          {canWrite&&<td>{r.status!=='CONVERTED'
            ?<button className="btn" onClick={()=>convert(r.id)}>Konversi</button>
            :<span className="badge green">Sudah</span>}</td>}
        </tr>)}
        {!rows.length&&<tr><td colSpan={canWrite?11:10} className="empty">Belum ada lead.</td></tr>}
      </tbody></table></div>
    </section>
  </>;
}

/* ── Tab Pipeline ──────────────────────────────────────────────────────────── */
function PipelineTab({canWrite,ownerName,setErr,setBusy}){
  const [rows,setRows]=useState([]),[stage,setStage]=useState(''),[summary,setSummary]=useState(null);
  const [form,setForm]=useState(null);

  async function load(){
    setBusy(true);setErr('');
    try{
      const d=await api('/crm/opportunities'+(stage?'?stage='+stage:''));
      setRows(d.rows||[]);
      setSummary(await api('/crm/pipeline-summary'));
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[stage]);

  async function save(){
    await api('/crm/opportunities',{method:'POST',body:JSON.stringify({
      buyer_name:form.buyer_name,stage:form.stage,
      estimated_value:Number(form.estimated_value||0),
      probability_percent:form.probability_percent===''?null:Number(form.probability_percent),
      expected_close_date:form.expected_close_date||null,
      owner_id:form.owner_id?Number(form.owner_id):null,
    })});
    setForm(null);load();
  }
  async function act(id,action,body){
    setBusy(true);setErr('');
    try{await api('/crm/opportunities/'+id+'/'+action,{method:'POST',body:JSON.stringify(body||{})});load()}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  function win(id){if(window.confirm('Tandai opportunity ini WON?'))act(id,'win')}
  function lose(id){const r=window.prompt('Alasan kalah (wajib):');if(r&&r.trim())act(id,'lose',{lost_reason:r.trim()})}
  function toOrder(id){const v=window.prompt('Order ID (angka) untuk ditautkan:');if(v&&String(v).trim())act(id,'convert-to-order',{order_id:Number(v)})}

  return <>
    {canWrite&&!form&&<button className="btn primary" style={{marginBottom:14}}
      onClick={()=>setForm({buyer_name:'',stage:'PROSPECT',estimated_value:'0',probability_percent:'',expected_close_date:'',owner_id:''})}>+ Opportunity Baru</button>}

    {form&&<section className="panel"><h2>Opportunity Baru</h2>
      <div className="form-grid">
        <label>Buyer<input value={form.buyer_name} onChange={e=>setForm({...form,buyer_name:e.target.value})}/></label>
        <label>Stage<select value={form.stage} onChange={e=>setForm({...form,stage:e.target.value})}>
          {STAGES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label>Estimasi Nilai<input type="number" value={form.estimated_value} onChange={e=>setForm({...form,estimated_value:e.target.value})}/></label>
        <label>Probabilitas %<input type="number" min="0" max="100" value={form.probability_percent} onChange={e=>setForm({...form,probability_percent:e.target.value})} placeholder="auto per stage"/></label>
        <label>Perkiraan Closing<input type="date" value={form.expected_close_date} onChange={e=>setForm({...form,expected_close_date:e.target.value})}/></label>
        <label>PIC<input value={form.owner_id} onChange={e=>setForm({...form,owner_id:e.target.value})} placeholder="user id"/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>setErr(e.message))}>Simpan</button></div>
    </section>}

    {summary&&<div className="cards">
      {summary.opportunities.stages.map(s=><div className={'stat '+(STAGE_TONE[s.stage]==='red'?'red':STAGE_TONE[s.stage]==='green'?'green':'blue')} key={s.stage}>
        <strong>{s.count}</strong><span>{s.stage} · {money(s.total_value)}<br/>weighted {money(s.weighted_value)}</span></div>)}
    </div>}

    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Stage
        <select value={stage} onChange={e=>setStage(e.target.value)}>
          <option value="">semua</option>{STAGES.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
    </div>

    <section className="panel">
      <div className="panel-head"><h2>Pipeline per Stage</h2><span>{rows.length} opportunity</span></div>
      <div className="table-scroll"><table><thead><tr>
        <th>No Opp</th><th>Buyer</th><th>Stage</th><th style={{textAlign:'right'}}>Nilai</th>
        <th>Probabilitas</th><th style={{textAlign:'right'}}>Weighted</th><th>Closing</th><th>PIC</th>
        <th>Order</th><th>Alasan Kalah</th>{canWrite&&<th>Aksi</th>}
      </tr></thead><tbody>
        {rows.map(r=><tr key={r.id}>
          <td><b>{r.opportunity_no}</b></td>
          <td>{r.buyer_name}</td>
          <td><span className={'badge '+(STAGE_TONE[r.stage]||'gray')}>{r.stage}</span></td>
          <td style={{textAlign:'right'}}>{money(r.estimated_value)}</td>
          <td>{r.probability_percent}%</td>
          <td style={{textAlign:'right'}}>{money(r.weighted_value)}</td>
          <td>{r.expected_close_date||'—'}</td>
          <td>{r.owner_name||ownerName(r.owner_id)}</td>
          <td>{r.order_id||(r.converted?'—':'')}</td>
          <td>{r.lost_reason||'—'}</td>
          {canWrite&&<td style={{display:'flex',gap:6,flexWrap:'wrap'}}>
            {['WON','LOST'].includes(r.stage)||r.converted?<span className="badge gray">selesai</span>:<>
              <button className="btn" onClick={()=>win(r.id)}>Win</button>
              <button className="btn" onClick={()=>lose(r.id)}>Lose</button>
              <button className="btn" onClick={()=>toOrder(r.id)}>→ Order</button>
            </>}
          </td>}
        </tr>)}
        {!rows.length&&<tr><td colSpan={canWrite?11:10} className="empty">Belum ada opportunity.</td></tr>}
      </tbody></table></div>
    </section>
  </>;
}

/* ── Tab Target ────────────────────────────────────────────────────────────── */
function TargetTab({canWrite,ownerName,setErr,setBusy}){
  const [period,setPeriod]=useState(THIS_PERIOD);
  const [rows,setRows]=useState([]),[summary,setSummary]=useState(null),[form,setForm]=useState(null);

  async function load(){
    setBusy(true);setErr('');
    try{
      const [t,s]=await Promise.all([
        api('/crm/sales-targets?period='+period),
        api('/crm/pipeline-summary?period='+period),
      ]);
      setRows(t.rows||[]);setSummary(s);
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[period]);

  async function save(){
    await api('/crm/sales-targets',{method:'POST',body:JSON.stringify({
      period:form.period,owner_id:form.owner_id?Number(form.owner_id):null,
      owner_name:form.owner_name||null,target_amount:Number(form.target_amount||0),
      target_orders:Number(form.target_orders||0),notes:form.notes||null,
    })});
    setForm(null);load();
  }

  const actual=summary?.sales_target||{};

  return <>
    {canWrite&&!form&&<button className="btn primary" style={{marginBottom:14}}
      onClick={()=>setForm({period,owner_id:'',owner_name:'',target_amount:'0',target_orders:'0',notes:''})}>+ Set Target</button>}

    {form&&<section className="panel"><h2>Target {form.period}</h2>
      <div className="form-grid">
        <label>Periode (YYYY-MM)<input value={form.period} onChange={e=>setForm({...form,period:e.target.value})}/></label>
        <label>PIC ID<input value={form.owner_id} onChange={e=>setForm({...form,owner_id:e.target.value})} placeholder="user id"/></label>
        <label>Nama PIC<input value={form.owner_name} onChange={e=>setForm({...form,owner_name:e.target.value})} placeholder="opsional"/></label>
        <label>Target Nilai<input type="number" value={form.target_amount} onChange={e=>setForm({...form,target_amount:e.target.value})}/></label>
        <label>Target Order<input type="number" value={form.target_orders} onChange={e=>setForm({...form,target_orders:e.target.value})}/></label>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>setErr(e.message))}>Simpan</button></div>
    </section>}

    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Periode
        <input type="month" value={period} onChange={e=>setPeriod(e.target.value)}/></label>
    </div>

    <div className="cards">
      <div className="stat blue"><strong>{money(actual.target_amount)}</strong><span>Target {period}</span></div>
      <div className="stat green"><strong>{money(actual.actual_amount)}</strong><span>Aktual (order)</span></div>
      <div className={'stat '+(actual.attainment_percent==null?'gray':actual.attainment_percent>=100?'green':'amber')}>
        <strong>{actual.attainment_percent==null?'—':actual.attainment_percent+'%'}</strong><span>Pencapaian</span></div>
    </div>

    <section className="panel">
      <div className="panel-head"><h2>Target vs Aktual — {period}</h2>
        <span>{actual.actual_orders??0} order · {actual.target_count??0} target</span></div>
      <div className="table-scroll"><table><thead><tr>
        <th>Periode</th><th>PIC</th><th style={{textAlign:'right'}}>Target Nilai</th>
        <th>Target Order</th><th>Catatan</th>
      </tr></thead><tbody>
        {rows.map(r=><tr key={r.id}>
          <td>{r.period}</td>
          <td>{r.owner_name||ownerName(r.owner_id)}</td>
          <td style={{textAlign:'right'}}>{money(r.target_amount)}</td>
          <td>{r.target_orders}</td>
          <td>{r.notes||'—'}</td>
        </tr>)}
        {!rows.length&&<tr><td colSpan={5} className="empty">Belum ada target untuk periode ini.</td></tr>}
      </tbody></table></div>
    </section>
  </>;
}
