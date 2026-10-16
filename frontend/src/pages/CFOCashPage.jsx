import React,{useCallback,useEffect,useState} from 'react';
import {useOutletContext} from 'react-router-dom';
import {api} from '../api';
import MoneyInput from '../components/MoneyInput';
import {formatRupiah,rupiahNumber} from '../money';
import {formatDate,dateInputValue} from '../control';

/* Kas kecil harian + kas besar. Kas kecil = buku harian + laporan saldo; kas besar otomatis diposting ke jurnal akuntansi. */
const PETTY_CATEGORIES=['ATK','Transport','Konsumsi','Listrik / Air','Perbaikan','Kebersihan','Lainnya'];

export default function CFOCashPage(){
  const role=useOutletContext()?.me?.role,canWrite=role==='CFO_MANAGER';
  const [kind,setKind]=useState('PETTY'),[day,setDay]=useState(()=>dateInputValue(new Date()));
  const [report,setReport]=useState(null),[list,setList]=useState(null),[accounts,setAccounts]=useState([]);
  const [form,setForm]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const month=day.slice(0,8)+'01';

  const load=useCallback(async()=>{
    setErr('');
    try{
      if(kind==='PETTY')setReport(await api('/cfo/cash/daily-report?kind=PETTY&day='+day));
      setList(await api(`/cfo/cash?kind=${kind}&date_from=${kind==='PETTY'?day:month}${kind==='PETTY'?'&date_to='+day:''}`));
    }catch(e){setErr(e.message)}
  },[kind,day,month]);
  useEffect(()=>{load()},[load]);
  useEffect(()=>{
    if(kind!=='BIG'||accounts.length)return;
    (async()=>{
      try{
        let rows=await api('/accounting/accounts?active_only=true');
        if(!rows.length&&canWrite){await api('/accounting/seed-coa',{method:'POST'});rows=await api('/accounting/accounts?active_only=true')}
        setAccounts(rows);
      }catch(e){setErr(e.message)}
    })();
  },[kind,accounts.length,canWrite]);

  function open(direction){setForm({kind,entry_date:day,direction,category:kind==='PETTY'?'ATK':'',description:'',amount:'',cash_account_code:'1-1000',counter_account_code:''})}
  async function save(e){
    e.preventDefault();setBusy(true);setErr('');
    try{
      const body={...form,amount:rupiahNumber(form.amount),category:form.category||null};
      if(kind==='PETTY'){delete body.cash_account_code;delete body.counter_account_code}
      await api('/cfo/cash',{method:'POST',body:JSON.stringify(body)});
      setForm(null);await load();
    }catch(x){setErr(x.message)}finally{setBusy(false)}
  }
  async function remove(row){
    if(!confirm('Hapus catatan kas kecil ini?'))return;
    try{await api('/cfo/cash/'+row.id,{method:'DELETE'});await load()}catch(x){setErr(x.message)}
  }
  const summary=kind==='PETTY'?report:list;

  return <div className="page">
    <div className="page-title"><div><h1>Kas Kecil & Kas Besar</h1><p>Kas kecil dicatat harian dengan saldo berjalan. Kas besar langsung menjadi jurnal di Akuntansi.</p></div>
      {canWrite&&<div className="row-actions"><button className="btn primary" onClick={()=>open('IN')}>+ Kas masuk</button><button className="btn" onClick={()=>open('OUT')}>− Kas keluar</button></div>}</div>
    <div className="tabs" role="tablist">{[['PETTY','Kas Kecil Harian'],['BIG','Kas Besar']].map(([k,l])=><button key={k} role="tab" aria-selected={kind===k} className={kind===k?'on':''} onClick={()=>setKind(k)}>{l}</button>)}</div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {kind==='PETTY'&&<div className="filter-bar"><label className="inline-field">Tanggal <input type="date" value={day} max={dateInputValue(new Date())} onChange={e=>e.target.value&&setDay(e.target.value)}/></label></div>}
    {summary&&<div className="cards cards-4">
      <div className="stat gray"><strong>{formatRupiah(summary.opening_balance)}</strong><span>Saldo awal</span></div>
      <div className="stat green"><strong>{formatRupiah(summary.total_in)}</strong><span>Masuk</span></div>
      <div className="stat red"><strong>{formatRupiah(summary.total_out)}</strong><span>Keluar</span></div>
      <div className="stat blue"><strong>{formatRupiah(summary.closing_balance)}</strong><span>Saldo akhir</span></div>
    </div>}
    {kind==='PETTY'&&report?.out_by_category?.length>0&&<section className="panel"><div className="panel-head"><h2>Pengeluaran per kategori</h2><span>{formatDate(day)}</span></div>
      <div className="chips">{report.out_by_category.map(c=><span key={c.category} className="chip-toggle on">{c.category}: <b>{formatRupiah(c.amount)}</b></span>)}</div></section>}
    <section className="panel flush"><div className="table-scroll"><table>
      <thead><tr><th>Tanggal</th><th>Keterangan</th><th>Kategori{kind==='BIG'?' / Akun':''}</th><th className="num">Masuk</th><th className="num">Keluar</th><th className="num">Saldo</th><th></th></tr></thead>
      <tbody>{(list?.rows||[]).map(r=><tr key={r.id}><td>{formatDate(r.entry_date)}</td><td className="wrap">{r.description}</td>
        <td>{r.category||'-'}{r.kind==='BIG'&&<><br/><small>{r.cash_account_code} ↔ {r.counter_account_code}</small></>}</td>
        <td className="num">{r.direction==='IN'?formatRupiah(r.amount):''}</td><td className="num">{r.direction==='OUT'?formatRupiah(r.amount):''}</td><td className="num"><b>{formatRupiah(r.balance)}</b></td>
        <td>{canWrite&&r.kind==='PETTY'&&<button className="btn sm" onClick={()=>remove(r)}>Hapus</button>}{r.kind==='BIG'&&<small>jurnal #{r.journal_entry_id}</small>}</td></tr>)}
        {list&&!list.rows.length&&<tr><td colSpan={7} className="empty-cell">Belum ada catatan{kind==='PETTY'?' pada tanggal ini':' bulan ini'}.</td></tr>}</tbody></table></div></section>

    {form&&<div className="modal-bg" onClick={()=>setForm(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
      <div className="modal-head"><h2>{form.direction==='IN'?'Kas masuk':'Kas keluar'} — {kind==='PETTY'?'kas kecil':'kas besar'}</h2><button type="button" className="icon-btn" onClick={()=>setForm(null)} aria-label="Tutup">×</button></div>
      <form onSubmit={save}>
        {err&&<div className="notice danger" role="alert">{err}</div>}
        <label>Tanggal<input type="date" required value={form.entry_date} onChange={e=>setForm({...form,entry_date:e.target.value})}/></label>
        <label>Jumlah<MoneyInput required value={form.amount} onChange={v=>setForm({...form,amount:v})}/></label>
        {kind==='PETTY'?<label>Kategori<select value={form.category} onChange={e=>setForm({...form,category:e.target.value})}>{PETTY_CATEGORIES.map(c=><option key={c}>{c}</option>)}</select></label>
          :<><label>Masuk/keluar lewat<select value={form.cash_account_code} onChange={e=>setForm({...form,cash_account_code:e.target.value})}><option value="1-1000">Kas</option><option value="1-1100">Bank</option></select></label>
            <label>Akun lawan *<select required value={form.counter_account_code} onChange={e=>setForm({...form,counter_account_code:e.target.value})}><option value="">Pilih akun…</option>{accounts.filter(a=>a.code!==form.cash_account_code).map(a=><option key={a.id} value={a.code}>{a.code} — {a.name}</option>)}</select><small>{form.direction==='IN'?'Contoh: Pendapatan Penjualan, Piutang, Modal':'Contoh: Beban Sewa, Utang Usaha, Beban Listrik'}</small></label>
            <label>Kategori<input value={form.category} onChange={e=>setForm({...form,category:e.target.value})} placeholder="Opsional"/></label></>}
        <label>Keterangan *<textarea required minLength={2} rows={2} value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <div className="modal-foot"><button type="button" className="btn" onClick={()=>setForm(null)}>Batal</button><button className="btn primary" disabled={busy}>{busy?'Menyimpan…':'Simpan'}</button></div>
      </form></div></div>}
  </div>;
}
