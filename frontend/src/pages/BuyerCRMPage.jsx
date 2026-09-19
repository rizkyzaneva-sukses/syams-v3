import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import {RefreshCw,Users} from 'lucide-react';
import {isOverdue} from '../queue';

/* Revisi #14 poin 6 — Buyer CRM.
   Buyer/Opportunity, stage, customer commitment, after-sales, next action,
   next follow-up, owner dan repeat opportunity. Sesuai blueprint terkunci,
   customer commitment dan after-sales berada di sini — bukan menu terpisah. */

export default function BuyerCRMPage(){
  const role=useRole();
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false),[q,setQ]=useState('');
  async function load(){setBusy(true);try{setData(await api('/cmo/buyer-crm'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat Buyer CRM...</div>;

  const term=q.trim().toLowerCase();
  const rows=(data.rows||[]).filter(r=>!term||[r.buyer,r.contact_name,r.country].some(v=>String(v||'').toLowerCase().includes(term)));

  return <div className="page">
    <div className="page-title">
      <div><h1>Buyer CRM</h1><p>Buyer, komitmen pelanggan, after-sales, dan peluang repeat order.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">
      <div className="stat blue"><strong>{data.total_buyers}</strong><span>Total buyer</span></div>
      <div className="stat green"><strong>{data.repeat_buyers}</strong><span>Buyer repeat</span></div>
      <div className="stat amber"><strong>{rows.filter(r=>r.active_orders>0).length}</strong><span>Punya order aktif</span></div>
    </div>

    <input aria-label="Cari buyer" placeholder="Cari buyer, kontak, atau negara" value={q} onChange={e=>setQ(e.target.value)}/>

    <div className="table-scroll"><table><thead><tr>
      <th>Buyer</th><th>Kontak</th><th>Orders</th><th>Komitmen Pelanggan</th>
      <th>Next Action</th><th>Next Follow-up</th><th>Owner</th><th>After Sales</th><th>Repeat</th>
    </tr></thead><tbody>
      {rows.map(r=><tr key={r.buyer}>
        <td><b>{r.buyer}</b>{r.country?<><br/><small>{r.country}</small></>:null}</td>
        <td>{r.contact_name||'—'}<br/><small>{r.contact_info||''}</small></td>
        <td>{r.total_orders} total · {r.active_orders} aktif{r.latest_order_id?<><br/><Link to={'/orders/'+r.latest_order_id}>{r.latest_order_id}</Link></>:null}</td>
        <td>{r.customer_commitment||'—'}</td>
        <td>{r.next_action}</td>
        <td>{r.next_follow_up
          ?(isOverdue(r.next_follow_up)?<span className="badge red">{r.next_follow_up} · lewat</span>:<span className="badge amber">{r.next_follow_up}</span>)
          :'—'}</td>
        <td><span className="badge gray">{r.owner}</span></td>
        <td>{r.after_sales
          ?<><span className={'badge '+(r.after_sales.status==='CONFIRMED'?'green':'amber')}>{r.after_sales.status}</span>
             {r.after_sales.confirmation_date?<small><br/>{r.after_sales.confirmation_date}</small>:null}
             {r.after_sales.feedback?<small><br/>{r.after_sales.feedback}</small>:null}</>
          :<span className="badge gray">Belum ada</span>}</td>
        <td>{r.repeat_opportunity?'Ya':'—'}</td>
      </tr>)}
      {!rows.length&&<tr><td colSpan={9} className="empty">Belum ada buyer terdaftar.</td></tr>}
    </tbody></table></div>

    {['CMO_MANAGER','CEO'].includes(role)&&<div className="notice info">
      Data kontak buyer dikelola di <Link to="/cmo/customers">Customer / Buyer</Link>.
      Komitmen pelanggan dan after-sales tercatat otomatis dari order dan konfirmasi pengiriman.
    </div>}
  </div>;
}