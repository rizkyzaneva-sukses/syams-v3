import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {RefreshCw,Search,Printer,ShieldCheck,AlertTriangle,Layers,Send} from 'lucide-react';

// Revisi #43-#45: Job Card Printing/Bordir, kendali kuantitas + partial
// handoff, dan bukti/inspeksi/defect/rework. Halaman ini murni baca dari
// GET /printing/job-cards dan GET /printing/quality.
//
// Aturan kuantitas ditampilkan apa adanya dari server (bukan dihitung ulang di
// UI): qty_in = qty_done + qty_reject + WIP. Field `qty_balanced` datang dari
// server supaya UI tidak pernah menampilkan angka yang "kelihatan seimbang"
// padahal tidak.

const STATUS_TONE={DONE:'green',IN_PROCESS:'amber',WAITING:'gray'};

function tone(value){return STATUS_TONE[value]||'gray'}

function passRateTone(rate){
  if(rate==null) return 'gray';
  if(rate>=95) return 'green';
  if(rate>=85) return 'amber';
  return 'red';
}

export default function PrintingJobCardPage(){
  const [jobCards,setJobCards]=useState([]);
  const [quality,setQuality]=useState(null);
  const [meta,setMeta]=useState({total_job_cards:0,quantity_balanced:true});
  const [err,setErr]=useState('');
  const [loading,setLoading]=useState(true);
  const [q,setQ]=useState('');
  const [statusFilter,setStatusFilter]=useState('');
  const [onlyPartial,setOnlyPartial]=useState(false);

  function load(){
    setLoading(true);
    Promise.all([api('/printing/job-cards'),api('/printing/quality')])
      .then(([cards,qualityData])=>{
        setJobCards(cards.job_cards||[]);
        setMeta({total_job_cards:cards.total_job_cards||0,quantity_balanced:cards.quantity_balanced!==false});
        setQuality(qualityData);
      })
      .catch(e=>setErr(e.message))
      .finally(()=>setLoading(false));
  }
  useEffect(load,[]);

  const filtered=useMemo(()=>jobCards.filter(card=>{
    if(statusFilter&&card.status!==statusFilter) return false;
    if(onlyPartial&&!card.partial_handoff) return false;
    if(!q) return true;
    const term=q.toLowerCase();
    return [card.job_id,card.order_id,card.article_code,card.buyer,card.stage,card.pic_name,card.spk_no]
      .some(value=>String(value??'').toLowerCase().includes(term));
  }),[jobCards,q,statusFilter,onlyPartial]);

  const totals=useMemo(()=>filtered.reduce((acc,card)=>({
    qty_in:acc.qty_in+Number(card.qty_in||0),
    qty_done:acc.qty_done+Number(card.qty_done||0),
    qty_reject:acc.qty_reject+Number(card.qty_reject||0),
    wip:acc.wip+Number(card.wip||0),
  }),{qty_in:0,qty_done:0,qty_reject:0,wip:0}),[filtered]);

  const unbalanced=jobCards.filter(card=>!card.qty_balanced);
  const openRejects=quality?.open_reject_no_disposition||[];
  const defects=quality?.defects||[];
  const reworkRows=quality?.rework||[];

  return <div className="page">
    <div className="page-title">
      <div><h1><Printer size={22}/> Printing / Bordir Job Card</h1>
        <p>{meta.total_job_cards} job card · kendali kuantitas &amp; quality</p></div>
      <button className="btn" onClick={load}><RefreshCw size={14}/> Refresh</button>
    </div>
    {err&&<div className="notice danger">{err}</div>}

    {unbalanced.length>0&&<div className="notice danger" style={{display:'flex',alignItems:'center',gap:'8px'}}>
      <AlertTriangle size={16}/> {unbalanced.length} job card tidak seimbang: qty_in &ne; qty_done + qty_reject + WIP
      {' '}({unbalanced.map(c=>c.job_id).join(', ')})
    </div>}
    {openRejects.length>0&&<div className="notice danger" style={{display:'flex',alignItems:'center',gap:'8px'}}>
      <AlertTriangle size={16}/> {openRejects.length} reject belum punya disposition — reject tidak boleh dianggap selesai
    </div>}

    {loading?<div className="page">Memuat...</div>:<>

    <div className="cards">
      <div className="stat blue"><strong>{totals.qty_in}</strong><span>Qty Masuk</span></div>
      <div className="stat green"><strong>{totals.qty_done}</strong><span>Qty Selesai</span></div>
      <div className="stat red"><strong>{totals.qty_reject}</strong><span>Qty Reject</span></div>
      <div className="stat amber"><strong>{totals.wip}</strong><span>WIP Tersisa</span></div>
      <div className={'stat '+passRateTone(quality?.overall_pass_rate)}>
        <strong>{quality?.overall_pass_rate!=null?quality.overall_pass_rate+'%':'-'}</strong><span>Pass Rate Inspeksi</span></div>
      <div className="stat gray"><strong>{quality?.total_rework||0}</strong><span>Rework</span></div>
    </div>

    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/>
        <input placeholder="Cari job id, order, artikel, buyer, SPK..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">
        {['WAITING','IN_PROCESS','DONE'].map(s=><button key={s} className={'pill '+(statusFilter===s?'active '+tone(s):'')}
          onClick={()=>setStatusFilter(statusFilter===s?'':s)}>{s}</button>)}
        <button className={'pill '+(onlyPartial?'active amber':'')} onClick={()=>setOnlyPartial(!onlyPartial)}>
          <Send size={12}/> Partial handoff</button>
      </div>
    </div>

    <div className="table-scroll"><table>
      <thead><tr>
        <th>Job / Order</th><th>Artikel</th><th>Stage</th><th>Versi Requirement</th>
        <th>Qty Masuk</th><th>Selesai</th><th>Reject</th><th>WIP</th><th>Handoff</th>
        <th>Bukti</th><th>Blocker</th><th>PIC / Shift</th><th>Target</th>
      </tr></thead>
      <tbody>{filtered.map(card=><tr key={card.movement_id}>
        <td><b>{card.job_id}</b><div style={{fontSize:'11px',color:'#64748b'}}>{card.order_id} · {card.buyer}</div></td>
        <td>{card.article_code}<div style={{fontSize:'11px',color:'#64748b'}}>{card.route||'route belum diset'}</div></td>
        <td><span className={'badge '+(String(card.stage).toLowerCase().includes('bordir')?'blue':'amber')}>{card.stage}</span></td>
        <td>{card.requirement_version||'-'}
          {card.artwork_version&&<div style={{fontSize:'11px',color:'#64748b'}}>{card.artwork_version}</div>}</td>
        <td>{card.qty_in}</td>
        <td>{card.qty_done}</td>
        <td><span className={card.qty_reject>0?'badge red':'badge gray'}>{card.qty_reject}</span></td>
        <td><b>{card.wip}</b>
          {!card.qty_balanced&&<div className="badge red">mismatch</div>}</td>
        <td>
          {card.partial_handoff
            ? <span className="badge amber"><Send size={11}/> Partial · sisa {card.remaining_balance}</span>
            : <span className="badge green">Saldo {card.remaining_balance}</span>}
          <div style={{fontSize:'11px',color:'#64748b'}}>
            {card.next_handoff?'→ '+card.next_handoff:'tahap akhir'}</div>
        </td>
        <td>{card.required_evidence.map((item,i)=><span key={i} className="badge gray" style={{marginRight:2}}>{item}</span>)}
          <div style={{fontSize:'11px',color:'#64748b'}}>{card.inspection_count} inspeksi · {card.rework_count} rework</div></td>
        <td>{card.blocker
          ? <span className="badge red"><AlertTriangle size={11}/> {card.blocker}</span>
          : card.reject_closed?<span className="badge green">clear</span>:<span className="badge red">reject terbuka</span>}</td>
        <td>{card.pic_name||'-'}<div style={{fontSize:'11px',color:'#64748b'}}>{card.status}</div></td>
        <td>{card.target_date||'-'}</td>
      </tr>)}
      {filtered.length===0&&<tr><td colSpan={13} className="empty">Belum ada job card Printing/Bordir</td></tr>}
      </tbody>
    </table></div>

    <div className="section-title"><Layers size={16}/> Inspeksi &amp; Defect <span className="badge gray">{quality?.total_inspections||0}</span></div>
    <div className="table-scroll"><table>
      <thead><tr><th>Inspeksi</th><th>Artikel</th><th>Proses</th><th>Checked</th><th>Pass</th><th>Reject</th>
        <th>Pass Rate</th><th>Kategori Defect</th><th>Alasan</th><th>Disposition</th><th>Status</th><th>Inspector</th></tr></thead>
      <tbody>{defects.map(d=><tr key={'d'+d.qc_id}>
        <td>#{d.qc_id}</td>
        <td><b>{d.article_code}</b></td>
        <td>{d.process}</td>
        <td>{d.total_checked}</td>
        <td>{d.total_pass}</td>
        <td><span className="badge red">{d.qty_rejected}</span></td>
        <td><span className={'badge '+passRateTone(d.pass_rate)}>{d.pass_rate!=null?d.pass_rate+'%':'-'}</span></td>
        <td><span className="badge amber">{d.defect_category}</span></td>
        <td>{d.defect_detail||<i>alasan belum diisi</i>}</td>
        <td><span className={'badge '+(d.disposition==='OPEN'?'red':d.disposition==='REWORK'?'amber':'green')}>{d.disposition}</span></td>
        <td>{d.status||'-'}</td>
        <td>{d.inspector||'-'}</td>
      </tr>)}
      {defects.length===0&&<tr><td colSpan={12} className="empty">Tidak ada defect tercatat</td></tr>}
      </tbody>
    </table></div>

    <div className="section-title"><ShieldCheck size={16}/> Rework / Remake — wajib retest sebelum handoff
      <span className="badge gray">{quality?.total_rework||0}</span></div>
    <div className="table-scroll"><table>
      <thead><tr><th>Rework</th><th>Dari QC</th><th>Artikel</th><th>Proses</th><th>Qty</th><th>Pass Setelah</th>
        <th>Alasan</th><th>Owner</th><th>Status</th><th>Retest</th></tr></thead>
      <tbody>{reworkRows.map(r=><tr key={'r'+r.qc_id}>
        <td>#{r.qc_id}</td>
        <td>{r.rework_parent_id?'#'+r.rework_parent_id:'-'}</td>
        <td><b>{r.article_code}</b></td>
        <td>{r.process}</td>
        <td>{r.qty_reworked}</td>
        <td>{r.qty_pass_after_rework}</td>
        <td>{r.reason||<i>alasan belum diisi</i>}</td>
        <td>{r.owner||'-'}</td>
        <td><span className={'badge '+(r.status==='PASS'?'green':'amber')}>{r.status}</span></td>
        <td>{r.retest_required?<span className="badge amber">wajib</span>:'-'}</td>
      </tr>)}
      {reworkRows.length===0&&<tr><td colSpan={10} className="empty">Tidak ada rework</td></tr>}
      </tbody>
    </table></div>

    <div className="section-title"><AlertTriangle size={16}/> Reject tanpa Disposition
      <span className="badge red">{quality?.open_reject_count||0}</span></div>
    <div className="table-scroll"><table>
      <thead><tr><th>Inspeksi</th><th>Artikel</th><th>Proses</th><th>Reject</th><th>Severity</th><th>Inspector</th></tr></thead>
      <tbody>{openRejects.map(d=><tr key={'o'+d.qc_id}>
        <td>#{d.qc_id}</td><td>{d.article_code}</td><td>{d.process}</td>
        <td><span className="badge red">{d.qty_rejected}</span></td>
        <td><span className="badge amber">{d.severity}</span></td>
        <td>{d.inspector||'-'}</td>
      </tr>)}
      {openRejects.length===0&&<tr><td colSpan={6} className="empty">Semua reject sudah berdisposisi</td></tr>}
      </tbody>
    </table></div>

    </>}
  </div>
}
