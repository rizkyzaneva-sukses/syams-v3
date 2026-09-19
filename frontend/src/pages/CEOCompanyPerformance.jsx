import React,{useEffect,useState} from 'react';
import {useNavigate,useParams} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw,BarChart3,ArrowLeft,ExternalLink,ShieldCheck,AlertTriangle,CheckCircle2,XCircle} from 'lucide-react';
import {formatKpiValue,missingKpiIds,reconciliationMismatches,domainLabel,finalCloseReady,DATA_STATE_LABEL,formatNullableCurrency} from '../ceoPerformance';

/* COMPANY PERFORMANCE — read-only drill-down (revisi #71 & #77, CEO-I-002 /
   CEO-I-008).

   Aturan repo (business.js): 'CEO tidak punya halaman kerja operasional ...
   CEO melihat angkanya lewat drill-down read-only di Company Performance.'

   Halaman ini karena itu:
   - hanya memanggil GET;
   - menampilkan setiap KPI dengan KPI ID, periode, sumber, target, variance,
     status, dan cutoff apa adanya dari API — tanpa angka hard-code;
   - membedakan 'belum ada data', 'nol', dan 'tidak relevan';
   - menyediakan tautan sumber per KPI, bukan tombol aksi.

   Tidak ada satu pun tombol create/edit/delete di sini. */

const TONE_CLASS={green:'green',amber:'amber',red:'red',gray:'gray'};

function KpiRow({kpi,onDrill}){
  const value=formatKpiValue(kpi);
  const health=TONE_CLASS[value.tone]||'gray';
  const hasTarget=kpi.target!=null;
  return <tr>
    <td>
      <b>{kpi.label}</b>
      <br/><small title="KPI ID dari API">{kpi.kpi_id}</small>
    </td>
    <td style={{textAlign:'right'}}>
      <span className={'badge '+health}>{value.text}</span>
      {kpi.unit&&<><br/><small>satuan {kpi.unit}</small></>}
    </td>
    <td style={{textAlign:'right'}}>
      {hasTarget?formatKpiValue({...kpi,value:kpi.target}).text:<small>—</small>}
      <br/><small>{DATA_STATE_LABEL[value.state]||value.state}</small>
    </td>
    <td style={{textAlign:'right'}}>
      {kpi.variance==null?<small>—</small>:
        <span className={'badge '+(kpi.variance>=0?'green':'red')}>
          {kpi.variance>0?'+':''}{kpi.variance}
        </span>}
    </td>
    <td>
      <small>
        {kpi.source_module||'—'}
        {kpi.source_entity?` / ${kpi.source_entity}`:''}
        {kpi.source_entity_id?` #${kpi.source_entity_id}`:''}
      </small>
      {kpi.numerator!=null&&kpi.denominator!=null&&
        <><br/><small>{kpi.numerator} dari {kpi.denominator}</small></>}
    </td>
    <td><small>{(kpi.period&&kpi.period.as_of)||'—'}</small></td>
    <td>
      {kpi.drilldown
        ?<button className="btn sm" onClick={()=>onDrill(kpi)}>Drill-down <ExternalLink size={12}/></button>
        :<small>Tidak ada drill-down</small>}
    </td>
  </tr>;
}

