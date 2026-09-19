import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw} from 'lucide-react';
import {isOverdue} from '../queue';

/* Revisi #9 poin 2 — HALAMAN HARI INI (CMO Support / Deby).
   Action-first: daftar kerja Deby, bukan dashboard analisis.
   Setiap baris memakai kolom wajib antrean (poin 3) dan membuka Order terkait.
   Aksi yang menjadi milik Cecep/CFO/COO hanya tampil sebagai informasi. */

function Section({queue}){
  const rows=queue.rows||[];
  return <section className="panel">
    <div className="panel-head">
      <h2>{queue.label}</h2>
      <span>{rows.length} tugas · owner {queue.owner}</span>
    </div>
    {rows.length?<div className="table-scroll"><table>
      <thead><tr>
        <th>Task ID</th><th>Buyer</th><th>Order</th><th>Article</th><th>Tahap</th>
        <th>Status</th><th>Data / Bukti Kurang</th><th>Next Action</th>
        <th>Owner</th><th>Due / SLA</th><th>Source / Evidence</th><th>Updated</th>
      </tr></thead>
      <tbody>{rows.map(r=><tr key={r.task_id}>
        <td><b>{r.task_id}</b></td>
        <td>{r.buyer||'—'}</td>
        <td>{r.order_id?<Link to={'/orders/'+r.order_id}>{r.order_id}</Link>:'—'}</td>
        <td>{r.article_code||'—'}</td>
        <td><span className="badge blue">{r.decision_type}</span></td>
        <td><span className={'badge '+(['SUBMITTED','NEEDS_INFO'].includes(r.status)?'amber':r.status==='READY'?'green':'gray')}>{r.status||'—'}</span></td>
        <td>{r.missing&&r.missing!=='Lengkap'&&r.missing!=='—'
          ?<span className="badge amber">{r.missing}</span>
          :<span className="badge green">{r.missing||'—'}</span>}</td>
        <td>{r.next_action}</td>
        <td><span className={'badge '+(r.owner==='CMO_SUPPORT'?'blue':'gray')}>{r.owner}</span></td>
        <td>{r.due?(isOverdue(r.due)?<span className="badge red">{r.due} · lewat</span>:r.due):'—'}</td>
        <td><small>{r.source||'—'}</small></td>
        <td><small>{r.updated_at?new Date(r.updated_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
      </tr>)}</tbody>
    </table></div>
    :<p className="empty">Tidak ada tugas di antrean ini.</p>}
    <p style={{fontSize:12,color:'#64748b',marginTop:6}}>Handoff berikutnya: {queue.handoff}</p>
  </section>;
}

export default function DebyTodayPage(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);try{setData(await api('/cmo/deby-today'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat daftar kerja...</div>;

  const queues=data.queues||[];
  const total=data.total_tasks||0;
  const own=queues.filter(q=>q.owner==='CMO_SUPPORT').reduce((n,q)=>n+(q.rows||[]).length,0);
  return <div className="page">
    <div className="page-title">
      <div><h1>Hari Ini</h1><p>Daftar kerja Deby — apa yang harus disiapkan dan siapa yang menunggu.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">
      <div className={'stat '+(own?'amber':'green')}><strong>{own}</strong><span>Tugas untuk Deby</span></div>
      <div className="stat blue"><strong>{total}</strong><span>Total baris antrean</span></div>
      <div className="stat gray"><strong>{total-own}</strong><span>Menunggu divisi lain</span></div>
    </div>

    {total===0&&<div className="notice success">Tidak ada tugas menunggu hari ini.</div>}

    <div className="notice info">
      Antrean ini hanya menampilkan pekerjaan persiapan milik CMO Support.
      Keputusan komersial, Release SPK, verifikasi pembayaran, eksekusi pengiriman
      dan penutupan order tetap milik Cecep, CFO dan COO.
    </div>

    {queues.map(q=><Section key={q.key} queue={q}/>)}
  </div>;
}