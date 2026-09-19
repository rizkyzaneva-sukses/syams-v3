import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import {AlertTriangle,RefreshCw} from 'lucide-react';

/* Revisi #14 poin 2 — MORNING PRIORITY (CMO Manager).
   Action-first decision queue, bukan dashboard analisis.
   Setiap baris menampilkan kolom wajib antrean keputusan. */

const TONE={RED:'red',YELLOW:'amber',GREEN:'green'};

function QueueSection({queue,role}){
  const rows=queue.rows||[];
  return <section className="panel">
    <div className="panel-head">
      <h2>{queue.label}</h2>
      <span>{rows.length} keputusan · owner {queue.owner}</span>
    </div>
    {rows.length?<div className="table-scroll"><table>
      <thead><tr>
        <th>Task ID</th><th>Buyer</th><th>Order</th><th>Article</th>
        <th>Status</th><th>Evidence / Gate</th><th>Next Action</th>
        <th>Owner</th><th>Due / SLA</th><th>Handoff</th><th>Updated</th>
      </tr></thead>
      <tbody>{rows.map(row=><tr key={row.task_id}>
        <td><b>{row.task_id}</b></td>
        <td>{row.buyer||'—'}</td>
        <td>{row.order_id?<Link to={'/orders/'+row.order_id}>{row.order_id}</Link>:'—'}</td>
        <td>{row.article_code||'—'}</td>
        <td><span className={'badge '+(TONE[row.severity]||'gray')}>{row.status||'—'}</span></td>
        <td>{row.gate||'—'}</td>
        <td>{row.next_action||'—'}</td>
        <td><span className="badge blue">{row.owner||'—'}</span></td>
        <td>{row.due||'—'}</td>
        <td><small>{row.handoff||'—'}</small></td>
        <td><small>{row.updated_at?new Date(row.updated_at+'Z').toLocaleString('id-ID'):'—'}</small></td>
      </tr>)}</tbody>
    </table></div>
    :<p className="empty">Tidak ada keputusan menunggu di antrean ini.</p>}
    <p style={{fontSize:12,color:'#64748b',marginTop:6}}>Handoff berikutnya: {queue.handoff}</p>
  </section>;
}

export default function CMOPriorityPage(){
  const role=useRole();
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);try{setData(await api('/cmo/morning-priority'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat antrean keputusan...</div>;

  const queues=data.queues||[];
  const total=data.total_decisions||0;
  return <div className="page">
    <div className="page-title">
      <div><h1>Morning Priority</h1><p>Antrean keputusan Cecep — action-first, urut sesuai prioritas bisnis.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    <div className="cards">
      <div className={'stat '+(total?'amber':'green')}><strong>{total}</strong><span>Total keputusan menunggu</span></div>
      {queues.map(q=><div className="stat blue" key={q.key}><strong>{(q.rows||[]).length}</strong><span>{q.label}</span></div>)}
    </div>
    <div className="notice info">
      Antrean ini hanya menampilkan keputusan yang menjadi kewenangan CMO Manager.
      Exception produksi, keuangan, dan operasional tetap milik COO, CFO, dan CEO.
    </div>
    {total===0&&<div className="notice success">Tidak ada keputusan komersial yang menunggu hari ini.</div>}
    {queues.map(q=><QueueSection key={q.key} queue={q} role={role}/>)}

    <section className="panel">
      <div className="panel-head"><h2>Master Control — Prioritas Bisnis</h2><span>Read-only</span></div>
      <p style={{fontSize:13,color:'#475569'}}>
        Data Master Control tampil read-only di sini sesuai blueprint. Cecep dapat menetapkan
        prioritas bisnis dan eskalasi; status operasional dan keuangan hanya dapat dibaca.
        Halaman penuh: <Link to="/master">Master Control</Link>.
      </p>
    </section>
  </div>;
}