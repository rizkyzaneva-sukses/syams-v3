import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw,AlertTriangle,ClipboardList,CheckSquare,DollarSign,Factory,TrendingUp,Users,ShieldCheck,ArrowRight} from 'lucide-react';

/* MORNING CEO VIEW — revisi #70 & #78 (REF-CEO-IYAN).

   Blueprint meminta halaman action-first yang HANYA memuat keputusan/exception
   milik CEO, dengan empat domain ringkas: Finance/Cash & Collection, Production
   Today, Sales Opportunity, dan People Condition; ditambah Decision Queue dan
   Action Tracker. Tiap angka harus drill-down ke sumbernya, dan tidak boleh ada
   angka yang di-hard-code di UI — semuanya datang dari API.

   Halaman ini murni membaca. Aksi/override terjadi di halaman keputusan, bukan
   di sini. */

const rupiah=n=>'Rp '+Number(n||0).toLocaleString('id-ID');
const angka=n=>Number(n||0).toLocaleString('id-ID');

function DomainCard({icon:I,title,subtitle,tone='blue',rows,link,linkLabel}){
  return <section className="panel">
    <div className="panel-head">
      <h2><I size={16} style={{verticalAlign:'-3px',marginRight:6}}/>{title}</h2>
      {link&&<Link to={link} className="btn sm">{linkLabel||'Buka'} <ArrowRight size={13}/></Link>}
    </div>
    {subtitle&&<p style={{margin:'0 0 10px',fontSize:12,color:'#64748b'}}>{subtitle}</p>}
    {rows.length?<div className="table-scroll"><table>
      <tbody>{rows.map((r,i)=><tr key={i}>
        <td>{r.label}</td>
        <td style={{textAlign:'right'}}>
          <span className={'badge '+(r.tone||tone)}>{r.value}</span>
          {r.note&&<><br/><small>{r.note}</small></>}
        </td>
      </tr>)}</tbody>
    </table></div>:<p className="empty">Tidak ada data.</p>}
  </section>;
}

