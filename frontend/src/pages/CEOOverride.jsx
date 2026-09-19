import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {RefreshCw,Plus,X,ShieldCheck,Undo2,Info} from 'lucide-react';

/* POLICY & OVERRIDE — empat batas override terkontrol (revisi #74 / CEO-I-005).

   Yang BOLEH dilakukan CEO di sini hanya keputusan/override eksplisit:
   memutus override yang memang wilayahnya, mengakui (acknowledge), dan
   rollback/koreksi. Tidak ada form PO, invoice, delivery, closing, atau BOM —
   transaksi rutin tetap milik Riadi/CFO/COO.

   Tipe override dan siapa pemutusnya datang dari API (`governance`), bukan
   ditulis ulang di UI, supaya RBAC tidak bisa berbeda antara layar dan server. */

const EMPTY={
  override_type:'PRODUCTION_PRIORITY',source_module:'',source_entity:'',source_entity_id:'',
  affected_entity:'',original_value:'',proposed_value:'',reason:'',impact:'',evidence_ref:'',
  scope:'',effective_from:'',effective_to:'',
};

const TYPE_LABEL={
  PRODUCTION_PRIORITY:'Production priority',
  PRICING_EXCEPTION:'Pricing exception',
  SHIPMENT_OUTSTANDING:'Shipment outstanding',
  PURCHASING_EXCEPTION:'Purchasing exception',
};

const STATUS_TONE={REQUESTED:'amber',APPROVED:'green',REJECTED:'red',ROLLED_BACK:'gray'};

