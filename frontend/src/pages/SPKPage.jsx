import React,{useEffect,useState} from 'react';
import {useOutletContext} from 'react-router-dom';
import {api} from '../api';
import {Plus,Edit2,Trash2,X,Check,Search,Eye,Printer,FileCheck2,Ban,RefreshCw,SendHorizontal,ShieldCheck,AlertTriangle} from 'lucide-react';
import {isOverdue} from '../queue';

/* Revisi #9 poin 9 — SPK (CMO Support).
   Satu baris SPK harus menjawab: apa dokumennya (SPK ID + versi), order/artikel
   mana yang dibekukan, gate komersial dan gate Sample/PPM-nya lolos atau tidak,
   sudah di-Generate/Preview/Print atau belum, siapa yang me-release serta kapan,
   dan apakah batch COO sudah dilepas (status terpisah, bukan milik CMO).

   Dua prinsip keras yang tidak boleh dilanggar tampilan ini:
   1. PRINT BUKAN RELEASE — aksi Print hanya menghasilkan dokumen, release tetap
      milik CMO Manager (Cecep), jadi tombol Release tidak pernah muncul untuk
      CMO Support.
   2. SPK RELEASE BUKAN BATCH RELEASE — kolom "Batch Release COO" hanya membaca
      status shipment; eksekusinya milik COO dan tidak bisa diubah dari sini.

   CATATAN DATA: model SPK belum menyimpan printed_by / printed_at / print_count /
   reprint_reason. Yang tersedia hanya status hasil print (PRINTED), jadi kolom
   print di bawah adalah status turunan — bukan riwayat cetak per user. */

const empty={spk_no:'',order_fk:'',notes:''};
const statusOpts=['DRAFT','GENERATED','PRINTED','RELEASED','VOID'];
/* Urutan proses yang ditampilkan (DRAFT → GENERATED → PRINTED → RELEASED). */
const flowOpts=['DRAFT','GENERATED','PRINTED','RELEASED'];
const STATUS_LABEL={DRAFT:'Draft',GENERATED:'Generated',PRINTED:'Printed',RELEASED:'Released',VOID:'Void'};
const STATUS_TONE={DRAFT:'gray',GENERATED:'amber',PRINTED:'blue',RELEASED:'green',VOID:'red'};

function fmt(value){
  if(!value)return '—';
  const text=String(value);
  const safe=/[zZ]|[+-]\d\d:?\d\d$/.test(text)?text:text+'Z';
  const d=new Date(safe);
  return isNaN(d.getTime())?text:d.toLocaleString('id-ID');
}
function fmtDate(value){return value?String(value).slice(0,10):'—'}

/* Artikel yang dibekukan di dalam snapshot SPK saat Generate. */
function snapshotArticles(snapshot){
  if(!snapshot)return [];
  try{
    const parsed=JSON.parse(snapshot);
    if(Array.isArray(parsed))return parsed;
    if(parsed&&Array.isArray(parsed.articles))return parsed.articles;
    return [];
  }catch{return []}
}
function snapshotHeader(snapshot){
  if(!snapshot)return null;
  try{const parsed=JSON.parse(snapshot);return parsed&&!Array.isArray(parsed)?parsed:null;}catch{return null}
}
/* Tanggal & user yang membekukan dokumen — disimpan di dalam snapshot. */
function generatedLine(spk){
  const head=snapshotHeader(spk.snapshot);
  if(!head)return null;
  const at=fmtDate(head.generated_at);
  return {at,by:head.generated_by||head.printed_by||null};
}