export default function CEOHome(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [decisions,setDecisions]=useState([]),[actions,setActions]=useState([]);
  const [exceptions,setExceptions]=useState([]);

  async function load(){
    setBusy(true);
    try{
      const [dash,dec,act,exc]=await Promise.all([
        api('/dashboard/CEO'),
        api('/ceo/decisions').catch(()=>[]),
        api('/ceo/actions').catch(()=>[]),
        api('/exceptions').catch(()=>[]),
      ]);
      setData(dash);setDecisions(dec||[]);setActions(act||[]);setExceptions(exc||[]);
      setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  if(err) return <div className="page"><div className="notice danger" role="alert">{err}</div></div>;
  if(!data) return <div className="page">Memuat Morning CEO View...</div>;

  const kpi=key=>data.kpis?.[key]?.value;
  const card=label=>(data.cards||[]).find(c=>c.label===label)?.value;

  /* Decision Queue: keputusan yang belum dijalankan + action yang belum selesai. */
  const openDecisions=decisions.filter(d=>d.action_status!=='DECIDED');
  const overdueActions=actions.filter(a=>a.overdue);
  const openActions=actions.filter(a=>a.status!=='DONE');

  /* Exception Center: endpoint sudah menyaring RED/butuh keputusan untuk CEO. */
  const redExceptions=exceptions.filter(e=>e.severity==='RED');
  const decisionRequired=exceptions.filter(e=>e.decision_required);

  const financeRows=[
    {label:'AR lewat jatuh tempo', value:rupiah(card('AR Lewat Jatuh Tempo')), tone: card('AR Lewat Jatuh Tempo')>0?'amber':'green', note:'sumber: invoice belum lunas'},
    {label:'Pengiriman tepat waktu', value:`${angka(kpi('on_time_shipments'))}%`, tone:'blue', note:`${data.kpis?.on_time_shipments?.numerator??0} dari ${data.kpis?.on_time_shipments?.denominator??0} shipment`},
    {label:'Margin quotation disetujui', value:`${angka(kpi('approved_quote_margin'))}%`, tone:'blue', note:'sumber: quotation APPROVED'},
    {label:'Shipment perlu keputusan CEO', value:angka(card('Shipment Perlu CEO')), tone: card('Shipment Perlu CEO')>0?'amber':'green', note:'gate finance HOLD'},
  ];
  const productionRows=[
    {label:'QC lulus', value:`${angka(kpi('qc_inspection_pass'))}%`, tone:'green', note:`${angka(data.kpis?.qc_inspection_pass?.numerator)} dari ${angka(data.kpis?.qc_inspection_pass?.denominator)} unit`},
    {label:'Order aktif', value:angka(card('Order Aktif')), tone:'blue', note:'sumber: /api/orders'},
    {label:'Critical issue produksi', value:angka(card('Critical Issue')), tone: card('Critical Issue')>0?'red':'green'},
  ];
  const salesRows=[
    {label:'Decision open', value:angka(card('Decision Open')), tone: card('Decision Open')>0?'amber':'green', note:'belum diputuskan CEO'},
    {label:'Exception butuh keputusan', value:angka(decisionRequired.length), tone: decisionRequired.length?'amber':'green'},
    {label:'Exception RED', value:angka(redExceptions.length), tone: redExceptions.length?'red':'green'},
  ];
  const peopleRows=[
    {label:'Exception people', value:angka(exceptions.filter(e=>['PEOPLE','HR_CONFIDENTIAL'].includes(e.category)).length), tone:'blue', note:'HR confidential dibatasi'},
    {label:'Action lewat tenggat', value:angka(overdueActions.length), tone: overdueActions.length?'red':'green', note:'perlu eskalasi'},
  ];

  return <div className="page">
    <div className="page-title">
      <div><h1>Morning CEO View</h1><p>Hanya keputusan dan exception yang membutuhkan CEO. Detail divisi dibuka lewat drill-down read-only.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    {/* Decision Queue — yang paling perlu perhatian, ditaruh paling atas (action-first). */}
    <section className="panel">
      <div className="panel-head">
        <h2><ClipboardList size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Decision Queue</h2>
        <Link to="/ceo/decisions" className="btn sm">Kelola keputusan <ArrowRight size={13}/></Link>
      </div>
      {openDecisions.length?<div className="table-scroll"><table><thead><tr>
        <th>Subject</th><th>Tipe</th><th>Sumber</th><th>Impact</th><th>Owner</th><th>Due</th><th>Status</th>
      </tr></thead><tbody>{openDecisions.map(d=><tr key={d.id}>
        <td><b>{d.subject}</b>{d.requester&&<><br/><small>diminta {d.requester}</small></>}</td>
        <td><span className="badge gray">{d.decision_type}</span></td>
        <td><small>{d.source_entity||'—'}{d.source_entity_id?` #${d.source_entity_id}`:''}</small></td>
        <td><small>{[d.impact_financial&&'finansial',d.impact_operational&&'operasional',d.impact_customer&&'customer',d.impact_people&&'people'].filter(Boolean).join(', ')||'—'}</small></td>
        <td><span className="badge blue">{d.decision_owner||'—'}</span></td>
        <td>{d.due_date||'—'}</td>
        <td><span className={(d.due_date&&d.due_date<new Date().toISOString().slice(0,10))?'badge red':'badge amber'}>{d.action_status||'OPEN'}</span></td>
      </tr>)}</tbody></table></div>:<p className="empty">Tidak ada keputusan yang menunggu.</p>}
    </section>

    {/* Empat domain ringkas (REF-CEO-IYAN). */}
    <div className="grid2">
      <DomainCard icon={DollarSign} title="Finance / Cash & Collection" subtitle="Piutang, margin, dan keputusan pembayaran" rows={financeRows} link="/cfo/shipments" linkLabel="Shipment Gate"/>
      <DomainCard icon={Factory} title="Production Today" subtitle="Kondisi produksi dan mutu" rows={productionRows} link="/audit-log" linkLabel="Audit"/>
    </div>
    <div className="grid2">
      <DomainCard icon={TrendingUp} title="Sales Opportunity" subtitle="Keputusan komersial dan exception berjalan" rows={salesRows} link="/exceptions" linkLabel="Exception Center"/>
      <DomainCard icon={Users} title="People Condition" subtitle="Kondisi orang dan tindak lanjut" rows={peopleRows} link="/exceptions" linkLabel="Exception Center"/>
    </div>

    {/* Action Tracker — memastikan keputusan benar-benar dijalankan. */}
    <section className="panel">
      <div className="panel-head">
        <h2><CheckSquare size={16} style={{verticalAlign:'-3px',marginRight:6}}/>CEO Action Tracker</h2>
        <span>{openActions.length} belum selesai · {overdueActions.length} lewat tenggat</span>
      </div>
      {actions.length?<div className="table-scroll"><table><thead><tr>
        <th>Action ID</th><th>Tindakan</th><th>Owner berwenang</th><th>Due</th><th>Status</th><th>Bukti penyelesaian</th>
      </tr></thead><tbody>{actions.slice(0,15).map(a=><tr key={a.id}>
        <td><b>{a.action_no||`ACT-${a.id}`}</b></td>
        <td>{a.title}</td>
        <td><span className="badge gray">{a.authorized_owner||'—'}</span></td>
        <td>{a.due_date?(a.overdue?<span className="badge red">{a.due_date} · lewat</span>:a.due_date):'—'}</td>
        <td><span className={'badge '+(a.status==='DONE'?'green':a.overdue?'red':'amber')}>{a.status}</span></td>
        <td><small>{a.completion_note||'—'}</small></td>
      </tr>)}</tbody></table></div>:<p className="empty">Belum ada action dari keputusan CEO.</p>}
    </section>

    {/* Exception Center ringkas + empat batas override terkontrol. */}
    <div className="grid2">
      <section className="panel">
        <div className="panel-head">
          <h2><AlertTriangle size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Exception Center</h2>
          <Link to="/exceptions" className="btn sm">Semua exception <ArrowRight size={13}/></Link>
        </div>
        {exceptions.length?<div className="table-scroll"><table><thead><tr>
          <th>Severity</th><th>Kategori</th><th>Judul</th><th>Owner</th><th>Due</th><th>Butuh keputusan</th>
        </tr></thead><tbody>{exceptions.slice(0,10).map(e=><tr key={e.id}>
          <td><span className={'badge '+(e.severity==='RED'?'red':'amber')}>{e.severity}</span></td>
          <td><span className="badge gray">{e.category}</span></td>
          <td>{e.title}</td>
          <td><small>{e.owner_role||'—'}</small></td>
          <td>{e.due_date||'—'}</td>
          <td>{e.decision_required?<span className="badge red">ya</span>:<small>tidak</small>}</td>
        </tr>)}</tbody></table></div>:<p className="empty">Tidak ada exception yang perlu CEO.</p>}
        <p style={{fontSize:12,color:'#64748b',marginTop:8}}>RED memicu push notification; YELLOW cukup terlihat di dashboard.</p>
      </section>

      <section className="panel">
        <div className="panel-head"><h2><ShieldCheck size={16} style={{verticalAlign:'-3px',marginRight:6}}/>Batas Override Terkontrol</h2></div>
        <div className="flow-list">
          <div className="flow-row"><b>1</b><span>Production priority — diputus CEO (Master Control).</span></div>
          <div className="flow-row"><b>2</b><span>Pricing exception — final oleh CFO, CEO hanya diinformasikan.</span></div>
          <div className="flow-row"><b>3</b><span>Shipment outstanding — wajib persetujuan CEO (Shipment Gate).</span></div>
          <div className="flow-row"><b>4</b><span>Purchasing — hanya kasus khusus/override; rutin milik Riadi/CFO.</span></div>
        </div>
        <p style={{fontSize:12,color:'#64748b',marginTop:8}}>
          Semua drill-down read-only kecuali keputusan/override eksplisit.
        </p>
      </section>
    </div>
  </div>;
}
