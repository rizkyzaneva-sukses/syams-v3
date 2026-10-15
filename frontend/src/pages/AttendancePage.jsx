import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';
import {RefreshCw,CalendarCheck,CalendarDays,Check,X,Send} from 'lucide-react';

/* Halaman Absensi & Cuti/Izin HR.
   Dua tab: "Absensi" (input harian individual maupun massal + rekap) dan
   "Cuti" (pengajuan, persetujuan, saldo). Tombol tulis hanya tampil untuk
   CHRO_MANAGER/HR_SUPPORT; CEO read-only. Semua aturan (upsert absensi, saldo
   cukup, alasan wajib) ditegakkan di server — UI hanya menampilkan pesannya. */
const WRITE_ROLES=['CHRO_MANAGER','HR_SUPPORT'];
const TODAY=new Date().toISOString().slice(0,10);
const YEAR=TODAY.slice(0,4);
const YEAR_START=YEAR+'-01-01';

const ATT_STATUS=['HADIR','TERLAMBAT','IZIN','SAKIT','ALPHA','CUTI','LIBUR'];
const LEAVE_TYPES=['TAHUNAN','SAKIT','IZIN','MELAHIRKAN','LAINNYA'];
const LEAVE_STATUS=['DRAFT','SUBMITTED','APPROVED','REJECTED','CANCELLED'];
const LEAVE_LABEL={TAHUNAN:'Cuti Tahunan',SAKIT:'Sakit',IZIN:'Izin',MELAHIRKAN:'Melahirkan',LAINNYA:'Lainnya'};
const STATUS_TONE={HADIR:'green',TERLAMBAT:'amber',IZIN:'blue',SAKIT:'amber',ALPHA:'red',CUTI:'blue',LIBUR:'gray',
  DRAFT:'gray',SUBMITTED:'amber',APPROVED:'green',REJECTED:'red',CANCELLED:'gray'};
const num=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2});

export default function AttendancePage(){
  const role=useRole();
  const canWrite=WRITE_ROLES.includes(role);
  const [tab,setTab]=useState('absensi');
  const [err,setErr]=useState(''),[msg,setMsg]=useState('');
  const [busy,setBusy]=useState(false);
  const [employees,setEmployees]=useState([]);
  const [year,setYear]=useState(YEAR);

  // muat daftar karyawan sekali untuk dropdown
  useEffect(()=>{
    api('/hr/employees-summary').then(d=>setEmployees(d.employees||[])).catch(e=>setErr(e.message));
  },[]);

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Absensi &amp; Cuti</h1>
        <p>Kehadiran harian, lembur, pengajuan cuti/izin, dan saldo cuti. HR menulis; CEO membaca.</p>
      </div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {msg&&<div className="notice" role="status">{msg}</div>}
    <div className="filter-bar">
      <div className="filter-pills">
        <button className={'pill'+(tab==='absensi'?' active open':'')} onClick={()=>setTab('absensi')}>Absensi</button>
        <button className={'pill'+(tab==='cuti'?' active open':'')} onClick={()=>setTab('cuti')}>Cuti / Izin</button>
      </div>
    </div>
    {tab==='absensi'
      ? <AbsensiTab employees={employees} canWrite={canWrite} setErr={setErr} setMsg={setMsg} busy={busy} setBusy={setBusy}/>
      : <CutiTab employees={employees} canWrite={canWrite} setErr={setErr} setMsg={setMsg} busy={busy} setBusy={setBusy} year={year} setYear={setYear}/>}
  </div>;
}

