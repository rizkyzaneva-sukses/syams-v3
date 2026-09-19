import React,{useEffect,useMemo,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import {printingStatusBounds} from '../printingOps';
import {BarChart3,Clock,RefreshCw,ShieldAlert,Truck,Factory} from 'lucide-react';

/* Revisi #41/#42/#46/#47 — Printing (Iman).
   Satu papan kerja: target harian Printing/Bordir vs realisasi, batas transisi
   status yang sah, kelayakan job (assignment/SPK/rute), makloon embroidery,
   exception Printing dan jejak audit. Semua angka datang dari server
   (/printing/daily-target + /printing/eligibility); halaman ini tidak menghitung
   ulang dan tidak menyediakan pilihan status bebas. */

const RATE_FIELDS=['rate','rate_per_piece','payable','payment'];
const fmt=n=>n==null?'—':Number(n).toLocaleString('id-ID');
const pct=n=>n==null?'—':n+'%';

function tone(value){
  if(['ACHIEVED','ELIGIBLE','DONE','IN_PROCESS'].includes(value)) return 'green';
  if(['PARTIAL','HOLD','WAITING','NO_TARGET'].includes(value)) return 'amber';
  if(['NOT_STARTED','BLOCKED','RED'].includes(value)) return 'red';
  return 'gray';
}

export default function PrintingDailyTargetPage(){
  const role=useRole();
  const [target,setTarget]=useState(null),[elig,setElig]=useState(null);
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [day,setDay]=useState('');
  const [onlyBlocked,setOnlyBlocked]=useState(false);

  async function load(){
    setBusy(true); setErr('');
    try{
      const q=day?('?on_date='+day):'';
      const [t,e]=await Promise.all([api('/printing/daily-target'+q),api('/printing/eligibility')]);
      setTarget(t); setElig(e);
    }catch(x){setErr(x.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  const rows=target?.rows||[];
  const jobs=elig?.jobs||[];
  const shownJobs=useMemo(()=>onlyBlocked?jobs.filter(j=>!j.eligible):jobs,[jobs,onlyBlocked]);
  const makloon=target?.makloon||{vendors:[],required_fields:[]};

  function statusOptions(job){
    // Pilihan status datang dari server; kalau server belum menjawab, jatuh ke
    // kontrak lokal yang sama dengan yang dipaksakan API (bukan teks bebas).
    const allowed=job.allowed_next_statuses||[];
    return allowed.length?allowed:printingStatusBounds.statusOptions(job.current_status);
  }

  return <div className="page">
    <div className="page-title">
      <div><h1>Printing — Target Harian & Batas Proses</h1>
        <p>Target harian Printing/Bordir milik Iman dibandingkan realisasi sah; status yang boleh dipilih terbatas pada transisi yang sah.</p></div>
      <div style={{display:'flex',gap:8,alignItems:'center'}}>
        <label className="check-label" style={{margin:0}}>
          <input type="date" value={day} onChange={e=>setDay(e.target.value)}/> Tanggal
        </label>
        <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
      </div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {!target&&!err&&<div className="page">Memuat target harian…</div>}

    {target&&<>
      <div className="cards">
        <div className={'stat '+(target.totals.attainment_percent>=100?'green':target.totals.attainment_percent?'amber':'gray')}>
          <strong>{pct(target.totals.attainment_percent)}</strong><span>Pencapaian target {target.on_date}</span></div>
        <div className="stat blue"><strong>{fmt(target.totals.target_qty)}</strong><span>Target (unit)</span></div>
        <div className="stat"><strong>{fmt(target.totals.realised_qty)}</strong><span>Realisasi sah (unit)</span></div>
        <div className={'stat '+(target.mismatch_count?'amber':'green')}>
          <strong>{target.mismatch_count}</strong><span>Mismatch target vs realisasi</span></div>
        <div className={'stat '+(target.exception_count?'red':'green')}>
          <strong>{target.exception_count}</strong><span>Exception Printing terbuka</span></div>
      </div>

      <section className="panel">
        <div className="panel-head"><h2><BarChart3 size={17}/> Target vs realisasi per proses</h2>
          <span>target ditetapkan Iman lewat target_date; realisasi hanya dari output sah</span></div>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>Order ID</th><th>Article ID</th><th>Proses</th><th>Target</th><th>Realisasi</th>
            <th>Capaian</th><th>Sisa target</th><th>Remaining WIP</th><th>Status</th><th>Blocker</th>
          </tr></thead>
          <tbody>
            {rows.map(row=><tr key={row.job_id}>
              <td>{row.order_id}</td>
              <td>{row.article_code}</td>
              <td><span className={'badge '+(row.process.toLowerCase().includes('bordir')?'blue':'gray')}>{row.process}</span></td>
              <td>{fmt(row.target_qty)}</td>
              <td>{fmt(row.realised_qty)}</td>
              <td>{pct(row.attainment_percent)}</td>
              <td>{fmt(row.remaining_vs_target)}</td>
              <td>{fmt(row.remaining_wip)}</td>
              <td><span className={'badge '+tone(row.status)}>{row.status}</span></td>
              <td>{row.blockers&&row.blockers.length?<span className="badge red">{row.blockers[0].code}</span>:'—'}</td>
            </tr>)}
            {!rows.length&&<tr><td colSpan={10} className="empty">Belum ada job Printing/Bordir.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2><Clock size={17}/> Mismatch & rekonsiliasi harian</h2>
            <span>{target.daily_reconciliation.identity}</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Kode</th><th>Rincian</th></tr></thead>
            <tbody>
              {target.mismatch.map((item,i)=><tr key={i}>
                <td><span className="badge amber">{item.code}</span></td><td>{item.detail}</td></tr>)}
              {!target.mismatch.length&&<tr><td colSpan={2} className="empty">Target hari ini terpenuhi / belum ada target.</td></tr>}
            </tbody>
          </table></div>
          <small className="muted">
            {target.daily_reconciliation.rows_without_target} job tanpa target · {fmt(target.daily_reconciliation.unresolved_reject_qty)} unit reject belum tuntas ·
            seimbang: {String(target.daily_reconciliation.balanced)}
          </small>
        </section>

        <section className="panel">
          <div className="panel-head"><h2><Truck size={17}/> Makloon Embroidery</h2>
            <span>cost milik CFO: {makloon.cost_owner}</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Vendor</th><th>Kirim</th><th>Kembali</th><th>Accepted</th><th>Rejected</th><th>Outstanding WIP</th></tr></thead>
            <tbody>
              {makloon.vendors.map(v=><tr key={v.vendor}>
                <td>{v.vendor}</td><td>{fmt(v.qty_sent)}</td><td>{fmt(v.qty_returned)}</td>
                <td>{fmt(v.qty_accepted)}</td><td>{fmt(v.qty_rejected)}</td>
                <td><span className={'badge '+(v.outstanding_external_wip?'amber':'green')}>{fmt(v.outstanding_external_wip)}</span></td>
              </tr>)}
              {!makloon.vendors.length&&<tr><td colSpan={6} className="empty">Belum ada pekerjaan makloon tercatat (vendor di luar Printing).</td></tr>}
            </tbody>
          </table></div>
          <small className="muted">Outstanding external WIP total: {fmt(makloon.outstanding_external_wip)} · {makloon.note}</small>
        </section>
      </div>
    </>}

    {elig&&<>
      <section className="panel">
        <div className="panel-head">
          <h2><ShieldAlert size={17}/> Kelayakan job & transisi status</h2>
          <label className="check-label"><input type="checkbox" checked={onlyBlocked} onChange={e=>setOnlyBlocked(e.target.checked)}/> Hanya yang terblokir</label>
        </div>
        <p className="muted">{elig.eligibility_rule[0]} Status terdaftar: {elig.registered_statuses.join(', ')} — tidak ada pilihan status bebas. Proses milik Printing: {printingStatusBounds.owned.join(' & ')}.</p>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>Job ID</th><th>Order</th><th>Artikel</th><th>Proses</th><th>PIC/role</th><th>SPK</th>
            <th>Status</th><th>Aksi sah</th><th>Status berikutnya</th><th>Handoff</th><th>Eligible</th>
          </tr></thead>
          <tbody>
            {shownJobs.map(job=><tr key={job.job_id}>
              <td>{job.job_id}</td>
              <td>{job.order_id}</td>
              <td>{job.article_code}</td>
              <td>{job.stage}</td>
              <td>{job.assignee||job.assigned_role}</td>
              <td>{job.requirement_version||'—'}</td>
              <td><span className={'badge '+tone(job.current_status)}>{job.current_status}</span></td>
              <td>{job.allowed_actions.length?job.allowed_actions.map(a=><span className="badge gray" key={a}>{a}</span>):'—'}</td>
              <td>{statusOptions(job).map(s=><span className={'badge '+tone(s)} key={s}>{s}</span>)}</td>
              <td>{job.handoff.next_stage?<>{job.handoff.next_stage} {job.handoff.reconciled?<span className="badge green">reconciled</span>:<span className="badge amber">belum</span>}</>:'—'}</td>
              <td>{job.eligible?<span className="badge green">boleh</span>:<span className="badge red">{job.blockers[0]?.code||'blocked'}</span>}</td>
            </tr>)}
            {!shownJobs.length&&<tr><td colSpan={11} className="empty">Tidak ada job Printing/Bordir untuk filter ini.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2><Factory size={17}/> Batas domain</h2><span>rate & payable = CFO</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Field</th><th>Pemilik</th><th>Printing boleh ubah</th><th>Catatan</th></tr></thead>
            <tbody>
              {elig.domain_boundaries.map(b=><tr key={b.field}>
                <td>{b.field}</td>
                <td><span className={'badge '+(RATE_FIELDS.includes(b.field)?'blue':'gray')}>{b.owner_role}</span></td>
                <td>{b.printing_allowed?<span className="badge green">boleh</span>:<span className="badge red">tidak</span>}</td>
                <td>{b.note}</td>
              </tr>)}
            </tbody>
          </table></div>
          <small className="muted">rate: {String(target?.rate_boundary?.printing_can_change_rate)} · {elig.read_only_boundaries[0]}</small>
        </section>

        <section className="panel">
          <div className="panel-head"><h2><ShieldAlert size={17}/> Exception Printing</h2>
            <span>{target?target.exception_count:0} terbuka</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Severity</th><th>Kategori</th><th>Judul</th><th>Owner</th><th>Sumber</th><th>Due</th></tr></thead>
            <tbody>
              {(target?.exceptions||[]).map(item=><tr key={item.id}>
                <td><span className={'badge '+(item.severity==='RED'?'red':'amber')}>{item.severity}</span></td>
                <td>{item.category}</td><td>{item.title}</td>
                <td>{item.owner_name||item.owner_role||'—'}</td>
                <td>{item.source_entity||'—'}</td><td>{item.due_date||'—'}</td>
              </tr>)}
              {!(target?.exceptions||[]).length&&<tr><td colSpan={6} className="empty">Tidak ada exception Printing terbuka.</td></tr>}
            </tbody>
          </table></div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Audit perubahan status (Production Movement)</h2>
          <span>{target?target.audit_count:0} entri terakhir</span></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Waktu</th><th>Aktor</th><th>Aksi</th><th>Order</th><th>Dari</th><th>Ke</th><th>Alasan</th></tr></thead>
          <tbody>
            {(target?.audit||[]).map(entry=><tr key={entry.id}>
              <td><small>{entry.created_at||'—'}</small></td>
              <td>{entry.actor_id}</td><td>{entry.action}</td>
              <td>{entry.order_id?<Link to={'/orders/'+entry.order_id}>{entry.order_id}</Link>:'—'}</td>
              <td>{entry.previous_status||'—'}</td><td>{entry.new_status||'—'}</td>
              <td>{entry.reason||'—'}</td>
            </tr>)}
            {!(target?.audit||[]).length&&<tr><td colSpan={7} className="empty">Belum ada perubahan status tercatat.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Aturan yang berlaku</h2><span>dipaksakan di API, bukan hanya di UI</span></div>
        <ul className="quick-links">
          {elig.eligibility_rule.map((rule,i)=><li key={i}>{rule}</li>)}
          <li>Lifecycle task: OPEN → START/IN_PROGRESS → UPDATE → SUBMIT_RESULT → DONE; task tidak boleh DONE sebelum output, reject, remaining WIP, evidence dan handoff terekonsiliasi.</li>
          <li>Internal production milik {target?.internal_production?.owner_role}; mesin/shift: {String(target?.internal_production?.machine_shift_columns_present)}.</li>
          <li>Peran Anda: {role}.</li>
        </ul>
      </section>
    </>}
  </div>;
}