export default function CEOCompanyPerformance(){
  const nav=useNavigate();
  const [data,setData]=useState(null);
  const [drill,setDrill]=useState(null);
  const [env,setEnv]=useState('LIVE');
  const [err,setErr]=useState(''),[busy,setBusy]=useState(false);

  async function load(){
    setBusy(true);
    try{
      const payload=await api('/ceo/company-performance?environment='+env);
      setData(payload); setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[env]);

  async function openDrill(domain){
    try{ setDrill(await api('/ceo/drilldown/'+domain)); setErr(''); }
    catch(e){ setErr(e.message); }
  }

  if(err&&!data) return <div className="page"><div className="notice danger" role="alert">{err}</div></div>;
  if(!data) return <div className="page">Memuat Company Performance...</div>;

  const health=data.health||{};
  const mismatches=reconciliationMismatches(data);
  const noSource=missingKpiIds(data);
  const domains=data.domains||{};

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Company Performance</h1>
        <p>
          Read-only drill-down. Setiap angka punya KPI ID, periode, target, sumber, dan cutoff.
          Aksi operasional tetap milik divisi; CEO hanya memutuskan dan meng-override.
        </p>
      </div>
      <div style={{display:'flex',gap:8}}>
        <select value={env} onChange={e=>setEnv(e.target.value)} aria-label="Environment">
          <option value="LIVE">LIVE</option>
          <option value="UAT">UAT</option>
          <option value="TEST">TEST</option>
          <option value="ALL">ALL</option>
        </select>
        <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
      </div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    {/* Health ringkas: RED/YELLOW/GREEN + berapa yang datanya belum ada. */}
    <div className="grid2">
      <section className="panel">
        <div className="panel-head"><h2><BarChart3 size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Company Health</h2>
          <span className={'badge '+TONE_CLASS[health.label==='RED'?'red':health.label==='YELLOW'?'amber':'green']}>{health.label||'—'}</span>
        </div>
        <div className="flow-list">
          <div className="flow-row"><b>{health.red||0}</b><span>KPI RED — {(health.red_ids||[]).join(', ')||'tidak ada'}</span></div>
          <div className="flow-row"><b>{health.yellow||0}</b><span>KPI YELLOW — {(health.yellow_ids||[]).join(', ')||'tidak ada'}</span></div>
          <div className="flow-row"><b>{health.green||0}</b><span>KPI GREEN</span></div>
          <div className="flow-row"><b>{health.missing||0}</b><span>Belum ada sumber data — {(health.missing_ids||[]).join(', ')||'tidak ada'}</span></div>
        </div>
        <p style={{fontSize:12,color:'#64748b',marginTop:8}}>
          Ambang warna configurable lewat business policy (berversi &amp; teraudit).
          Periode {(data.period&&data.period.month)||'—'} · cutoff {data.calculated_at}
        </p>
      </section>

      <section className="panel">
        <div className="panel-head"><h2><ShieldCheck size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Rekonsiliasi &amp; Data Integrity</h2>
          {mismatches.length?<span className="badge red">{mismatches.length} selisih</span>:<span className="badge green">cocok</span>}
        </div>
        <div className="table-scroll"><table><thead><tr>
          <th>Pemeriksaan</th><th style={{textAlign:'right'}}>Total CEO</th><th style={{textAlign:'right'}}>Modul otoritatif</th><th>Sumber</th><th>Cocok</th>
        </tr></thead><tbody>{(data.reconciliation||[]).map((row,i)=><tr key={i}>
          <td>{row.check}</td>
          <td style={{textAlign:'right'}}>{row.ceo_value}</td>
          <td style={{textAlign:'right'}}>{row.module_value}</td>
          <td><small>{row.source_module}</small></td>
          <td>{row.match?<span className="badge green">ya</span>:<span className="badge red">tidak</span>}</td>
        </tr>)}</tbody></table></div>
        <p style={{fontSize:12,color:'#64748b',marginTop:8}}>
          Baris LIVE {(data.environment_rows||{}).LIVE??0} · UAT {(data.environment_rows||{}).UAT??0} ·
          TEST {(data.environment_rows||{}).TEST??0}. Seed/UAT dipisahkan dari KPI produksi.
          {noSource.length>0&&<> KPI tanpa sumber: {noSource.join(', ')}.</>}
        </p>
      </section>
    </div>

    {/* Empat domain ringkas, tiap kartu menuju drill-down read-only. */}
    <div className="grid2">
      {['finance','production','sales','people'].map(d=><section className="panel" key={d}>
        <div className="panel-head">
          <h2>{domainLabel(d)}</h2>
          <button className="btn sm" onClick={()=>openDrill(d)}>Drill-down <ExternalLink size={12}/></button>
        </div>
        <div className="table-scroll"><table><tbody>
          {Object.entries(domains[d]||{}).filter(([k])=>k!=='drilldown').map(([k,v])=><tr key={k}>
            <td><small>{k.replace(/_/g,' ')}</small></td>
            <td style={{textAlign:'right'}}>
              <span className="badge gray">
                {typeof v==='number'?(Number.isInteger(v)?v:v.toFixed(1)):'—'}
              </span>
            </td>
          </tr>)}
        </tbody></table></div>
      </section>)}
    </div>

    {/* Tabel KPI lengkap — provenance terlihat, bukan disembunyikan. */}
    <section className="panel">
      <div className="panel-head"><h2>KPI &amp; Target</h2><span>{data.kpis.length} KPI</span></div>
      <div className="table-scroll"><table><thead><tr>
        <th>KPI</th><th style={{textAlign:'right'}}>Actual</th><th style={{textAlign:'right'}}>Target</th>
        <th style={{textAlign:'right'}}>Variance</th><th>Sumber / N / D</th><th>Cutoff</th><th>Drill-down</th>
      </tr></thead><tbody>{data.kpis.map(k=><KpiRow key={k.kpi_id} kpi={k} onDrill={kpi=>openDrill(String(kpi.drilldown||'').split('/').pop())}/>)}</tbody></table></div>
    </section>

    {/* Closing terpisah: final close hanya bila ketiganya lulus. */}
    <ClosingPanel/>

    {/* Drill-down read-only. */}
    {drill&&<section className="panel">
      <div className="panel-head">
        <h2><ArrowLeft size={16} style={{verticalAlign:'-3px',marginRight:6,cursor:'pointer'}} onClick={()=>setDrill(null)}/>
          Drill-down: {domainLabel(drill.domain)}</h2>
        <button className="btn sm" onClick={()=>setDrill(null)}>Tutup</button>
      </div>
      <p style={{fontSize:12,color:'#64748b',margin:'0 0 8px'}}>
        Sumber: {drill.source_module} · read-only {String(drill.read_only)} · {drill.rows?.length||drill.employees?.length||drill.quotations?.length||0} baris
      </p>
      {drill.rows&&<DrillTable columns={drill.columns} rows={drill.rows}/>}
      {drill.employees&&<DrillTable columns={drill.columns} rows={drill.employees}/>}
      {drill.quotations&&<><p style={{fontWeight:600}}>Quotation</p><DrillTable
        columns={['quotation_no','buyer','amount','margin_percent','status']} rows={drill.quotations}/></>}
      {drill.orders&&<><p style={{fontWeight:600}}>Order aktif</p><DrillTable
        columns={['order_id','buyer','overall_status','flow_step','buyer_deadline']} rows={drill.orders}/></>}
      {drill.issues&&<><p style={{fontWeight:600}}>Employee issue</p><DrillTable
        columns={['id','severity','status','escalated']} rows={drill.issues}/></>}
    </section>}
  </div>;
}

function DrillTable({columns,rows}){
  if(!rows||!rows.length) return <p className="empty">Tidak ada baris sumber.</p>;
  return <div className="table-scroll"><table><thead><tr>
    {columns.map(c=><th key={c}>{c.replace(/_/g,' ')}</th>)}<th>Sumber</th>
  </tr></thead><tbody>{rows.map((row,i)=><tr key={i}>
    {columns.map(c=><td key={c}>
      {typeof row[c]==='number'&&/amount|outstanding|paid|value/.test(c)
        ?formatNullableCurrency(row[c])
        :String(row[c]??'—')}
    </td>)}
    <td><small>{row.source_entity||'—'}{row.source_entity_id?` #${row.source_entity_id}`:''}</small></td>
  </tr>)}</tbody></table></div>;
}

function ClosingPanel(){
  const [data,setData]=useState(null),[err,setErr]=useState('');
  useEffect(()=>{api('/ceo/closing-status').then(setData).catch(e=>setErr(e.message))},[]);
  if(err) return <section className="panel"><div className="notice danger">{err}</div></section>;
  if(!data) return <section className="panel">Memuat status closing...</section>;
  const rows=[['operational','Operasional (COO)'],['customer','Customer (CMO)'],['financial','Financial (CFO)']];
  return <section className="panel">
    <div className="panel-head"><h2>Order Closing</h2>
      {finalCloseReady(data)
        ?<span className="badge green"><CheckCircle2 size={13}/> {data.verdict}</span>
        :<span className="badge amber"><AlertTriangle size={13}/> {data.verdict}</span>}
    </div>
    <div className="table-scroll"><table><thead><tr>
      <th>Dimensi</th><th>Modul pemilik</th><th style={{textAlign:'right'}}>Closed</th><th style={{textAlign:'right'}}>Open</th><th>Lulus</th>
    </tr></thead><tbody>{rows.map(([key,label])=>{
      const dim=data[key]||{}, owner=(data.owner_module||{})[key];
      return <tr key={key}>
        <td>{label}</td><td><small>{owner}</small></td>
        <td style={{textAlign:'right'}}>{dim.closed}</td>
        <td style={{textAlign:'right'}}>{dim.open}</td>
        <td>{dim.open===0?<span className="badge green"><CheckCircle2 size={12}/> ya</span>:<span className="badge red"><XCircle size={12}/> belum</span>}</td>
      </tr>;})}</tbody></table></div>
    <p style={{fontSize:12,color:'#64748b',marginTop:8}}>{data.note}</p>
  </section>;
}
