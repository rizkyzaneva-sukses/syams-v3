import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {RefreshCw} from 'lucide-react';

/* Revisi #14 poin 8 — Reports CMO.
   Performa pipeline, conversion, quotation, sample approval, order activation,
   SPK release, SLA dan customer commitment. Read-only: laporan ini tidak boleh
   mengubah data operasional atau keuangan. */

const pct=v=>v==null?'—':v+'%';
const money=n=>n==null?'—':'Rp '+Number(n).toLocaleString('id-ID');

function Block({title,note,rows}){
  return <section className="panel">
    <div className="panel-head"><h2>{title}</h2>{note&&<span>{note}</span>}</div>
    <div className="table-scroll"><table><tbody>
      {rows.map(([label,value])=><tr key={label}><td>{label}</td><td><b>{value}</b></td></tr>)}
    </tbody></table></div>
  </section>;
}

export default function CMOReportsPage(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);try{setData(await api('/cmo/reports'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat laporan...</div>;

  const {pipeline,quotation,sample,spk}=data;
  return <div className="page">
    <div className="page-title">
      <div><h1>Reports</h1><p>Laporan performa komersial. Tidak untuk mengubah data operasional atau keuangan.</p></div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">
      <div className="stat blue"><strong>{pct(quotation.conversion_percent)}</strong><span>Conversion quotation</span></div>
      <div className="stat blue"><strong>{pct(sample.approval_percent)}</strong><span>Sample approval</span></div>
      <div className="stat blue"><strong>{pct(spk.release_percent)}</strong><span>SPK release</span></div>
      <div className="stat green"><strong>{pipeline.active_orders}</strong><span>Order aktif</span></div>
    </div>

    <div className="grid2">
      <Block title="Pipeline & Order" rows={[
        ['Total buyer',pipeline.total_buyers],
        ['Total order',pipeline.total_orders],
        ['Order aktif',pipeline.active_orders],
        ['Order selesai',pipeline.closed_orders],
      ]}/>
      <Block title="Quotation" note="Approve / tolak" rows={[
        ['Total quotation',quotation.total],
        ['Disetujui',quotation.approved],
        ['Ditolak',quotation.rejected],
        ['Nilai disetujui',money(quotation.approved_value)],
        ['Conversion',pct(quotation.conversion_percent)],
      ]}/>
      <Block title="Sample / PPM" rows={[
        ['Total sample',sample.total],
        ['Sudah ada keputusan',sample.decided],
        ['Approval',pct(sample.approval_percent)],
      ]}/>
      <Block title="SPK" note="Release ke COO" rows={[
        ['Total SPK',spk.total],
        ['Released',spk.released],
        ['Release rate',pct(spk.release_percent)],
      ]}/>
    </div>
  </div>;
}