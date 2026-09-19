import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';
import {History,Paperclip,ShieldCheck,Lock,RefreshCw,AlertTriangle,ChevronDown,ChevronRight,FileCheck2} from 'lucide-react';

/* Revisi #34 / #36 / #38 — VERSIONED SAMPLE LIFECYCLE, EVIDENCE & IMMUTABILITY.
 *
 * Halaman baca (read-only). Semua angka datang dari server; halaman ini tidak
 * menghitung ulang status dan tidak pernah menawarkan Edit/Hapus pada versi yang
 * sudah diputuskan buyer.
 *
 *  #34  Versioned Sample Lifecycle & Evidence
 *       Per artikel: versi terakhir, jumlah + nama file evidence, kelengkapan,
 *       keputusan buyer, pelaku, waktu, dan next action.
 *  #36  Sinkronisasi Sample / Task / Order Flow / Master
 *       Baris yang status Sample-nya tidak sejalan dengan gate Order Flow
 *       ditandai "mismatch" supaya tidak ada lagi "Article Sample APPROVED,
 *       progress 0%".
 *  #38  Immutability, Revision & Audit
 *       Versi APPROVED (dan versi yang sudah dikunci SPK) ditandai immutable,
 *       field yang terkunci ditampilkan, dan aksinya hanya CREATE NEW VERSION /
 *       REVISE / VOID — bukan EDIT.
 */

const TONE={APPROVED:'green',REJECTED:'red',REVISION:'red',PROCESS:'amber',IN_PROCESS:'amber',PENDING:'amber'};

const STATE_LABEL={
  OPEN:'Terbuka',
  LOCKED_BY_SPK:'Dikunci SPK',
  IMMUTABLE_APPROVED:'Final · Approved',
  IMMUTABLE_DECIDED:'Final · Keputusan buyer',
};

function fmt(value){
  if(!value) return '—';
  const raw=typeof value==='string'&&!value.endsWith('Z')&&!value.includes('+')?value+'Z':value;
  const date=new Date(raw);
  return Number.isNaN(date.getTime())?'—':date.toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'});
}

function day(value){return value?String(value).slice(0,10):'—'}

function EvidenceCell({row}){
  const names=row.evidence_file_names||[];
  if(!row.evidence_count) return <span className="badge amber">Belum ada</span>;
  return <>
    <span className={'badge '+(row.evidence_complete?'blue':'amber')}>{row.evidence_count} file</span>
    <small title={names.join(', ')}>{names.slice(0,2).join(', ')}{names.length>2?` +${names.length-2}`:''}</small>
  </>;
}

function DecisionCell({row}){
  if(!row.buyer_decision) return <><span className="badge amber">Menunggu buyer</span>{row.blocker&&<small>{row.blocker}</small>}</>;
  return <>
    <span className={'badge '+(row.buyer_decision==='APPROVED'?'green':'red')}>{row.buyer_decision}</span>
    <small>{row.decision_by||'aktor tidak tercatat'}</small>
    <small>{fmt(row.decision_at)}</small>
  </>;
}

function ImmutableTag({row}){
  if(!row.immutable) return <span className="badge blue">Boleh dikoreksi</span>;
  return <>
    <span className="badge red" title={row.immutability_reason}><Lock size={12}/> {STATE_LABEL[row.immutability_state]||row.immutability_state}</span>
    <small>{row.requires_new_version?'Perubahan harus lewat versi baru':'—'}</small>
  </>;
}

function VersionChain({detail}){
  if(!detail) return null;
  return <div className="table-scroll"><table>
    <thead><tr><th>Versi</th><th>Status</th><th>Evidence</th><th>Keputusan</th><th>Pelaku</th><th>Waktu</th><th>Kunci</th></tr></thead>
    <tbody>{detail.versions.map(version=><tr key={version.sample_id}>
      <td><b>v{version.sample_version}</b>{version.is_latest_version&&<span className="badge blue">terakhir</span>}
        <small>Sample #{version.sample_id}{version.previous_version_sample_id?` · dari #${version.previous_version_sample_id}`:''}</small></td>
      <td><span className={'badge '+(TONE[version.status]||'')}>{version.status}</span><small>{version.stage_label}</small></td>
      <td>{version.evidence_count?version.evidence.map(item=><small key={item.evidence_id}>{item.file_name} · {item.uploaded_by||'—'} · {fmt(item.created_at)}</small>):'Belum ada'}</td>
      <td>{version.buyer_decision||'Menunggu'}{version.decision_reason&&<small>{version.decision_reason}</small>}</td>
      <td>{version.decision_by||'—'}</td>
      <td>{fmt(version.created_at)}</td>
      <td>{version.immutable?<span className="badge red"><Lock size={12}/> {STATE_LABEL[version.immutability_state]||version.immutability_state}</span>:<span className="badge blue">Terbuka</span>}</td>
    </tr>)}</tbody></table></div>;
}

