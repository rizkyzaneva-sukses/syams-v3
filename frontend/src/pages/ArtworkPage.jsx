import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';
import {RefreshCw,Search,Upload,ShieldCheck,Ban,AlertTriangle,FileImage,Send,CheckCircle2} from 'lucide-react';

// Artwork Versioning (workspace Diki). Halaman ini menutup gap PRD §7:
// versi artwork lama yang sudah diganti (SUPERSEDED) atau dibatalkan (OBSOLETE)
// tidak boleh dipakai mencetak. UI tidak menghitung sendiri apakah sebuah versi
// "boleh cetak" — semua flag datang dari server (GET /artwork/can-print &
// field is_printable pada tiap versi) supaya tampilan tidak pernah "terlihat
// boleh" padahal server menolak.

const TYPE_LABEL={SABLON:'Sablon',BORDIR:'Bordir',LABEL:'Label',LAINNYA:'Lainnya'};
const TYPE_TONE={SABLON:'amber',BORDIR:'blue',LABEL:'green',LAINNYA:'gray'};
const WRITE_ROLES=['CMO_SUPPORT','CMO_MANAGER','SAMPLE_PIC','PRINTING_PIC'];
const APPROVE_ROLES=['CMO_SUPPORT','CMO_MANAGER'];
const ACK_ROLES=['PRINTING_PIC','CMO_SUPPORT','CMO_MANAGER'];

function statusTone(status){
  if(status==='APPROVED') return 'green';
  if(status==='SUPERSEDED') return 'gray';
  if(status==='OBSOLETE') return 'red';
  if(status==='SUBMITTED') return 'amber';
  return 'gray';
}

// Badge status versi. SUPERSEDED diberi coret (strikethrough) — tanda visual
// bahwa versi itu sudah tidak berlaku, bukan sekadar status biasa.
function VersionBadge({status}){
  const strike=status==='SUPERSEDED';
  return <span className={'badge '+statusTone(status)}
    style={strike?{textDecoration:'line-through',opacity:0.7}:undefined}>{status}</span>;
}