export default function SPKPage(){
  const role=useOutletContext()?.me?.role;
  const manager=role==='CMO_MANAGER';
  const preparer=manager||role==='CMO_SUPPORT';
  const [list,setList]=useState([]),[orders,setOrders]=useState([]),[ships,setShips]=useState([]);
  const [err,setErr]=useState(''),[q,setQ]=useState(''),[filterStatus,setFilterStatus]=useState('');
  const [form,setForm]=useState(null),[busy,setBusy]=useState(false),[preview,setPreview]=useState('');
  const [releaseTarget,setReleaseTarget]=useState(null),[readiness,setReadiness]=useState(null);
  const [releaseReason,setReleaseReason]=useState(''),[correctionReason,setCorrectionReason]=useState('');
  const [detail,setDetail]=useState(null),[ready,setReady]=useState({});
  const [gateTarget,setGateTarget]=useState(null),[gateReadiness,setGateReadiness]=useState(null);

  async function load(){
    try{
      const [s,o,sh]=await Promise.all([
        api('/cmo/spk'),
        api('/orders'),
        /* Shipment hanya dibaca untuk status Batch Release COO. Kalau endpoint
           ini ditolak untuk peran ini, halaman tetap jalan tanpa kolom itu. */
        api('/coo/shipments').catch(()=>[]),
      ]);
      setList(s);setOrders(o);setShips(Array.isArray(sh)?sh:[]);setErr('');
    }catch(e){setErr(e.message);}
  }
  useEffect(()=>{load()},[]);
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview]);

  const orderOf=id=>orders.find(o=>o.id===id)||null;
  const orderLabel=id=>orderOf(id)?.order_id||String(id);
  const shipmentsOf=id=>ships.filter(s=>s.order_fk===id);

  /* Batch Release COO. Shipment dibuat COO/Shipment Admin; CMO hanya membaca. */
  function batchRelease(orderFk){
    const rows=shipmentsOf(orderFk);
    if(!rows.length)return {available:false,text:'Belum ada batch',tone:'gray'};
    const delivered=rows.filter(s=>s.status==='DELIVERED').length;
    const shipped=rows.filter(s=>s.status==='SHIPPED').length;
    if(delivered)return {available:true,text:`Dilepas · ${delivered}/${rows.length} delivered`,tone:'green'};
    if(shipped)return {available:true,text:`Dikirim · ${shipped}/${rows.length} shipped`,tone:'amber'};
    return {available:true,text:`Menunggu gate · ${rows.length} batch`,tone:'gray'};
  }

  /* Ringkasan gate komersial & Sample/PPM dari prasyarat yang tercatat di SPK. */
  function releaseSummary(spk){
    if(!spk.release_prerequisites)return null;
    try{return JSON.parse(spk.release_prerequisites);}catch{return null}
  }
  function releaseChecks(spk){
    const stored=releaseSummary(spk);
    return stored&&stored.checks?stored.checks:null;
  }
  /* Sebelum release, prasyarat belum tersimpan di SPK: pakai readiness terakhir
     yang sudah diambil dari server untuk baris ini saja. */
  function checksFor(spk){return releaseChecks(spk)||(gateTarget&&gateTarget.id===spk.id?gateReadiness?.checks:null)}
  function gateState(spk){
    const checks=checksFor(spk);
    if(!checks)return {state:'BELUM_DIPERIKSA',tone:'gray',fails:[]};
    const fails=Object.values(checks).filter(c=>!c.ok).map(c=>c.label);
    return fails.length?{state:'TERTAHAN',tone:'red',fails}:{state:'LOLOS',tone:'green',fails:[]};
  }
  function commercialGate(spk){
    const checks=checksFor(spk);
    if(!checks)return {text:'Belum diperiksa',tone:'gray'};
    const keys=['quotation_approved','finance_approved'];
    if(!keys.some(k=>checks[k]))return {text:'Belum diperiksa',tone:'gray'};
    const fails=keys.filter(k=>checks[k]&&!checks[k].ok).map(k=>checks[k].label);
    return fails.length?{text:'Tertahan',tone:'red',note:fails.join(' · ')}:{text:'Lolos',tone:'green'};
  }
  function sampleGate(spk){
    const checks=checksFor(spk);
    if(!checks||!checks.samples_approved)return {text:'Belum diperiksa',tone:'gray'};
    return checks.samples_approved.ok
      ?{text:'Sample/PPM disetujui',tone:'green'}
      :{text:'Belum lengkap',tone:'red',note:checks.samples_approved.label};
  }

  async function checkGates(spk){
    setGateTarget(spk);setGateReadiness(null);setErr('');
    try{
      const r=await api(`/cmo/spk/${spk.id}/release-readiness`);
      setGateReadiness(r);
      setReady(p=>({...p,[spk.id]:r.ready?'SIAP':'BELUM_SIAP'}));
    }catch(e){
      /* Readiness adalah wewenang CMO Manager — untuk CMO Support cukup dicatat
         bahwa statusnya tidak dapat diperiksa dari peran ini. */
      setReady(p=>({...p,[spk.id]:'TIDAK_TERSEDIA'}));
      setErr(`${spk.spk_no}: ${e.message}`);
    }
  }

  const filtered=list.filter(s=>{
    if(filterStatus&&s.status!==filterStatus)return false;
    const term=q.trim().toLowerCase();
    const order=orderOf(s.order_fk);
    return !term||[s.spk_no,s.notes,s.correction_reason,s.release_reason,order?.order_id,order?.buyer]
      .some(v=>String(v||'').toLowerCase().includes(term));
  });

  const counts=statusOpts.reduce((acc,s)=>({...acc,[s]:list.filter(x=>x.status===s).length}),{});
  const dueSoon=list.filter(s=>['DRAFT','GENERATED','PRINTED'].includes(s.status)&&isOverdue(orderOf(s.order_fk)?.buyer_deadline)).length;
  const waitingBatch=list.filter(s=>s.status==='RELEASED'&&orderOf(s.order_fk)&&!batchRelease(s.order_fk).text.startsWith('Dilepas')).length;

  async function save(ev){
    ev.preventDefault();setBusy(true);setErr('');
    try{
      if(form.id)await api(`/cmo/spk/${form.id}`,{method:'PATCH',body:JSON.stringify({notes:form.notes})});
      else await api('/cmo/spk',{method:'POST',body:JSON.stringify({spk_no:form.spk_no.trim(),order_fk:Number(form.order_fk),notes:form.notes})});
      setForm(null);await load();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  async function act(spk,action){
    if(action==='void'&&!confirm(`Void SPK ${spk.spk_no}?`))return;
    if(action==='delete'&&!confirm(`Hapus draft SPK ${spk.spk_no}?`))return;
    setBusy(true);setErr('');
    try{
      if(action==='delete')await api(`/cmo/spk/${spk.id}`,{method:'DELETE'});
      else await api(`/cmo/spk/${spk.id}/${action}`,{method:'POST'});
      await load();
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }

  async function openRelease(spk){
    setReleaseTarget(spk);setReadiness(null);setReleaseReason('');setCorrectionReason('');setErr('');
    try{setReadiness(await api(`/cmo/spk/${spk.id}/release-readiness`));}
    catch(e){setErr(e.message);setReleaseTarget(null);}
  }

  async function submitRelease(ev){
    ev.preventDefault();if(!releaseTarget)return;
    setBusy(true);setErr('');
    try{
      await api(`/cmo/spk/${releaseTarget.id}/release`,{method:'POST',body:JSON.stringify({
        version_id:releaseTarget.id,reason:releaseReason.trim(),
        correction_reason:correctionReason.trim()||null})});
      setReleaseTarget(null);setReadiness(null);await load();
    }catch(e){setErr(e.message);try{setReadiness(await api(`/cmo/spk/${releaseTarget.id}/release-readiness`))}catch{}}
    finally{setBusy(false)}
  }

  async function showPdf(spk,print=false){
    setBusy(true);setErr('');
    const tab=print?window.open('','_blank'):null;
    try{
      const blob=await api(`/cmo/spk/${spk.id}/${print?'print':'pdf'}`,
        print?{method:'POST',responseType:'blob'}:{responseType:'blob'});
      const url=URL.createObjectURL(blob);
      if(print){
        if(tab){tab.location.href=url;tab.onload=()=>{try{tab.print()}catch{}};}
        else{setPreview(url);setErr('PDF siap. Gunakan tombol Print di penampil PDF.');}
        setTimeout(()=>URL.revokeObjectURL(url),120000);
        await load();
      }else setPreview(url);
    }catch(e){if(tab)tab.close();setErr(e.message)}finally{setBusy(false)}
  }

  const gates=detail?checksFor(detail):null;

  return <div className="page">
    <div className="page-title">
      <div><h1>SPK</h1><p>Draft → Generate → Preview PDF → Print → Release CMO. Print tidak merilis SPK, dan Release CMO bukan Batch Release COO.</p></div>
      <div className="table-scroll">
        <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
        {preparer&&<button className="btn primary" disabled={busy} onClick={()=>setForm({...empty})}><Plus size={16}/> Buat Draft</button>}
      </div>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="cards compact">
      <div className={'stat '+(counts.DRAFT?'gray':'green')}><strong>{counts.DRAFT}</strong><span>Draft belum di-Generate</span></div>
      <div className={'stat '+(counts.GENERATED?'amber':'green')}><strong>{counts.GENERATED}</strong><span>Generated — menunggu Print</span></div>
      <div className={'stat '+(counts.PRINTED?'blue':'green')}><strong>{counts.PRINTED}</strong><span>Printed — menunggu Release CMO</span></div>
      <div className="stat green"><strong>{counts.RELEASED}</strong><span>Released CMO</span></div>
      <div className={'stat '+(waitingBatch?'amber':'green')}><strong>{waitingBatch}</strong><span>Menunggu Batch Release COO</span></div>
    </div>

    {dueSoon>0&&<div className="notice danger" role="alert">
      <AlertTriangle size={14}/> {dueSoon} SPK belum release sementara deadline buyer-nya sudah lewat. Selesaikan Generate/Print lalu minta Cecep me-release.
    </div>}

    <div className="notice info">
      <b>Print bukan Release</b> — Deby hanya menyiapkan dokumen (Generate, Preview, Print).
      <b> Release CMO bukan Batch Release</b> — pelepasan SPK ke produksi milik CMO Manager (Cecep),
      sedangkan pelepasan batch / eksekusi pengiriman milik COO. Kolom batch di bawah hanya informasi.
    </div>

    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/><input aria-label="Cari SPK" placeholder="Cari nomor SPK, order, buyer, catatan, alasan..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">{statusOpts.map(s=><button key={s} className={'pill '+(filterStatus===s?'active '+STATUS_TONE[s]:'')} onClick={()=>setFilterStatus(filterStatus===s?'':s)}>{STATUS_LABEL[s]} ({counts[s]})</button>)}</div>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>SPK ID / Version</th><th>Order / Article</th><th>Commercial Gate</th><th>Sample / PPM Gate</th>
      <th>Generated / Previewed / Printed</th><th>Printed by / at</th><th>Print count</th><th>Reprint reason</th>
      <th>Release CMO (Cecep)</th><th>Batch Release COO</th><th>Catatan</th><th>Aksi</th>
    </tr></thead>
      <tbody>{filtered.map(s=>{
        const order=orderOf(s.order_fk);
        const arts=snapshotArticles(s.snapshot);
        const gate=gateState(s);
        const cg=commercialGate(s);
        const sg=sampleGate(s);
        const gen=generatedLine(s);
        const rel=releaseChecks(s);
        const batch=batchRelease(s.order_fk);
        const generated=['GENERATED','PRINTED','RELEASED'].includes(s.status);
        const printed=['PRINTED','RELEASED'].includes(s.status);
        return <tr key={s.id}>
          <td>
            <b>{s.spk_no}</b><br/><small>ID #{s.id} · versi v{s.version}</small><br/>
            <span className={'badge '+(STATUS_TONE[s.status]||'gray')}>{STATUS_LABEL[s.status]||s.status}</span>
          </td>
          <td>
            {order?<><a href={'/orders/'+order.order_id}>{order.order_id}</a><br/><small>{order.buyer||'—'}</small></>:<a href={'/orders/'+s.order_fk}>{orderLabel(s.order_fk)}</a>}
            <br/><small>{arts.length?arts.map(a=>`${a.article_code||'—'} ×${a.qty??'—'}`).join(', '):'Artikel belum dibekukan (belum di-Generate)'}</small>
            {order?.buyer_deadline&&<><br/>{isOverdue(order.buyer_deadline)
              ?<span className="badge red">Deadline {order.buyer_deadline} · lewat</span>
              :<span className="badge gray">Deadline {order.buyer_deadline}</span>}</>}
          </td>
          <td>
            <span className={'badge '+cg.tone}>{cg.text}</span>
            {cg.note?<><br/><small>{cg.note}</small></>:null}
            {rel?<><br/><small>Diperiksa {fmtDate(rel.checked_at)}</small></>:null}
          </td>
          <td>
            <span className={'badge '+sg.tone}>{sg.text}</span>
            {sg.note?<><br/><small>{sg.note}</small></>:null}
          </td>
          <td>
            <span className={'badge '+(generated?'green':'gray')}>{generated?'Generated':'Belum'}</span>
            <span className={'badge '+(generated?'green':'gray')} style={{marginLeft:4}}>{generated?'Preview PDF':'—'}</span>
            <span className={'badge '+(printed?'green':'gray')} style={{marginLeft:4}}>{printed?'Printed':'Belum'}</span>
            {gen?<><br/><small>Snapshot {gen.at}{gen.by?` · user #${gen.by}`:''}</small></>:<br/>}
          </td>
          {/* printed_by / printed_at tidak ada di API SPK — hanya tanggal snapshot. */}
          <td>{printed?(gen?<><span className="badge gray">bukti: snapshot {gen.at}</span></>:<span className="badge gray">tidak tercatat di API</span>):'—'}</td>
          <td>{printed?'1× (status)':'—'} <br/><small>tidak tersedia di API</small></td>
          <td>{s.correction_reason||'—'}</td>
          <td>
            {s.released_at
              ?<><span className="badge green">Released v{s.released_version??s.version}</span><br/>
                 <small>{fmt(s.released_at)}<br/>user #{s.released_by??'—'}</small></>
              :s.status==='RELEASED'
                ?<span className="badge amber">Riwayat lama — approver tidak tercatat</span>
                :<span className="badge gray">Belum release</span>}
            {s.release_reason?(<><br/><small title={s.release_reason}>Alasan: {s.release_reason.length>60?s.release_reason.slice(0,60)+'…':s.release_reason}</small></>):null}
          </td>
          <td>
            <span className={'badge '+batch.tone}>{batch.text}</span><br/>
            <small>eksekusi milik COO</small>
          </td>
          <td>{s.notes||'—'}</td>
          <td className="td-action">
            <button className="btn sm" disabled={busy} onClick={()=>setDetail(s)}><Eye size={14}/> Detail</button>
            <button className="btn sm" disabled={busy} onClick={()=>checkGates(s)}><ShieldCheck size={14}/> Cek Gate</button>
            {preparer&&s.status==='DRAFT'&&<>
              <button className="btn sm" disabled={busy} onClick={()=>setForm({id:s.id,notes:s.notes||''})}><Edit2 size={14}/> Edit</button>
              <button className="btn sm primary" disabled={busy} onClick={()=>act(s,'generate')}><FileCheck2 size={14}/> Generate</button>
            </>}
            {preparer&&['GENERATED','PRINTED','RELEASED'].includes(s.status)&&<button className="btn sm" disabled={busy} onClick={()=>showPdf(s)}><Eye size={14}/> Preview PDF</button>}
            {preparer&&['GENERATED','PRINTED'].includes(s.status)&&<button className="btn sm" disabled={busy} onClick={()=>showPdf(s,true)}><Printer size={14}/> Print</button>}
            {manager&&s.status==='PRINTED'&&<button className="btn sm primary" disabled={busy} onClick={()=>openRelease(s)}><Check size={14}/> Release</button>}
            {manager&&['DRAFT','GENERATED','PRINTED'].includes(s.status)&&<button className="btn sm" disabled={busy} onClick={()=>act(s,'void')}><Ban size={14}/> Void</button>}
            {manager&&s.status==='DRAFT'&&<button className="icon-btn danger" disabled={busy} onClick={()=>act(s,'delete')} title="Hapus draft"><Trash2 size={15}/></button>}
          </td>
        </tr>})}
        {filtered.length===0&&<tr><td colSpan={12} className="empty">Tidak ada SPK yang cocok dengan filter.</td></tr>}
      </tbody></table></div>

    {detail&&<div className="modal-bg" onClick={()=>setDetail(null)}><div className="modal" style={{width:'min(96vw,1100px)'}} onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>Detail SPK · {detail.spk_no} v{detail.version}</h2>
        <button className="icon-btn" onClick={()=>setDetail(null)}><X size={18}/></button></div>
      <div className="cards compact">
        <div className="mini"><b>{STATUS_LABEL[detail.status]||detail.status}</b><small>Status</small></div>
        <div className="mini"><b>v{detail.version}</b><small>Version</small></div>
        <div className="mini"><b>{snapshotArticles(detail.snapshot).length}</b><small>Artikel dibekukan</small></div>
        <div className="mini"><b>{detail.released_version?'v'+detail.released_version:'—'}</b><small>Versi di-release</small></div>
        <div className="mini"><b>{batchRelease(detail.order_fk).available?'Ada':'—'}</b><small>Batch COO</small></div>
      </div>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2>Gate & prasyarat</h2>
            <span>{gates?'tercatat saat release':'belum diperiksa'}</span></div>
          {gates?<div className="table-scroll"><table><thead><tr><th>Prasyarat</th><th>Hasil</th></tr></thead>
            <tbody>{Object.entries(gates).map(([key,check])=><tr key={key}>
              <td>{check.label||key}</td>
              <td><span className={'badge '+(check.ok?'green':'red')}>{check.ok?'Lolos':'Belum'}</span></td>
            </tr>)}</tbody></table></div>
            :<p className="empty">Prasyarat release belum tersimpan untuk SPK ini. Tekan <b>Cek Gate</b> pada baris untuk memeriksa versi terkunci ini (kewenangan CMO Manager).</p>}
        </section>

        <section className="panel">
          <div className="panel-head"><h2>Release CMO & Batch Release</h2><span>dua langkah terpisah</span></div>
          <div className="table-scroll"><table><tbody>
            <tr><th>Release CMO</th><td>{detail.released_at
              ?<><span className="badge green">Released</span> {fmt(detail.released_at)}</>
              :<span className="badge gray">Belum</span>}</td></tr>
            <tr><th>Released by</th><td>{detail.released_by?`user #${detail.released_by}`:'—'}</td></tr>
            <tr><th>Versi di-release</th><td>{detail.released_version?'v'+detail.released_version:'—'}</td></tr>
            <tr><th>Release reason</th><td style={{whiteSpace:'normal'}}>{detail.release_reason||'—'}</td></tr>
            <tr><th>Correction reason</th><td style={{whiteSpace:'normal'}}>{detail.correction_reason||'—'}</td></tr>
            <tr><th>Batch Release COO</th><td><span className={'badge '+batchRelease(detail.order_fk).tone}>{batchRelease(detail.order_fk).text}</span></td></tr>
            <tr><th>Shipment batch</th><td>
              {shipmentsOf(detail.order_fk).length?shipmentsOf(detail.order_fk).map(sh=><div key={sh.id}>
                <small>{sh.shipment_no} · {sh.status} · {sh.packing_status||'—'}{sh.tracking_no?` · ${sh.tracking_no}`:''}</small></div>)
                :<small>Belum ada batch dibuat COO.</small>}
            </td></tr>
            <tr><th>Dibuat</th><td>{fmt(detail.created_at)}</td></tr>
          </tbody></table></div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Order & artikel pada dokumen</h2>
          <span>{orderLabel(detail.order_fk)}</span></div>
        {snapshotArticles(detail.snapshot).length?<div className="table-scroll"><table>
          <thead><tr><th>Article</th><th>Jenis</th><th>Qty</th><th>Size</th><th>Rute Produksi</th></tr></thead>
          <tbody>{snapshotArticles(detail.snapshot).map((a,i)=><tr key={i}>
            <td><b>{a.article_code||'—'}</b></td><td>{a.garment_type||'—'}</td><td>{a.qty??'—'}</td>
            <td>{a.size_breakdown||'—'}</td><td style={{whiteSpace:'normal'}}>{a.production_route||'—'}</td>
          </tr>)}</tbody></table></div>
        :<p className="empty">Snapshot artikel belum ada. Dokumen dibekukan saat SPK di-Generate.</p>}
        <p style={{fontSize:12,color:'#64748b',marginTop:6}}>
          Catatan SPK: {detail.notes||'—'}
        </p>
      </section>

      <div className="modal-foot"><button type="button" className="btn" onClick={()=>setDetail(null)}>Tutup</button></div>
    </div></div>}

    {form&&<div className="modal-bg" onClick={()=>setForm(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.id?'Edit Draft':'Buat Draft SPK'}</h2><button className="icon-btn" onClick={()=>setForm(null)}><X size={18}/></button></div>
      <form onSubmit={save}>
        {!form.id&&<div className="form-grid">
          <label>No. SPK *<input required value={form.spk_no} onChange={e=>setForm({...form,spk_no:e.target.value})} placeholder="SPK-001"/></label>
          <label>Order *<select required value={form.order_fk} onChange={e=>setForm({...form,order_fk:e.target.value})}><option value="">Pilih order...</option>{orders.filter(o=>o.order_type!=='SAMPLE_ONLY').map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}</select></label>
        </div>}
        <label>Catatan<textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} rows={3}/></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={busy}><Check size={14}/> Simpan Draft</button></div>
      </form>
    </div></div>}

    {preview&&<div className="modal-bg" onClick={()=>setPreview('')}><div className="modal" style={{width:'min(95vw,1000px)'}} onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>Preview PDF SPK</h2><button className="icon-btn" onClick={()=>setPreview('')}><X size={18}/></button></div>
      <iframe title="Preview PDF SPK" src={preview} style={{width:'100%',height:'75vh',border:0}}/>
    </div></div>}

    {releaseTarget&&<div className="modal-bg" onClick={()=>setReleaseTarget(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>CMO SPK Release · {releaseTarget.spk_no} v{releaseTarget.version}</h2><button className="icon-btn" onClick={()=>setReleaseTarget(null)}><X size={18}/></button></div>
      <p>Versi dokumen #{releaseTarget.id}. Release ini mengesahkan SPK ke produksi; pelepasan batch COO adalah langkah terpisah.</p>
      {!readiness?<p>Memeriksa prasyarat...</p>:<div>
        {Object.entries(readiness.checks).map(([key,check])=><div key={key} style={{marginBottom:6}}>
          <span className={'badge '+(check.ok?'green':'red')}>{check.ok?'Siap':'Belum'}</span> {check.label}
        </div>)}
      </div>}
      <form onSubmit={submitRelease}>
        <label>Alasan release *<textarea required maxLength={2000} value={releaseReason} onChange={e=>setReleaseReason(e.target.value)} rows={3}/></label>
        {releaseTarget.version>1&&<label>Alasan koreksi versi *<textarea required maxLength={2000} value={correctionReason} onChange={e=>setCorrectionReason(e.target.value)} rows={3}/></label>}
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setReleaseTarget(null)}>Batal</button>
          <button className="btn primary" disabled={busy||!readiness?.ready||!releaseReason.trim()||(releaseTarget.version>1&&!correctionReason.trim())}><SendHorizontal size={14}/> Release versi ini</button></div>
      </form>
    </div></div>}
  </div>;
}