/* ─────────────────────────────── TAB ABSENSI ─────────────────────────────── */
function AbsensiTab({employees,canWrite,setErr,setMsg,busy,setBusy}){
  const [from,setFrom]=useState(YEAR_START),[to,setTo]=useState(TODAY);
  const [empFilter,setEmpFilter]=useState('');
  const [statusFilter,setStatusFilter]=useState('');
  const [rows,setRows]=useState([]);
  const [summary,setSummary]=useState(null);
  const [mode,setMode]=useState('individual');

  const load=()=>{
    setErr('');
    const qs=[];
    if(empFilter) qs.push('employee_id='+empFilter);
    if(from) qs.push('date_from='+from);
    if(to) qs.push('date_to='+to);
    if(statusFilter) qs.push('status='+statusFilter);
    api('/hr/attendance?'+qs.join('&')).then(d=>setRows(d.rows||[])).catch(e=>setErr(e.message));
    api(`/hr/attendance/summary?date_from=${from}&date_to=${to}`).then(setSummary).catch(e=>setErr(e.message));
  };
  useEffect(load,[from,to,empFilter,statusFilter]);

  const empName=id=>employees.find(e=>e.id===id);

  return <>
    <section className="panel">
      <div className="panel-head"><h2><CalendarCheck size={16}/> Filter &amp; Rekap</h2></div>
      <div className="filter-bar">
        <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Dari<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
        <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Sampai<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
        <select value={empFilter} onChange={e=>setEmpFilter(e.target.value)}>
          <option value="">Semua karyawan</option>
          {employees.map(e=><option key={e.id} value={e.id}>{e.employee_no} — {e.name}</option>)}
        </select>
        <select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}>
          <option value="">Semua status</option>
          {ATT_STATUS.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn" onClick={load} disabled={busy}><RefreshCw size={16}/> Muat</button>
      </div>
      {summary&&<div className="cards">
        {[['HADIR','green'],['TERLAMBAT','amber'],['IZIN','blue'],['SAKIT','amber'],['ALPHA','red']].map(([k,tone])=>
          <div className={'stat '+tone} key={k}><span>{k}</span><strong>{summary.totals?.[k]??0}</strong></div>)}
        <div className="stat blue"><span>Total lembur (jam)</span><strong>{num(summary.totals?.overtime_hours)}</strong></div>
      </div>}
    </section>

    {canWrite&&<section className="panel">
      <div className="panel-head"><h2>Input Absensi</h2>
        <div className="filter-pills">
          <button className={'pill'+(mode==='individual'?' active open':'')} onClick={()=>setMode('individual')}>Individual</button>
          <button className={'pill'+(mode==='massal'?' active open':'')} onClick={()=>setMode('massal')}>Massal</button>
        </div>
      </div>
      {mode==='individual'
        ? <IndividualForm employees={employees} onDone={()=>{load();setMsg('Absensi disimpan (upsert).')}} setErr={setErr} setBusy={setBusy} busy={busy}/>
        : <MassalForm employees={employees} onDone={()=>{load();setMsg('Input massal selesai.')}} setErr={setErr} setBusy={setBusy} busy={busy}/>}
    </section>}

    <section className="panel">
      <div className="panel-head"><h2>Catatan Absensi ({rows.length})</h2></div>
      <div className="table-scroll"><table>
        <thead><tr><th>Tanggal</th><th>Karyawan</th><th>Status</th><th>Masuk</th><th>Keluar</th><th>Lembur</th><th>Shift</th><th>Catatan</th></tr></thead>
        <tbody>{rows.map(r=>{const e=empName(r.employee_id);return <tr key={r.id}>
          <td>{r.work_date}</td>
          <td><b>{e?e.employee_no:r.employee_id}</b><br/><small>{e?e.name:'-'}</small></td>
          <td><span className={'badge '+(STATUS_TONE[r.status]||'gray')}>{r.status}</span></td>
          <td>{r.check_in||'-'}</td>
          <td>{r.check_out||'-'}</td>
          <td>{num(r.overtime_hours)}</td>
          <td>{r.shift||'-'}</td>
          <td>{r.notes||'-'}</td>
        </tr>;})}
        {rows.length===0&&<tr><td colSpan={8}><div className="empty">Belum ada catatan absensi pada periode ini.</div></td></tr>}
        </tbody>
      </table></div>
    </section>

    {summary&&summary.rows?.length>0&&<section className="panel">
      <div className="panel-head"><h2>Rekap per Karyawan</h2></div>
      <div className="table-scroll"><table>
        <thead><tr><th>Karyawan</th><th>Divisi</th>{ATT_STATUS.map(s=><th key={s}>{s}</th>)}<th>Lembur</th></tr></thead>
        <tbody>{summary.rows.map(r=><tr key={r.employee_id}>
          <td><b>{r.employee_no||r.employee_id}</b><br/><small>{r.name||'-'}</small></td>
          <td>{r.division||'-'}</td>
          {ATT_STATUS.map(s=><td key={s}>{r[s]??0}</td>)}
          <td>{num(r.overtime_hours)}</td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </>;
}

function IndividualForm({employees,onDone,setErr,setBusy,busy}){
  const [f,setF]=useState({employee_id:'',work_date:TODAY,status:'HADIR',check_in:'',check_out:'',overtime_hours:0,shift:'',notes:''});
  const up=k=>e=>setF({...f,[k]:e.target.value});
  async function submit(){
    if(!f.employee_id){setErr('Pilih karyawan dulu.');return;}
    setBusy(true);setErr('');
    try{
      const qs=new URLSearchParams({employee_id:f.employee_id,work_date:f.work_date,status:f.status,overtime_hours:f.overtime_hours||0});
      ['check_in','check_out','shift','notes'].forEach(k=>{if(f[k])qs.set(k,f[k]);});
      await api('/hr/attendance?'+qs.toString(),{method:'POST'});
      onDone();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  return <div className="form-grid">
    <div className="form-row"><label>Karyawan</label>
      <select value={f.employee_id} onChange={up('employee_id')}><option value="">— pilih —</option>
        {employees.map(e=><option key={e.id} value={e.id}>{e.employee_no} — {e.name}</option>)}</select></div>
    <div className="form-row"><label>Tanggal</label><input type="date" value={f.work_date} onChange={up('work_date')}/></div>
    <div className="form-row"><label>Status</label>
      <select value={f.status} onChange={up('status')}>{ATT_STATUS.map(s=><option key={s} value={s}>{s}</option>)}</select></div>
    <div className="form-row"><label>Masuk</label><input placeholder="08:00" value={f.check_in} onChange={up('check_in')}/></div>
    <div className="form-row"><label>Keluar</label><input placeholder="17:00" value={f.check_out} onChange={up('check_out')}/></div>
    <div className="form-row"><label>Lembur (jam)</label><input type="number" min="0" step="0.5" value={f.overtime_hours} onChange={up('overtime_hours')}/></div>
    <div className="form-row"><label>Shift</label><input value={f.shift} onChange={up('shift')}/></div>
    <div className="form-row"><label>Catatan</label><input value={f.notes} onChange={up('notes')}/></div>
    <div className="form-actions"><button className="btn primary" onClick={submit} disabled={busy}>Simpan (upsert)</button></div>
  </div>;
}

function MassalForm({employees,onDone,setErr,setBusy,busy}){
  const [work_date,setDate]=useState(TODAY);
  const [status,setStatus]=useState('HADIR');
  const [shift,setShift]=useState('');
  const [picked,setPicked]=useState([]);
  const allIds=useMemo(()=>employees.map(e=>e.id),[employees]);
  function toggle(id){setPicked(p=>p.includes(id)?p.filter(x=>x!==id):[...p,id]);}
  async function submit(){
    if(picked.length===0){setErr('Pilih minimal satu karyawan.');return;}
    setBusy(true);setErr('');
    try{
      for(const id of picked){
        const qs=new URLSearchParams({employee_id:id,work_date,status,overtime_hours:0});
        if(shift) qs.set('shift',shift);
        await api('/hr/attendance?'+qs.toString(),{method:'POST'});
      }
      setPicked([]);
      onDone();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  return <>
    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Tanggal<input type="date" value={work_date} onChange={e=>setDate(e.target.value)}/></label>
      <select value={status} onChange={e=>setStatus(e.target.value)}>{ATT_STATUS.map(s=><option key={s} value={s}>{s}</option>)}</select>
      <input placeholder="Shift (opsional)" value={shift} onChange={e=>setShift(e.target.value)}/>
      <button className="btn" onClick={()=>setPicked(allIds)}>Pilih semua</button>
      <button className="btn" onClick={()=>setPicked([])}>Kosongkan</button>
      <button className="btn primary" onClick={submit} disabled={busy||picked.length===0}>Simpan {picked.length} baris</button>
    </div>
    <div className="table-scroll" style={{maxHeight:320,overflowY:'auto'}}><table>
      <thead><tr><th></th><th>NIP</th><th>Nama</th><th>Divisi</th></tr></thead>
      <tbody>{employees.map(e=><tr key={e.id}>
        <td><input type="checkbox" checked={picked.includes(e.id)} onChange={()=>toggle(e.id)}/></td>
        <td>{e.employee_no}</td><td>{e.name}</td><td>{e.division||'-'}</td>
      </tr>)}</tbody>
    </table></div>
    <div style={{fontSize:12,color:'#64748b',marginTop:8}}>
      Input massal mengirim satu permintaan per karyawan terpilih; baris yang sudah ada akan diperbarui (upsert), bukan digandakan.
    </div>
  </>;
}

/* ──────────────────────────────── TAB CUTI ──────────────────────────────── */
function CutiTab({employees,canWrite,setErr,setMsg,busy,setBusy,year,setYear}){
  const [statusFilter,setStatusFilter]=useState('');
  const [rows,setRows]=useState([]);
  const [balances,setBalances]=useState([]);
  const [reject,setReject]=useState(null); // {id, reason}

  const load=()=>{
    setErr('');
    const qs=statusFilter?('?status='+statusFilter):'';
    api('/hr/leave'+qs).then(d=>setRows(d.rows||[])).catch(e=>setErr(e.message));
    api('/hr/leave/balances?year='+year).then(d=>setBalances(d.rows||[])).catch(e=>setErr(e.message));
  };
  useEffect(load,[statusFilter,year]);

  async function act(id,path,params){
    setBusy(true);setErr('');
    const qs=params?('?'+new URLSearchParams(params).toString()):'';
    try{await api(`/hr/leave/${id}/${path}${qs}`,{method:'POST'});
      setMsg('Aksi cuti dijalankan.');load();}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  const empName=id=>employees.find(e=>e.id===id);

  return <>
    {canWrite&&<section className="panel">
      <div className="panel-head"><h2><Send size={16}/> Pengajuan Cuti Baru</h2></div>
      <LeaveForm employees={employees} onDone={()=>{load();setMsg('Pengajuan cuti dibuat (SUBMITTED).')}} setErr={setErr} setBusy={setBusy} busy={busy}/>
    </section>}

    <section className="panel">
      <div className="panel-head"><h2>Daftar Pengajuan ({rows.length})</h2>
        <select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}>
          <option value="">Semua status</option>
          {LEAVE_STATUS.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="table-scroll"><table>
        <thead><tr><th>No</th><th>Karyawan</th><th>Jenis</th><th>Periode</th><th>Hari</th><th>Status</th><th>Alasan/Keputusan</th>{canWrite&&<th></th>}</tr></thead>
        <tbody>{rows.map(r=>{const e=empName(r.employee_id);return <tr key={r.id}>
          <td>{r.request_no}</td>
          <td><b>{e?e.employee_no:r.employee_id}</b><br/><small>{e?e.name:'-'}</small></td>
          <td>{LEAVE_LABEL[r.leave_type]||r.leave_type}</td>
          <td>{r.start_date} → {r.end_date}</td>
          <td>{num(r.days)}</td>
          <td><span className={'badge '+(STATUS_TONE[r.status]||'gray')}>{r.status}</span></td>
          <td><small>{r.status==='APPROVED'||r.status==='REJECTED'?(r.decision_note||'-'):(r.reason||'-')}</small></td>
          {canWrite&&<td className="td-action">{r.status==='SUBMITTED'&&<>
            <button className="icon-btn" title="Setujui" disabled={busy} onClick={()=>act(r.id,'approve')}><Check size={15}/></button>
            <button className="icon-btn" title="Tolak" disabled={busy} onClick={()=>setReject({id:r.id,reason:''})}><X size={15}/></button>
          </>}</td>}
        </tr>;})}
        {rows.length===0&&<tr><td colSpan={canWrite?8:7}><div className="empty">Belum ada pengajuan cuti.</div></td></tr>}
        </tbody>
      </table></div>
    </section>

    <section className="panel">
      <div className="panel-head"><h2><CalendarDays size={16}/> Saldo Cuti {year}</h2>
        <input type="number" style={{width:90}} value={year} onChange={e=>setYear(e.target.value)}/>
      </div>
      <div className="table-scroll"><table>
        <thead><tr><th>Karyawan</th><th>Jenis</th><th>Jatah</th><th>Terpakai</th><th>Sisa</th></tr></thead>
        <tbody>{balances.map(b=>{const e=empName(b.employee_id);return <tr key={b.id}>
          <td><b>{b.employee_no||b.employee_id}</b><br/><small>{b.name||'-'}</small></td>
          <td>{LEAVE_LABEL[b.leave_type]||b.leave_type}</td>
          <td>{num(b.entitled_days)}</td>
          <td>{num(b.used_days)}</td>
          <td><span className={'badge '+(b.remaining>0?'green':'gray')}>{num(b.remaining)}</span></td>
        </tr>;})}
        {balances.length===0&&<tr><td colSpan={5}><div className="empty">Belum ada saldo cuti tercatat untuk tahun {year}.</div></td></tr>}
        </tbody>
      </table></div>
    </section>

    {reject&&<div className="modal-bg" onClick={()=>setReject(null)}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="modal-head"><h3>Tolak Pengajuan Cuti</h3></div>
        <div style={{padding:'0 16px'}}>
          <p style={{fontSize:13,color:'#64748b'}}>Alasan penolakan wajib diisi — akan tersimpan sebagai decision_note.</p>
          <input autoFocus placeholder="Alasan penolakan" value={reject.reason}
            onChange={e=>setReject({...reject,reason:e.target.value})}/>
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={()=>setReject(null)}>Batal</button>
          <button className="btn primary" disabled={busy||!reject.reason.trim()}
            onClick={()=>{const {id,reason}=reject;setReject(null);act(id,'reject',{reason});}}>Tolak</button>
        </div>
      </div>
    </div>}
  </>;
}

function LeaveForm({employees,onDone,setErr,setBusy,busy}){
  const [f,setF]=useState({employee_id:'',leave_type:'TAHUNAN',start_date:TODAY,end_date:TODAY,reason:''});
  const up=k=>e=>setF({...f,[k]:e.target.value});
  const days=useMemo(()=>{
    const a=new Date(f.start_date),b=new Date(f.end_date);
    if(isNaN(a)||isNaN(b)||b<a)return null;
    return Math.round((b-a)/86400000)+1;
  },[f.start_date,f.end_date]);
  async function submit(){
    if(!f.employee_id){setErr('Pilih karyawan dulu.');return;}
    setBusy(true);setErr('');
    try{
      const qs=new URLSearchParams({employee_id:f.employee_id,leave_type:f.leave_type,start_date:f.start_date,end_date:f.end_date});
      if(f.reason) qs.set('reason',f.reason);
      await api('/hr/leave?'+qs.toString(),{method:'POST'});
      onDone();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  return <div className="form-grid">
    <div className="form-row"><label>Karyawan</label>
      <select value={f.employee_id} onChange={up('employee_id')}><option value="">— pilih —</option>
        {employees.map(e=><option key={e.id} value={e.id}>{e.employee_no} — {e.name}</option>)}</select></div>
    <div className="form-row"><label>Jenis</label>
      <select value={f.leave_type} onChange={up('leave_type')}>{LEAVE_TYPES.map(t=><option key={t} value={t}>{LEAVE_LABEL[t]}</option>)}</select></div>
    <div className="form-row"><label>Mulai</label><input type="date" value={f.start_date} onChange={up('start_date')}/></div>
    <div className="form-row"><label>Selesai</label><input type="date" value={f.end_date} onChange={up('end_date')}/></div>
    <div className="form-row"><label>Jumlah hari (otomatis)</label><input value={days==null?'—':days+' hari'} readOnly/></div>
    <div className="form-row"><label>Alasan</label><input value={f.reason} onChange={up('reason')}/></div>
    <div className="form-actions"><button className="btn primary" onClick={submit} disabled={busy||days==null}>Ajukan</button></div>
  </div>;
}