export default function ArtworkPage(){
  const role=useRole();
  const canWrite=WRITE_ROLES.includes(role);
  const canApprove=APPROVE_ROLES.includes(role);
  const canAck=ACK_ROLES.includes(role);

  const [rows,setRows]=useState([]);
  const [detail,setDetail]=useState(null);
  const [canPrint,setCanPrint]=useState(null);
  const [err,setErr]=useState('');
  const [info,setInfo]=useState('');
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [q,setQ]=useState('');
  const [typeFilter,setTypeFilter]=useState('');

  // Form unggah versi baru
  const [vFileRef,setVFileRef]=useState('');
  const [vFileName,setVFileName]=useState('');
  const [vBuyerRef,setVBuyerRef]=useState('');
  const [vNotes,setVNotes]=useState('');
  // Form serah terima
  const [hToPic,setHToPic]=useState('Iman');
  const [hRegister,setHRegister]=useState('');
  const [hPrinted,setHPrinted]=useState(true);

  function load(){
    setLoading(true);setErr('');
    api('/artwork')
      .then(r=>setRows(r.rows||[]))
      .catch(e=>setErr(e.message))
      .finally(()=>setLoading(false));
  }
  useEffect(load,[]);

  function openDetail(id){
    setErr('');setInfo('');
    api('/artwork/'+id).then(d=>{
      setDetail(d);
      return api('/artwork/can-print?article_id='+d.article_id).then(cp=>setCanPrint(cp));
    }).catch(e=>setErr(e.message));
  }

  async function run(fn,msg){
    setBusy(true);setErr('');setInfo('');
    try{await fn();setInfo(msg||'Berhasil.')}
    catch(e){setErr(e.message)}
    finally{setBusy(false)}
  }

  const filtered=useMemo(()=>rows.filter(r=>{
    if(typeFilter&&r.artwork_type!==typeFilter) return false;
    if(!q) return true;
    const term=q.toLowerCase();
    return [r.title,r.artwork_type,r.article_id,String(r.id)].some(v=>String(v??'').toLowerCase().includes(term));
  }),[rows,q,typeFilter]);

  // Peringatan merah: dipakai kalau ada versi OBSOLETE/SUPERSEDED yang masih
  // "kelihatan" atau kalau guardrail can-print menolak. Ini banner yang diminta
  // gap PRD — "obsolete warning" saat versi lama dicoba dipakai.
  const hasStale=detail?.versions?.some(v=>v.status==='OBSOLETE'||v.status==='SUPERSEDED');
  const blockedByGuard=canPrint&&!canPrint.boleh_cetak;

  function submitVersion(e){
    e.preventDefault();
    run(async()=>{
      await api('/artwork/'+detail.id+'/versions',{method:'POST',body:JSON.stringify({
        file_ref:vFileRef,file_name:vFileName,buyer_reference:vBuyerRef||null,notes:vNotes||null})});
      setVFileRef('');setVFileName('');setVBuyerRef('');setVNotes('');
      openDetail(detail.id);load();
    },'Versi baru diunggah (SUBMITTED). Versi lama yang APPROVED otomatis menjadi SUPERSEDED.');
  }

  function approveVersion(version){
    run(async()=>{
      await api('/artwork/versions/'+version.id+'/approve',{method:'POST'});
      openDetail(detail.id);load();
    },'Versi v'+version.version_no+' disetujui (APPROVED).');
  }

  function obsoleteVersion(version){
    const reason=window.prompt('Alasan menandai versi v'+version.version_no+' OBSOLETE (wajib):');
    if(!reason) return;
    run(async()=>{
      await api('/artwork/versions/'+version.id+'/obsolete',{method:'POST',body:JSON.stringify({reason})});
      openDetail(detail.id);load();
    },'Versi v'+version.version_no+' ditandai OBSOLETE.');
  }

  function handover(version){
    run(async()=>{
      await api('/artwork/versions/'+version.id+'/handover',{method:'POST',body:JSON.stringify({
        to_pic:hToPic||'Iman',printed:hPrinted,print_register_no:hRegister||null})});
      setHRegister('');
      openDetail(detail.id);
    },'Versi v'+version.version_no+' diserahkan ke '+(hToPic||'Iman')+'.');
  }

  function acknowledge(handoverId){
    run(async()=>{
      await api('/artwork/handovers/'+handoverId+'/acknowledge',{method:'POST',body:JSON.stringify({})});
      openDetail(detail.id);
    },'Penerimaan versi dicatat (Iman).');
  }

  return <div className="page">
    <div className="page-title">
      <div><h1><FileImage size={22}/> Artwork Versioning</h1>
        <p>{rows.length} artwork · versi, approval, serah terima ke Printing (Iman)</p></div>
      <button className="btn" onClick={load} disabled={busy}><RefreshCw size={14}/> Refresh</button>
    </div>

    {err&&<div className="notice danger" role="alert"><AlertTriangle size={14}/> {err}</div>}
    {info&&<div className="notice" role="status"><CheckCircle2 size={14}/> {info}</div>}

    <p className="hint" style={{color:'#64748b',fontSize:'12px'}}>
      Guardrail PRD §7: hanya versi <b>APPROVED</b> yang boleh dicetak.
      Versi yang sudah digantikan (<i>SUPERSEDED</i>) atau dibatalkan (<i>OBSOLETE</i>)
      tidak boleh dipakai sebagai versi aktif.
    </p>

    <div className="filter-bar">
      <div className="search-bar"><Search size={16}/>
        <input placeholder="Cari judul / artikel / jenis..." value={q} onChange={e=>setQ(e.target.value)}/></div>
      <div className="filter-pills">
        {Object.keys(TYPE_LABEL).map(t=><button key={t}
          className={'pill '+(typeFilter===t?'active '+TYPE_TONE[t]:'')}
          onClick={()=>setTypeFilter(typeFilter===t?'':t)}>{TYPE_LABEL[t]}</button>)}
      </div>
    </div>

    <div className="table-scroll"><table>
      <thead><tr>
        <th>ID</th><th>Artikel</th><th>Jenis</th><th>Judul</th>
        <th>Versi Aktif</th><th>Status</th><th>Jumlah Versi</th><th>Boleh Cetak</th>
      </tr></thead>
      <tbody>{filtered.map(r=><tr key={r.id} style={{cursor:'pointer'}} onClick={()=>openDetail(r.id)}>
        <td>#{r.id}</td>
        <td>{r.article_id}</td>
        <td><span className={'badge '+TYPE_TONE[r.artwork_type]}>{TYPE_LABEL[r.artwork_type]||r.artwork_type}</span></td>
        <td><b>{r.title}</b></td>
        <td>v{r.current_version_no}</td>
        <td>{r.current_version?<VersionBadge status={r.current_version.status}/>:<span className="badge gray">belum ada</span>}</td>
        <td>{r.version_count}</td>
        <td>{r.current_is_printable
          ? <span className="badge green">ya</span>
          : <span className="badge red">tidak</span>}</td>
      </tr>)}
      {filtered.length===0&&<tr><td colSpan={8} className="empty">Belum ada artwork. {canWrite?'Buat lewat POST /artwork.':''}</td></tr>}
      </tbody>
    </table></div>

    {detail&&<div className="section-title"><FileImage size={16}/> Detail — {detail.title}
      <span className={'badge '+TYPE_TONE[detail.artwork_type]}>{TYPE_LABEL[detail.artwork_type]||detail.artwork_type}</span>
      <span className="badge gray">versi aktif v{detail.current_version_no}</span>
      <button className="btn" style={{marginLeft:'auto'}} onClick={()=>{setDetail(null);setCanPrint(null)}}>Tutup</button>
    </div>}

    {detail&&<>
      {/* BANNER MERAH: guardrail menolak cetak / ada versi basi. */}
      {blockedByGuard&&<div className="notice danger" style={{display:'flex',alignItems:'center',gap:'8px'}}>
        <AlertTriangle size={16}/> <b>Artwork ini TIDAK boleh dicetak.</b> {canPrint.alasan}
      </div>}
      {!blockedByGuard&&canPrint&&<div className="notice" style={{display:'flex',alignItems:'center',gap:'8px'}}>
        <ShieldCheck size={16}/> {canPrint.alasan}
      </div>}
      {hasStale&&<div className="notice danger" style={{display:'flex',alignItems:'center',gap:'8px'}}>
        <Ban size={16}/> Ada versi lama berstatus OBSOLETE/SUPERSEDED pada artwork ini.
        Jangan pakai versi tersebut untuk produksi — gunakan versi APPROVED yang berlaku.
      </div>}

      {/* Form unggah versi baru (pengelola berkas). */}
      {canWrite&&<form className="panel" onSubmit={submitVersion} style={{display:'grid',gap:8,marginTop:12}}>
        <strong><Upload size={14}/> Unggah versi baru (versi lama APPROVED otomatis jadi SUPERSEDED)</strong>
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          <input required placeholder="file_ref (path/URL)" value={vFileRef} onChange={e=>setVFileRef(e.target.value)} style={{flex:2,minWidth:220}}/>
          <input required placeholder="file_name" value={vFileName} onChange={e=>setVFileName(e.target.value)} style={{flex:1,minWidth:160}}/>
          <input placeholder="buyer_reference (opsional)" value={vBuyerRef} onChange={e=>setVBuyerRef(e.target.value)} style={{flex:1,minWidth:160}}/>
        </div>
        <textarea placeholder="catatan revisi (opsional)" value={vNotes} onChange={e=>setVNotes(e.target.value)} rows={2}/>
        <button className="btn primary" type="submit" disabled={busy}><Upload size={14}/> Unggah versi baru</button>
      </form>}

      {/* Riwayat versi. */}
      <div className="section-title"><FileImage size={16}/> Riwayat Versi <span className="badge gray">{detail.versions?.length||0}</span></div>
      <div className="table-scroll"><table>
        <thead><tr>
          <th>Versi</th><th>Status</th><th>Berkas</th><th>Buyer Ref</th><th>Catatan</th>
          <th>Diserahkan / Diterima</th><th>Aksi</th>
        </tr></thead>
        <tbody>{(detail.versions||[]).map(v=><tr key={v.id}
          style={v.status==='SUPERSEDED'?{opacity:0.7}:v.status==='OBSOLETE'?{background:'#fef2f2'}:undefined}>
          <td><b style={v.status==='SUPERSEDED'?{textDecoration:'line-through'}:undefined}>v{v.version_no}</b></td>
          <td><VersionBadge status={v.status}/>
            {v.superseded_by_id&&<div style={{fontSize:'11px',color:'#64748b'}}>→ digantikan v#</div>}</td>
          <td>{v.file_name}<div style={{fontSize:'11px',color:'#64748b'}}>{v.file_ref}</div></td>
          <td>{v.buyer_reference||'-'}</td>
          <td>{v.notes||<i>—</i>}</td>
          <td>
            {v.handovers.length===0&&<span className="badge gray">belum diserahkan</span>}
            {v.handovers.map(h=><div key={h.id} style={{marginBottom:4}}>
              <span className="badge blue"><Send size={10}/> {h.to_pic}</span>
              {h.printed&&<span className="badge gray" style={{marginLeft:4}}>cetak {h.print_register_no||'-'}</span>}
              <div style={{fontSize:'11px',color:'#64748b'}}>
                {h.acknowledged
                  ? <>diterima {h.acknowledged_at?h.acknowledged_at.slice(0,16).replace('T',' '):''}</>
                  : <i>belum diterima</i>}
              </div>
              {!h.acknowledged&&canAck&&<button className="btn" style={{marginTop:2}} disabled={busy}
                onClick={()=>acknowledge(h.id)}><CheckCircle2 size={12}/> Catat terima</button>}
            </div>)}
          </td>
          <td style={{minWidth:200}}>
            {canApprove&&v.status==='SUBMITTED'&&<button className="btn primary" disabled={busy}
              onClick={()=>approveVersion(v)}><ShieldCheck size={12}/> Approve</button>}
            {v.status==='APPROVED'&&canWrite&&<>
              <button className="btn" disabled={busy} onClick={()=>handover(v)}>
                <Send size={12}/> Serah ke Iman</button>
            </>}
            {canWrite&&v.status!=='OBSOLETE'&&v.status!=='SUPERSEDED'&&<button className="btn" style={{marginLeft:4}}
              disabled={busy} onClick={()=>obsoleteVersion(v)}><Ban size={12}/> Obsolete</button>}
            {v.status==='APPROVED'&&<div style={{fontSize:11,color:'#166534',marginTop:4}}>siap cetak</div>}
            {v.status==='SUPERSEDED'&&<div style={{fontSize:11,color:'#b91c1c',marginTop:4}}>tidak boleh dicetak</div>}
            {v.status==='OBSOLETE'&&<div style={{fontSize:11,color:'#b91c1c',marginTop:4}}>dibatalkan</div>}
          </td>
        </tr>)}
        {(detail.versions||[]).length===0&&<tr><td colSpan={7} className="empty">Belum ada versi</td></tr>}
        </tbody>
      </table></div>

      {/* Panel serah terima: pengaturan penerima + register cetak. */}
      {canWrite&&<div className="panel" style={{marginTop:12,display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
        <strong><Send size={14}/> Serah terima ke:</strong>
        <input value={hToPic} onChange={e=>setHToPic(e.target.value)} placeholder="Iman" style={{maxWidth:160}}/>
        <label style={{flexDirection:'row',alignItems:'center',gap:6}}>
          <input type="checkbox" checked={hPrinted} onChange={e=>setHPrinted(e.target.checked)}/> sudah dicetak</label>
        <input value={hRegister} onChange={e=>setHRegister(e.target.value)} placeholder="no. register cetak (opsional)" style={{maxWidth:220}}/>
        <span className="hint" style={{fontSize:'11px',color:'#64748b'}}>Tombol "Serah ke Iman" ada pada baris versi berstatus APPROVED.</span>
      </div>}
    </>}

    {loading&&<div className="page">Memuat...</div>}
  </div>;
}