export default function SampleLifecyclePage(){
  const role=useRole();
  const canView=['CEO','CMO_MANAGER','CMO_SUPPORT','COO_MANAGER','SAMPLE_PIC'].includes(role);
  const [summary,setSummary]=useState(null),[decisions,setDecisions]=useState(null);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false),[q,setQ]=useState('');
  const [onlyProblem,setOnlyProblem]=useState(false);
  const [open,setOpen]=useState(null),[detail,setDetail]=useState(null),[detailBusy,setDetailBusy]=useState(false);

  async function load(){
    setBusy(true);
    try{
      const [sum,reg]=await Promise.all([
        api('/cmo/samples-version-summary'),
        api('/cmo/samples-version-decisions'),
      ]);
      setSummary(sum);setDecisions(reg);setErr('');
    }catch(error){setErr(error.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  async function toggle(sampleId){
    if(open===sampleId){setOpen(null);setDetail(null);return}
    setOpen(sampleId);setDetail(null);setDetailBusy(true);setErr('');
    try{setDetail(await api(`/cmo/samples/${sampleId}/versions`))}
    catch(error){setErr(error.message)}
    finally{setDetailBusy(false)}
  }

  const rows=summary?.rows||[];
  const shown=useMemo(()=>rows.filter(row=>{
    if(onlyProblem&&!row.has_mismatch&&row.immutable) return false;
    if(!q) return true;
    const term=q.toLowerCase();
    return [row.article_code,row.order_id,row.buyer,row.status,row.next_action]
      .some(value=>String(value||'').toLowerCase().includes(term));
  }),[rows,q,onlyProblem]);

  const totals=summary?.totals||{};
  const immutableIds=useMemo(()=>new Set((decisions?.rows||[]).map(row=>row.sample_id)),[decisions]);

  if(!canView&&role) return <div className="page"><div className="notice danger">Halaman ini tidak tersedia untuk peran Anda.</div></div>;

  return <div className="page">
    <div className="page-title">
      <div><h1>Versioned Sample Lifecycle</h1>
        <p>Setiap artikel punya versi. Evidence menyimpan pelaku &amp; waktu, dan versi yang sudah disetujui buyer tidak bisa diubah lagi.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> {busy?'Memuat...':'Muat ulang'}</button>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards">
      <div className="stat"><span>Artikel</span><b>{totals.articles??'—'}</b><small>{totals.versions??0} versi total</small></div>
      <div className="stat"><span>Versi final</span><b>{totals.immutable_articles??'—'}</b><small>tidak boleh diubah</small></div>
      <div className="stat"><span>Masih berjalan</span><b>{totals.open_articles??'—'}</b><small>{totals.awaiting_buyer??0} menunggu buyer</small></div>
      <div className="stat"><span>Evidence kurang</span><b>{totals.evidence_incomplete??'—'}</b><small>belum lengkap</small></div>
      <div className="stat"><span>Mismatch flow</span><b>{totals.mismatch??0}</b><small>sample vs Order Flow</small></div>
    </div>

    <div className="filter-bar">
      <div className="search-bar"><History size={16}/><input placeholder="Cari artikel, order, buyer, atau next action..." value={q} onChange={event=>setQ(event.target.value)}/></div>
      <div className="filter-pills">
        <button className={'pill '+(onlyProblem?'active':'')} onClick={()=>setOnlyProblem(!onlyProblem)}>
          {onlyProblem?'Hanya perlu perhatian':'Semua versi'}
        </button>
      </div>
    </div>

    <div className="table-scroll"><table>
      <thead><tr><th>Order / Artikel</th><th>Versi</th><th>Status &amp; Tahap</th><th>Evidence</th><th>Keputusan Buyer</th><th>Kelengkapan</th><th>Pelaku / Waktu</th><th>Next action</th><th>Immutability</th><th></th></tr></thead>
      <tbody>{shown.map(row=><React.Fragment key={row.latest_sample_id}>
        <tr>
          <td>{row.order_id||'—'}<br/><b>{row.article_code||'—'}</b><small>{row.buyer||'—'}{row.sample_required===false?' · tidak wajib sample':''}</small></td>
          <td><b>v{row.latest_version}</b><small>{row.version_count} versi{row.previous_version?` · sebelumnya v${row.previous_version}`:''}</small></td>
          <td><span className={'badge '+(TONE[row.status]||'')}>{row.status}</span><small>{row.stage_label}</small>{row.master_sample_status&&row.master_sample_status!==row.status&&<small>Master: {row.master_sample_status}</small>}</td>
          <td><EvidenceCell row={row}/></td>
          <td><DecisionCell row={row}/></td>
          <td>{row.evidence_complete?<span className="badge green"><FileCheck2 size={12}/> Lengkap</span>:<span className="badge amber">Belum lengkap</span>}
            {row.evidence_gap?.next_action&&<small>{row.evidence_gap.next_action}</small>}</td>
          <td>{row.decision_by||'—'}<small>{row.current_owner} · due {day(row.due_date)}</small></td>
          <td>{row.next_action}{row.has_mismatch&&row.mismatch.map(item=><small key={item.code}><AlertTriangle size={11}/> {item.detail}</small>)}</td>
          <td><ImmutableTag row={row}/></td>
          <td className="td-action">
            <button className="btn sm" onClick={()=>toggle(row.latest_sample_id)}>
              {open===row.latest_sample_id?<ChevronDown size={13}/>:<ChevronRight size={13}/>} Riwayat versi
            </button>
            {row.immutable&&<button className="btn sm" disabled title="Versi final: buat versi baru lewat /cmo/samples"><Lock size={12}/> Tanpa Edit/Hapus</button>}
          </td>
        </tr>
        {open===row.latest_sample_id&&<tr><td colSpan={10}>
          {detailBusy&&<p>Memuat riwayat versi...</p>}
          {detail&&<>
            <p className="notice info">
              Artikel <b>{detail.article_code}</b> punya {detail.version_count} versi.
              Versi terakhir: v{detail.latest_version} (Sample #{detail.latest_sample_id}).
              Status versi ini: {detail.immutability?.immutable
                ? <><b>immutable</b> — {detail.immutability.reason} Aksi yang tersedia: {detail.allowed_actions.join(', ')}.</>
                : <><b>terbuka</b> — {detail.next_action}</>}
            </p>
            {detail.immutability?.locked_fields?.length>0&&
              <p className="notice info"><ShieldCheck size={14}/> Field terkunci: {detail.immutability.locked_fields.join(', ')}</p>}
            {detail.immutability?.immutable&&<p className="notice info"><Paperclip size={14}/> Untuk mengubah PPM/artwork, buat versi sample baru — versi lama tetap tersimpan sebagai bukti approval buyer.</p>}
            <VersionChain detail={detail}/>
          </>}
          {!detail&&!detailBusy&&<p>Riwayat versi tidak tersedia.</p>}
        </td></tr>}
      </React.Fragment>)}
      {shown.length===0&&<tr><td colSpan={10} className="empty">Tidak ada sample yang cocok.</td></tr>}</tbody></table></div>

    {decisions&&decisions.rows.length>0&&<>
      <h2>Versi yang tidak boleh diubah <small>({decisions.totals.immutable_versions})</small></h2>
      <p className="notice info">Versi di bawah ini bersifat final. UI tidak menyediakan Edit/Hapus; perubahan hanya lewat {decisions.totals.supported_actions.join(' / ')}.</p>
      <div className="table-scroll"><table>
        <thead><tr><th>Sample</th><th>Order / Artikel</th><th>Status</th><th>Alasan terkunci</th><th>Field terkunci</th><th>Aksi yang sah</th><th>Pelaku keputusan</th></tr></thead>
        <tbody>{decisions.rows.map(row=><tr key={row.sample_id}>
          <td><b>#{row.sample_id}</b>{immutableIds.has(row.sample_id)&&<small>{STATE_LABEL[row.immutability_state]||row.immutability_state}</small>}</td>
          <td>{row.order_id||'—'}<br/><b>{row.article_code||'—'}</b></td>
          <td><span className={'badge '+(TONE[row.status]||'')}>{row.status}</span></td>
          <td>{row.reason}</td>
          <td>{(row.locked_fields||[]).join(', ')||'—'}</td>
          <td>{(row.allowed_actions||[]).join(', ')}</td>
          <td>{row.decision_by||'—'}<small>{fmt(row.decision_at)}</small></td>
        </tr>)}</tbody></table></div>
    </>}
  </div>;
}
