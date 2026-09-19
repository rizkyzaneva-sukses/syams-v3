import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {Search,RefreshCw,IdCard,CalendarClock,ShieldAlert,ClipboardList} from 'lucide-react';
import {
  SUMMARY_ENDPOINT, lifecycleEndpoint, statusLabel, isOpenStatus,
  summaryTiles, statusBreakdown, contractWatchList, migrationQueue,
  attendanceNotice, hrTraceTiles, timelineRows, migrationLabel, employeeLabel,
} from '../hrEmployees';

// Revisi #62 (Employee Master, Migrasi & Lifecycle) dan #67 (Attendance read-only,
// Payroll & Employment Status). Halaman ini SENGAJA read-only: tidak ada form
// tambah/ubah/hapus. Attendance milik CFO dan hanya ditampilkan sebagai catatan.
const softNotice={background:'#fff0cc',color:'#8a5b00',border:'1px solid #ffe0a3'};
const hint={fontSize:12,color:'#64748b'};

export default function HREmployeeMasterPage(){
  const [summary,setSummary]=useState(null);
  const [err,setErr]=useState('');
  const [loading,setLoading]=useState(true);
  const [q,setQ]=useState('');
  const [onlyMigration,setOnlyMigration]=useState(false);
  const [detail,setDetail]=useState(null);
  const [detailErr,setDetailErr]=useState('');

  function load(){
    setLoading(true); setErr('');
    api(SUMMARY_ENDPOINT).then(setSummary).catch(e=>setErr(e.message)).finally(()=>setLoading(false));
  }
  useEffect(load,[]);

  const rows=summary?.employees||[];
  const filtered=useMemo(()=>{
    const term=q.trim().toLowerCase();
    return rows.filter(r=>{
      if(onlyMigration&&!r.needs_migration) return false;
      if(!term) return true;
      return [r.employee_no,r.name,r.division,r.position,r.manager,r.employment_status]
        .some(v=>String(v??'').toLowerCase().includes(term));
    });
  },[rows,q,onlyMigration]);

  function openLifecycle(id){
    const row=rows.find(r=>r.id===id);
    setDetail({loading:true,row});setDetailErr('');
    api(lifecycleEndpoint(id))
      .then(d=>setDetail({loading:false,data:d,row:d.employee}))
      .catch(e=>{setDetailErr(e.message);setDetail({loading:false,row})});
  }

  const migration=migrationQueue(summary);
  const attendance=attendanceNotice(summary);
  const contracts=contractWatchList(summary);

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Employee Master &amp; Lifecycle</h1>
        <p>Revisi #62/#67 — sumber resmi data SDM, kontrak, tanggal masuk/keluar, dan penanda migrasi. Read-only.</p>
      </div>
      <button className="btn" onClick={load} disabled={loading}><RefreshCw size={16}/> Muat ulang</button>
    </div>

    {err&&<div className="notice danger">{err}</div>}
    {loading&&!summary&&<div className="empty">Memuat Employee Master...</div>}

    {summary&&<>
      <div className="cards">
        {summaryTiles(summary).map(t=><div className="stat blue" key={t.label}>
          <div className="stat-icon"><IdCard size={22}/></div>
          <strong>{t.value}</strong><span>{t.label}</span>
        </div>)}
      </div>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2>Per Employment Status</h2></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Status</th><th>Jumlah</th><th>Slot headcount</th></tr></thead>
            <tbody>{statusBreakdown(summary).map(s=><tr key={s.status}>
              <td><b>{s.label}</b><br/><small>{s.status}</small></td>
              <td>{s.count}</td>
              <td><span className={'badge '+(s.open?'green':'gray')}>{s.open?'Terbuka':'Arsip'}</span></td>
            </tr>)}</tbody>
          </table></div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2><CalendarClock size={16}/> Kontrak Akan Habis</h2></div>
          {contracts.length===0
            ? <div className="empty">Tidak ada kontrak yang jatuh tempo dalam {summary.contract_watch?.window_days??30} hari.</div>
            : <div className="table-scroll"><table>
                <thead><tr><th>Karyawan</th><th>Divisi</th><th>Akhir kontrak</th><th>Sisa</th></tr></thead>
                <tbody>{contracts.map(c=><tr key={c.id}>
                  <td><b>{c.employee_no}</b><br/><small>{c.name}</small></td>
                  <td>{c.division||'-'}</td>
                  <td>{c.contract_end_date}</td>
                  <td><span className={'badge '+(c.urgent?'red':'amber')}>{c.daysLabel}</span></td>
                </tr>)}</tbody>
              </table></div>}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2><ShieldAlert size={16}/> Perlu Migrasi / Kelengkapan Data</h2></div>
        {migration.length===0
          ? <div className="empty">Tidak ada baris yang perlu migrasi.</div>
          : <div className="table-scroll"><table>
              <thead><tr><th>NIP</th><th>Nama</th><th>Alasan</th><th></th></tr></thead>
              <tbody>{migration.map(m=><tr key={m.id}>
                <td>{m.employee_no}</td>
                <td><b>{m.name}</b><br/><small>{m.division||'-'} · {m.position||'-'}</small></td>
                <td>{m.reasons.map(r=><div key={r}>• {r}</div>)}</td>
                <td className="td-action"><button className="icon-btn" onClick={()=>openLifecycle(m.id)} title="Lihat lifecycle"><ClipboardList size={15}/></button></td>
              </tr>)}</tbody>
            </table></div>}
        <div style={{...hint,marginTop:8}}>
          Sumber data lama dari Lutfi, deduplikasi dan validasi belum tersedia — lihat REQUESTS/hr_employees.md.
        </div>
      </section>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2>Attendance Summary — Read Only</h2></div>
          <div className="notice" style={attendance.available?undefined:softNotice}>{attendance.text}</div>
          <div style={hint}>
            Attendance dan payroll tetap milik CFO (revisi #67). HR hanya membaca ringkasan untuk
            bahan review/disiplin; halaman ini tidak menyediakan endpoint tulis attendance.
          </div>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Jejak HR (bukan attendance CFO)</h2></div>
          <div className="quick-links">{hrTraceTiles(summary).map(t=>
            <div className="qlink" key={t.label}><ClipboardList size={18}/><div><b>{t.value}</b><small>{t.label}</small></div></div>)}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Employee ({filtered.length} dari {rows.length})</h2></div>
        <div className="filter-bar">
          <div className="search-bar"><Search size={16}/><input placeholder="Cari NIP, nama, divisi, posisi, atasan..." value={q} onChange={e=>setQ(e.target.value)}/></div>
          <button className={'pill'+(onlyMigration?' active red':'')} onClick={()=>setOnlyMigration(v=>!v)}>Hanya perlu migrasi</button>
        </div>
        <div className="table-scroll"><table>
          <thead><tr><th>NIP</th><th>Nama</th><th>Divisi</th><th>Posisi</th><th>Atasan</th><th>Status</th><th>Masuk</th><th>Keluar</th><th>Kontrak s/d</th><th>Perlu migrasi</th><th></th></tr></thead>
          <tbody>{filtered.map(e=><tr key={e.id}>
            <td>{e.employee_no}</td>
            <td><b>{e.name}</b></td>
            <td>{e.division||'-'}</td>
            <td>{e.position||'-'}</td>
            <td>{e.manager||'-'}</td>
            <td><span className={'badge '+(isOpenStatus(e.employment_status)?'green':'gray')}>{statusLabel(e.employment_status)}</span></td>
            <td>{e.join_date||'-'}{e.join_date_source==='CREATED_AT_PROXY'&&<><br/><small>perkiraan dari created_at</small></>}</td>
            <td>{e.exit_date||'-'}</td>
            <td>{e.contract_end_date||'-'}{e.contract_expired&&<><br/><small>kontrak lewat</small></>}</td>
            <td>{e.needs_migration?<span className="badge amber">ya</span>:<span className="badge green">lengkap</span>}</td>
            <td className="td-action"><button className="icon-btn" onClick={()=>openLifecycle(e.id)} title="Lihat lifecycle"><ClipboardList size={15}/></button></td>
          </tr>)}{filtered.length===0&&<tr><td colSpan={11}><div className="empty">Tidak ada karyawan yang cocok.</div></td></tr>}</tbody>
        </table></div>
      </section>
    </>}

    {detail&&<div className="modal-bg" onClick={()=>setDetail(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{detail.row?employeeLabel(detail.row):'Lifecycle'}</h2><button className="icon-btn" onClick={()=>setDetail(null)}>×</button></div>
      {detailErr&&<div className="notice danger">{detailErr}</div>}
      {detail.loading&&<div className="empty">Memuat riwayat...</div>}
      {detail.data&&<>
        <div className="notice">
          Status saat ini: <b>{statusLabel(detail.data.current_status)}</b>
          {' · '}Sumber timeline: {detail.data.timeline_source==='DERIVED_FROM_EXISTING_DATA'?'diturunkan dari data yang ada':'tersimpan'}
        </div>
        {detail.data.migration?.needs_migration&&<div className="notice" style={softNotice}>
          Perlu migrasi: {detail.data.migration.flags.map(f=><span key={f} className="badge amber" style={{marginRight:4}}>{migrationLabel(f)}</span>)}
        </div>}
        <table>
          <thead><tr><th>Tanggal</th><th>Kejadian</th><th>Detail</th><th>Sumber</th><th>Status setelah</th></tr></thead>
          <tbody>{timelineRows(detail.data).map((ev,i)=><tr key={i}>
            <td>{ev.dateLabel}</td>
            <td><b>{ev.typeLabel}</b><br/><small>{ev.label}</small></td>
            <td>{ev.detail||'-'}</td>
            <td className="td-sm">{ev.source||'-'}</td>
            <td>{statusLabel(ev.status_after)}</td>
          </tr>)}{timelineRows(detail.data).length===0&&<tr><td colSpan={5}><div className="empty">Belum ada riwayat yang bisa ditelusuri.</div></td></tr>}</tbody>
        </table>
        <div className="panel-head"><h2>Ringkasan Terkait</h2></div>
        <div className="quick-links">
          <div className="qlink"><ClipboardList size={18}/><div><b>{detail.data.related_counts?.trainings??0}</b><small>Training</small></div></div>
          <div className="qlink"><ClipboardList size={18}/><div><b>{detail.data.related_counts?.performances??0}</b><small>Performance</small></div></div>
          <div className="qlink"><ClipboardList size={18}/><div><b>{detail.data.related_counts?.issues??0}</b><small>Employee issue</small></div></div>
        </div>
        <div style={hint}>{(detail.data.notes||[]).map((n,i)=><div key={i}>• {n}</div>)}</div>
      </>}
      <div className="modal-foot"><button className="btn" onClick={()=>setDetail(null)}>Tutup</button></div>
    </div></div>}
  </div>}