export default function CEOOverride(){
  const [data,setData]=useState(null);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [form,setForm]=useState(null),[saving,setSaving]=useState(false);
  const [me,setMe]=useState(null);
  const [rollback,setRollback]=useState(null);

  async function load(){
    setBusy(true);
    try{
      const [list,who]=await Promise.all([api('/ceo/overrides'),api('/auth/me').catch(()=>null)]);
      setData(list); setMe(who); setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  const governance=data?.governance||{};
  const rows=data?.items||[];
  const myRole=me?.role;

  /** Boleh memutus? Governance dari API, bukan asumsi UI. */
  function canDecide(row){
    const decider=governance[row.override_type]?.decider;
    return Boolean(decider)&&decider===myRole&&!row.ceo_decision;
  }
  /** Boleh rollback? Hanya CEO, dan hanya override yang sudah diputus. */
  function canRollback(row){
    return myRole==='CEO'&&Boolean(row.ceo_decision)&&!row.rolled_back_at;
  }

  async function save(ev){
    ev.preventDefault(); setSaving(true);
    try{
      const payload={...form,source_entity_id:form.source_entity_id?parseInt(form.source_entity_id):null};
      await api('/ceo/overrides',{method:'POST',body:JSON.stringify(payload)});
      setForm(null); load();
    }catch(e){alert(e.message)}
    setSaving(false);
  }

  async function decide(row,decision){
    const reason=prompt(`Alasan ${decision==='APPROVED'?'persetujuan':'penolakan'} (wajib, min 5 karakter):`);
    if(!reason||reason.trim().length<5) return;
    try{ await api(`/ceo/overrides/${row.id}/decide`,{method:'POST',body:JSON.stringify({decision,reason:reason.trim()})}); load(); }
    catch(e){alert(e.message)}
  }

  async function acknowledge(row){
    try{ await api(`/ceo/overrides/${row.id}/acknowledge`,{method:'POST'}); load(); }
    catch(e){alert(e.message)}
  }

  async function doRollback(ev){
    ev.preventDefault();
    try{
      await api(`/ceo/overrides/${rollback.id}/rollback`,{method:'POST',
        body:JSON.stringify({reason:rollback.reason,correction_note:rollback.correction_note})});
      setRollback(null); load();
    }catch(e){alert(e.message)}
  }

  return <div className="page">
    <div className="page-title">
      <div><h1>Policy &amp; Override</h1>
        <p>Empat batas override terkontrol. Keputusan/override eksplisit milik CEO — transaksi rutin tetap milik CFO/COO.</p></div>
      <div style={{display:'flex',gap:8}}>
        <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
        <button className="btn primary" onClick={()=>setForm({...EMPTY})}><Plus size={16}/> Ajukan override</button>
      </div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {data?.migration_pending&&<div className="notice"><Info size={14}/> {data.note}</div>}

    {/* Batas override: siapa pemutusnya, apa yang CEO lakukan. */}
    <section className="panel">
      <div className="panel-head"><h2><ShieldCheck size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Batas Override Terkontrol</h2></div>
      <div className="table-scroll"><table><thead><tr>
        <th>Tipe</th><th>Pemutus</th><th>Diberi tahu</th><th>Peran CEO</th>
      </tr></thead><tbody>{Object.entries(governance).map(([type,g])=><tr key={type}>
        <td><b>{TYPE_LABEL[type]||type}</b><br/><small>{type}</small></td>
        <td><span className="badge blue">{g.decider}</span></td>
        <td><small>{(g.informed||[]).join(', ')||'—'}</small></td>
        <td>{g.ceo_decides
          ?<span className="badge green">CEO memutuskan</span>
          :<span className="badge gray">CEO hanya diinformasikan</span>}</td>
      </tr>)}</tbody></table></div>
      <p style={{fontSize:12,color:'#64748b',marginTop:8}}>
        Production priority diputus CEO · pricing exception final oleh CFO dengan CEO informed ·
        shipment outstanding wajib persetujuan CEO · purchasing hanya kasus khusus/override.
      </p>
    </section>

    {/* Registry override. */}
    <section className="panel">
      <div className="panel-head"><h2>Registry Override</h2><span>{rows.length} catatan</span></div>
      {rows.length?<div className="table-scroll"><table><thead><tr>
        <th>Override ID</th><th>Tipe</th><th>Entitas</th><th>Nilai asal → usulan</th>
        <th>Requester</th><th>Scope</th><th>Berlaku</th><th>Status</th><th>Keputusan</th><th>Tindakan</th>
      </tr></thead><tbody>{rows.map(row=><tr key={row.id}>
        <td><b>{row.override_no||`OVR-${row.id}`}</b>{row.is_active&&<><br/><span className="badge green">aktif</span></>}</td>
        <td><span className="badge gray">{TYPE_LABEL[row.override_type]||row.override_type}</span></td>
        <td><small>{row.affected_entity}<br/>{row.source_module}/{row.source_entity}
          {row.source_entity_id?` #${row.source_entity_id}`:''}</small></td>
        <td><small>{row.original_value} → <b>{row.proposed_value}</b></small></td>
        <td><small>#{row.requester_id}<br/>{row.reason}</small></td>
        <td><small>{row.scope}</small></td>
        <td><small>{row.effective_from||'—'}<br/>s/d {row.effective_to||'—'}</small></td>
        <td><span className={'badge '+(STATUS_TONE[row.status]||'gray')}>{row.status}</span></td>
        <td><small>{row.ceo_decision||'—'}{row.ceo_decision_reason?<><br/>{row.ceo_decision_reason}</>:null}
          {row.rolled_back_at&&<><br/><b>rollback</b> {row.correction_note}</>}</small></td>
        <td>
          {canDecide(row)&&<div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
            <button className="btn sm" onClick={()=>decide(row,'APPROVED')}>Setujui</button>
            <button className="btn sm" onClick={()=>decide(row,'REJECTED')}>Tolak</button>
          </div>}
          {row.status==='APPROVED'&&!row.acknowledged_at&&
            <button className="btn sm" onClick={()=>acknowledge(row)}>Acknowledge</button>}
          {canRollback(row)&&
            <button className="btn sm" onClick={()=>setRollback({id:row.id,reason:'',correction_note:''})}>
              <Undo2 size={12}/> Rollback
            </button>}
          {!canDecide(row)&&!canRollback(row)&&!row.acknowledged_at&&<small>—</small>}
        </td>
      </tr>)}</tbody></table></div>:<p className="empty">Belum ada override tercatat.</p>}
    </section>

    {/* Form pengajuan override — hanya registry, bukan transaksi operasional. */}
    {form&&<section className="panel">
      <div className="panel-head"><h2>Ajukan Override</h2>
        <button className="btn sm" onClick={()=>setForm(null)}><X size={13}/> Batal</button></div>
      <form onSubmit={save} className="form-grid">
        <label>Tipe
          <select value={form.override_type} onChange={e=>setForm({...form,override_type:e.target.value})}>
            {Object.keys(governance).map(t=><option key={t} value={t}>{TYPE_LABEL[t]||t}</option>)}
          </select>
        </label>
        <label>Source module<input required value={form.source_module} onChange={e=>setForm({...form,source_module:e.target.value})}/></label>
        <label>Source entity<input required value={form.source_entity} onChange={e=>setForm({...form,source_entity:e.target.value})}/></label>
        <label>Source entity ID<input type="number" value={form.source_entity_id} onChange={e=>setForm({...form,source_entity_id:e.target.value})}/></label>
        <label>Entitas terdampak<input required value={form.affected_entity} onChange={e=>setForm({...form,affected_entity:e.target.value})}/></label>
        <label>Nilai asal<input required value={form.original_value} onChange={e=>setForm({...form,original_value:e.target.value})}/></label>
        <label>Nilai / usulan<input required value={form.proposed_value} onChange={e=>setForm({...form,proposed_value:e.target.value})}/></label>
        <label>Scope<input required value={form.scope} onChange={e=>setForm({...form,scope:e.target.value})}/></label>
        <label>Berlaku dari<input type="date" value={form.effective_from} onChange={e=>setForm({...form,effective_from:e.target.value})}/></label>
        <label>Berlaku sampai<input type="date" value={form.effective_to} onChange={e=>setForm({...form,effective_to:e.target.value})}/></label>
        <label>Bukti (ref)<input value={form.evidence_ref} onChange={e=>setForm({...form,evidence_ref:e.target.value})}/></label>
        <label style={{gridColumn:'1/-1'}}>Dampak
          <textarea required value={form.impact} onChange={e=>setForm({...form,impact:e.target.value})}/></label>
        <label style={{gridColumn:'1/-1'}}>Alasan
          <textarea required minLength={5} value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label>
        <div style={{gridColumn:'1/-1'}}>
          <button className="btn primary" disabled={saving}>{saving?'Menyimpan...':'Ajukan override'}</button>
        </div>
      </form>
    </section>}

    {/* Rollback/koreksi — tanpa hard delete. */}
    {rollback&&<section className="panel">
      <div className="panel-head"><h2>Rollback Override #{rollback.id}</h2>
        <button className="btn sm" onClick={()=>setRollback(null)}><X size={13}/> Batal</button></div>
      <form onSubmit={doRollback} className="form-grid">
        <label style={{gridColumn:'1/-1'}}>Alasan rollback
          <textarea required minLength={5} value={rollback.reason}
            onChange={e=>setRollback({...rollback,reason:e.target.value})}/></label>
        <label style={{gridColumn:'1/-1'}}>Catatan koreksi
          <textarea required minLength={5} value={rollback.correction_note}
            onChange={e=>setRollback({...rollback,correction_note:e.target.value})}/></label>
        <div style={{gridColumn:'1/-1'}}><button className="btn primary">Rollback</button></div>
      </form>
    </section>}
  </div>;
}
