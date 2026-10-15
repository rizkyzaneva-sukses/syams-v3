import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';

const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:0});
const num=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2});
const TODAY=new Date().toISOString().slice(0,10);
const YEAR_START=TODAY.slice(0,4)+'-01-01';
const WRITE_ROLES=['CFO_MANAGER','FINANCE_SUPPORT'];
const TYPE_LABEL={ASSET:'Aset',LIABILITY:'Liabilitas',EQUITY:'Ekuitas',REVENUE:'Pendapatan',EXPENSE:'Beban'};

export default function AccountingPage(){
 const role=useRole();
 const canWrite=WRITE_ROLES.includes(role);
 const [tab,setTab]=useState('neraca');
 const [from,setFrom]=useState(YEAR_START),[to,setTo]=useState(TODAY);
 const [err,setErr]=useState(''),[busy,setBusy]=useState(false);
 const [data,setData]=useState({});

 function load(key,path){
   return api(path).then(r=>setData(d=>({...d,[key]:r}))).catch(e=>setErr(e.message));
 }
 useEffect(()=>{
   setErr('');
   if(tab==='neraca') load('bs','/accounting/balance-sheet?as_of='+to);
   if(tab==='laba') load('is',`/accounting/income-statement?date_from=${from}&date_to=${to}`);
   if(tab==='tb') load('tb','/accounting/trial-balance?as_of='+to);
   if(tab==='kas') load('cf',`/accounting/cash-flow?date_from=${from}&date_to=${to}`);
   if(tab==='jurnal') load('je','/accounting/journal-entries');
   if(tab==='bb') load('acc','/accounting/accounts');
   if(tab==='aset'){load('assets','/accounting/assets');load('dep','/accounting/depreciation')}
   if(tab==='budget'){load('bv','/accounting/budgets?period='+to.slice(0,4));load('acc','/accounting/accounts')}
 },[tab,from,to]);

 async function action(fn,msg){
   setBusy(true);setErr('');
   try{await fn();load(msg.key,msg.path)}catch(e){setErr(e.message)}finally{setBusy(false)}
 }
 const seedCOA=()=>action(()=>api('/accounting/seed-coa',{method:'POST'}),{key:'acc',path:'/accounting/accounts'});
 const syncTx=()=>action(()=>api('/accounting/sync-transactions',{method:'POST'}),{key:'je',path:'/accounting/journal-entries'});
 const runDep=()=>action(()=>api('/accounting/depreciation/run',{method:'POST',body:JSON.stringify({period:to.slice(0,7)})}),{key:'dep',path:'/accounting/depreciation'});

 const TABS=[['neraca','Neraca'],['laba','Laba Rugi'],['tb','Trial Balance'],['kas','Arus Kas'],['jurnal','Jurnal'],['bb','Buku Besar'],['aset','Aset & Penyusutan'],['budget','Anggaran']];

 return <div className="page">
  <div className="page-title">
    <div><h1>Akuntansi</h1><p>Double-entry: jurnal berpasangan, buku besar, dan laporan keuangan dari posting tervalidasi.</p></div>
    {canWrite&&<div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
      <button className="btn" onClick={seedCOA} disabled={busy}>Isi COA Standar</button>
      <button className="btn" onClick={syncTx} disabled={busy}>Posting Invoice/Payment</button>
    </div>}
  </div>
  {err&&<div className="notice danger" role="alert">{err}</div>}

  <div className="filter-bar">
    <div className="filter-pills" style={{flexWrap:'wrap'}}>
      {TABS.map(([k,l])=><button key={k} className={'pill'+(tab===k?' active open':'')} onClick={()=>setTab(k)}>{l}</button>)}
    </div>
    {['laba','kas'].includes(tab)&&<>
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Dari<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Sampai<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
    </>}
    {['neraca','tb'].includes(tab)&&<label style={{flexDirection:'row',alignItems:'center',gap:6}}>Per<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>}
    {tab==='aset'&&canWrite&&<button className="btn primary" onClick={runDep} disabled={busy}>Jalankan Penyusutan {to.slice(0,7)}</button>}
  </div>

  {tab==='neraca'&&<NeracaPanel d={data.bs}/>}
  {tab==='laba'&&<LabaRugiPanel d={data.is}/>}
  {tab==='tb'&&<TrialBalancePanel d={data.tb}/>}
  {tab==='kas'&&<ArusKasPanel d={data.cf}/>}
  {tab==='jurnal'&&<JurnalPanel rows={data.je} accounts={data.acc} canWrite={canWrite} onChanged={()=>load('je','/accounting/journal-entries')}/>}
  {tab==='bb'&&<BukuBesarPanel accounts={data.acc}/>}
  {tab==='aset'&&<AsetPanel assets={data.assets} dep={data.dep} accounts={data.acc} canWrite={canWrite} onCreated={()=>load('assets','/accounting/assets')}/>}
  {tab==='budget'&&<BudgetPanel rows={data.bv} accounts={data.acc} canWrite={canWrite} period={to.slice(0,4)} onCreated={()=>load('bv','/accounting/budgets?period='+to.slice(0,4))}/>}
 </div>;
}

const Loading=({d})=>!d?<p>Memuat...</p>:null;

function NeracaPanel({d}){
  if(!d) return <p>Memuat...</p>;
  const Row=({r})=><tr><td>{r.code}</td><td>{r.name}</td><td style={{textAlign:'right'}}>{money(r.balance)}</td></tr>;
  const Section=({title,rows,total,negative})=>rows.length?<section className="panel">
    <h2>{title}</h2>
    <div className="table-scroll"><table><thead><tr><th>Kode</th><th>Akun</th><th style={{textAlign:'right'}}>Saldo</th></tr></thead>
    <tbody>{rows.map(r=><Row key={r.code} r={r}/>)}</tbody>
    <tfoot><tr><th colSpan={2}>Total {title}</th><th style={{textAlign:'right'}}>{money(total)}</th></tr></tfoot></table></div>
  </section>:null;
  return <>
    <div className="cards">
      <div className="stat green"><span>Total Aset</span><strong>{money(d.total_assets)}</strong></div>
      <div className="stat amber"><span>Total Liabilitas</span><strong>{money(d.total_liabilities)}</strong></div>
      <div className="stat blue"><span>Total Ekuitas</span><strong>{money(d.total_equity)}</strong></div>
      <div className={'stat '+(d.balanced?'green':'red')}><span>Aset = Liab + Ekuitas</span><strong>{d.balanced?'SEIMBANG':'TIDAK SEIMBANG'}</strong></div>
    </div>
    <Section title="Aset" rows={d.assets} total={d.total_assets}/>
    <Section title="Liabilitas" rows={d.liabilities} total={d.total_liabilities}/>
    <Section title="Ekuitas" rows={d.equity} total={d.total_equity}/>
    <section className="panel"><h2>Laba Periode Berjalan (belum ditutup)</h2>
      <div className="table-scroll"><table><tbody><tr><td>Laba/rugi berjalan</td><td style={{textAlign:'right'}}>{money(d.current_earnings)}</td></tr></tbody></table></div>
    </section>
  </>;
}

function LabaRugiPanel({d}){
  if(!d) return <p>Memuat...</p>;
  const R=({r})=><tr><td>{r.code}</td><td>{r.name}</td><td style={{textAlign:'right'}}>{money(r.amount)}</td></tr>;
  return <>
    <div className="cards">
      <div className="stat green"><span>Pendapatan</span><strong>{money(d.total_revenue)}</strong></div>
      <div className="stat red"><span>Beban</span><strong>{money(d.total_expense)}</strong></div>
      <div className={'stat '+(d.net_income>=0?'green':'red')}><span>Laba Bersih</span><strong>{money(d.net_income)}</strong></div>
    </div>
    <section className="panel"><h2>Pendapatan</h2>
      {d.revenue.length?<div className="table-scroll"><table><thead><tr><th>Kode</th><th>Akun</th><th style={{textAlign:'right'}}>Jumlah</th></tr></thead><tbody>{d.revenue.map(r=><R key={r.code} r={r}/>)}</tbody>
      <tfoot><tr><th colSpan={2}>Total Pendapatan</th><th style={{textAlign:'right'}}>{money(d.total_revenue)}</th></tr></tfoot></table></div>:<div className="empty">Belum ada pendapatan pada periode ini.</div>}
    </section>
    <section className="panel"><h2>Beban</h2>
      {d.expense.length?<div className="table-scroll"><table><thead><tr><th>Kode</th><th>Akun</th><th style={{textAlign:'right'}}>Jumlah</th></tr></thead><tbody>{d.expense.map(r=><R key={r.code} r={r}/>)}</tbody>
      <tfoot><tr><th colSpan={2}>Total Beban</th><th style={{textAlign:'right'}}>{money(d.total_expense)}</th></tr></tfoot></table></div>:<div className="empty">Belum ada beban pada periode ini.</div>}
    </section>
    <section className="panel"><h2>Laba Bersih</h2>
      <div className="table-scroll"><table><tbody><tr><td><b>Laba (rugi) bersih periode {d.date_from} s.d. {d.date_to}</b></td><td style={{textAlign:'right'}}><b>{money(d.net_income)}</b></td></tr></tbody></table></div>
    </section>
  </>;
}

function TrialBalancePanel({d}){
  if(!d) return <p>Memuat...</p>;
  return <section className="panel">
    <div className="panel-head"><h2>Trial Balance per {d.as_of}</h2>
      <span className={'badge '+(d.balanced?'green':'red')}>{d.balanced?'BALANCE':'TIDAK BALANCE'}</span></div>
    <div className="table-scroll"><table>
      <thead><tr><th>Kode</th><th>Akun</th><th>Tipe</th><th style={{textAlign:'right'}}>Debit</th><th style={{textAlign:'right'}}>Kredit</th></tr></thead>
      <tbody>{d.rows.filter(r=>r.debit||r.credit).map(r=><tr key={r.code}><td>{r.code}</td><td>{r.name}</td><td><span className="badge gray">{TYPE_LABEL[r.account_type]||r.account_type}</span></td><td style={{textAlign:'right'}}>{r.debit?num(r.debit):'—'}</td><td style={{textAlign:'right'}}>{r.credit?num(r.credit):'—'}</td></tr>)}
      {!d.rows.some(r=>r.debit||r.credit)&&<tr><td colSpan={5}>Belum ada jurnal terposting.</td></tr>}</tbody>
      <tfoot><tr><th colSpan={3}>Total</th><th style={{textAlign:'right'}}>{num(d.total_debit)}</th><th style={{textAlign:'right'}}>{num(d.total_credit)}</th></tr></tfoot>
    </table></div>
  </section>;
}

function ArusKasPanel({d}){
  if(!d) return <p>Memuat...</p>;
  return <>
    <div className="cards">
      <div className="stat blue"><span>Operasional</span><strong>{money(d.operating)}</strong></div>
      <div className="stat blue"><span>Investasi</span><strong>{money(d.investing)}</strong></div>
      <div className="stat blue"><span>Pendanaan</span><strong>{money(d.financing)}</strong></div>
      <div className={'stat '+(d.net_change>=0?'green':'red')}><span>Perubahan Kas Bersih</span><strong>{money(d.net_change)}</strong></div>
    </div>
    <section className="panel"><h2>Rincian Arus Kas {d.date_from} s.d. {d.date_to}</h2>
      <div className="table-scroll"><table><tbody>
        <tr><td>Aktivitas Operasional</td><td style={{textAlign:'right'}}>{money(d.operating)}</td></tr>
        <tr><td>Aktivitas Investasi</td><td style={{textAlign:'right'}}>{money(d.investing)}</td></tr>
        <tr><td>Aktivitas Pendanaan</td><td style={{textAlign:'right'}}>{money(d.financing)}</td></tr>
        {!!d.unclassified&&<tr><td>Belum terklasifikasi</td><td style={{textAlign:'right'}}>{money(d.unclassified)}</td></tr>}
      </tbody>
      <tfoot><tr><th>Perubahan Kas Bersih</th><th style={{textAlign:'right'}}>{money(d.net_change)}</th></tr></tfoot></table></div>
    </section>
  </>;
}

function JurnalPanel({rows,accounts,canWrite,onChanged}){
  const [form,setForm]=useState(null);
  const amap=useMemo(()=>Object.fromEntries((accounts||[]).map(a=>[a.code,a])),[accounts]);
  const line=()=>({account_code:'',debit:'',credit:'',description:''});
  const totalDebit=(form?.lines||[]).reduce((s,l)=>s+Number(l.debit||0),0);
  const totalCredit=(form?.lines||[]).reduce((s,l)=>s+Number(l.credit||0),0);
  const balanced=Math.abs(totalDebit-totalCredit)<0.005&&totalDebit>0;
  async function save(){
    await api('/accounting/journal-entries',{method:'POST',body:JSON.stringify({
      entry_date:form.entry_date,description:form.description,
      lines:form.lines.map(l=>({account_code:l.account_code,debit:Number(l.debit||0),credit:Number(l.credit||0),description:l.description||null}))})});
    setForm(null);onChanged();
  }
  async function doAction(entryId,path,body){
    await api(`/accounting/journal-entries/${entryId}/${path}`,{method:'POST',body:body?JSON.stringify(body):undefined});
    onChanged();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({entry_date:TODAY,description:'',lines:[line(),line()]})} style={{marginBottom:14}}>+ Jurnal Manual</button>}
    {form&&<section className="panel">
      <div className="panel-head"><h2>Jurnal Baru</h2>
        <span className={'badge '+(balanced?'green':'amber')}>{balanced?'Balance':'Belum balance'} · D {num(totalDebit)} / K {num(totalCredit)}</span></div>
      <div className="form-grid">
        <label>Tanggal<input type="date" value={form.entry_date} onChange={e=>setForm({...form,entry_date:e.target.value})}/></label>
        <label>Keterangan<input value={form.description} onChange={e=>setForm({...form,description:e.target.value})} placeholder="mis. Setoran modal"/></label>
      </div>
      <div className="table-scroll"><table><thead><tr><th>Akun</th><th>Debit</th><th>Kredit</th><th>Keterangan</th><th/></tr></thead>
        <tbody>{form.lines.map((l,i)=><tr key={i}>
          <td><select value={l.account_code} onChange={e=>upd(i,{account_code:e.target.value})}>
            <option value="">— pilih akun —</option>
            {(accounts||[]).map(a=><option key={a.code} value={a.code}>{a.code} · {a.name}</option>)}</select></td>
          <td><input type="number" min="0" value={l.debit} onChange={e=>upd(i,{debit:e.target.value,credit:''})}/></td>
          <td><input type="number" min="0" value={l.credit} onChange={e=>upd(i,{credit:e.target.value,debit:''})}/></td>
          <td><input value={l.description} onChange={e=>upd(i,{description:e.target.value})}/></td>
          <td>{form.lines.length>2&&<button className="icon-btn danger" onClick={()=>setForm({...form,lines:form.lines.filter((_,j)=>j!==i)})}>×</button>}</td>
        </tr>)}</tbody></table></div>
      <div className="form-actions">
        <button className="btn" onClick={()=>setForm({...form,lines:[...form.lines,line()]})}>+ Baris</button>
        <button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" disabled={!balanced} onClick={()=>save().catch(e=>alert(e.message))}>Simpan (Draft)</button>
      </div>
    </section>}
    <section className="panel"><h2>Daftar Jurnal</h2>
      {!rows?<p>Memuat...</p>:<div className="table-scroll"><table>
        <thead><tr><th>No</th><th>Tanggal</th><th>Keterangan</th><th>Sumber</th><th style={{textAlign:'right'}}>Debit</th><th>Status</th><th>Aksi</th></tr></thead>
        <tbody>{rows.map(e=><React.Fragment key={e.id}>
          <tr><td>{e.entry_no}</td><td>{e.entry_date}</td><td>{e.description||'—'}</td>
            <td><span className="badge gray">{e.entry_source}</span></td>
            <td style={{textAlign:'right'}}>{num(e.total_debit)}</td>
            <td><span className={'badge '+(e.status==='POSTED'?'green':e.status==='REVERSED'?'red':'amber')}>{e.status}</span>{e.reversed_by_id&&e.status==='POSTED'&&<span className="badge red" style={{marginLeft:4}}>DIBALIK</span>}</td>
            <td>{canWrite&&e.status==='DRAFT'&&<button className="btn sm" onClick={()=>doAction(e.id,'post').catch(x=>alert(x.message))}>Posting</button>}
              {canWrite&&e.status==='POSTED'&&!e.reversed_by_id&&<button className="btn sm" onClick={()=>{const r=prompt('Alasan reversal:');if(r)doAction(e.id,'reverse',{reason:r}).catch(x=>alert(x.message))}}>Reversal</button>}</td></tr>
          {e.lines.map((l,i)=><tr key={e.id+'-'+i} style={{background:'#fbfcfe'}}>
            <td/><td/><td style={{paddingLeft:26,color:'#64748b'}}>{l.account_code} · {l.account_name}</td><td/>
            <td style={{textAlign:'right',color:'#64748b'}}>D {l.debit?num(l.debit):'—'} / K {l.credit?num(l.credit):'—'}</td><td/><td/></tr>)}
        </React.Fragment>)}
        {!rows.length&&<tr><td colSpan={7}>Belum ada jurnal. Klik "Isi COA Standar" lalu "Posting Invoice/Payment".</td></tr>}</tbody>
      </table></div>}
    </section>
  </>;
  function upd(i,patch){setForm(f=>({...f,lines:f.lines.map((l,j)=>j===i?{...l,...patch}:l)}))}
}

function BukuBesarPanel({accounts}){
  const [accId,setAccId]=useState('');
  const [gl,setGl]=useState(null),[err,setErr]=useState('');
  useEffect(()=>{if(!accId)return;setErr('');api(`/accounting/general-ledger/${accId}`).then(setGl).catch(e=>setErr(e.message))},[accId]);
  return <>
    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Akun
        <select value={accId} onChange={e=>setAccId(e.target.value)}>
          <option value="">— pilih akun —</option>
          {(accounts||[]).map(a=><option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
        </select></label>
    </div>
    {err&&<div className="notice danger">{err}</div>}
    {!accId&&<div className="empty">Pilih akun untuk melihat buku besar.</div>}
    {gl&&<section className="panel">
      <div className="panel-head"><h2>{gl.account.code} · {gl.account.name}</h2>
        <span className="badge blue">Saldo Akhir {money(gl.closing_balance)}</span></div>
      <div className="table-scroll"><table>
        <thead><tr><th>Tanggal</th><th>No Jurnal</th><th>Keterangan</th><th style={{textAlign:'right'}}>Debit</th><th style={{textAlign:'right'}}>Kredit</th><th style={{textAlign:'right'}}>Saldo</th></tr></thead>
        <tbody>{gl.rows.map((r,i)=><tr key={i}><td>{r.date}</td><td>{r.entry_no}</td><td>{r.description||'—'}</td>
          <td style={{textAlign:'right'}}>{r.debit?num(r.debit):'—'}</td><td style={{textAlign:'right'}}>{r.credit?num(r.credit):'—'}</td>
          <td style={{textAlign:'right'}}>{num(r.running_balance)}</td></tr>)}
        {!gl.rows.length&&<tr><td colSpan={6}>Belum ada mutasi pada akun ini.</td></tr>}</tbody></table></div>
    </section>}
  </>;
}

function AsetPanel({assets,dep,canWrite,onCreated}){
  const [form,setForm]=useState(null);
  async function save(){
    await api('/accounting/assets',{method:'POST',body:JSON.stringify({
      asset_code:form.asset_code,name:form.name,category:form.category||null,
      acquisition_date:form.acquisition_date,acquisition_cost:Number(form.acquisition_cost),
      salvage_value:Number(form.salvage_value||0),useful_life_months:Number(form.useful_life_months)})});
    setForm(null);onCreated();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({asset_code:'',name:'',category:'',acquisition_date:TODAY,acquisition_cost:'',salvage_value:'0',useful_life_months:48})} style={{marginBottom:14}}>+ Aset Tetap</button>}
    {form&&<section className="panel"><h2>Aset Baru</h2>
      <div className="form-grid">
        <label>Kode<input value={form.asset_code} onChange={e=>setForm({...form,asset_code:e.target.value})}/></label>
        <label>Nama<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
        <label>Kategori<input value={form.category} onChange={e=>setForm({...form,category:e.target.value})}/></label>
        <label>Tanggal Perolehan<input type="date" value={form.acquisition_date} onChange={e=>setForm({...form,acquisition_date:e.target.value})}/></label>
        <label>Harga Perolehan<input type="number" value={form.acquisition_cost} onChange={e=>setForm({...form,acquisition_cost:e.target.value})}/></label>
        <label>Nilai Residu<input type="number" value={form.salvage_value} onChange={e=>setForm({...form,salvage_value:e.target.value})}/></label>
        <label>Umur (bulan)<input type="number" value={form.useful_life_months} onChange={e=>setForm({...form,useful_life_months:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan</button></div>
    </section>}
    <section className="panel"><h2>Daftar Aset Tetap</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Nama</th><th>Kategori</th><th style={{textAlign:'right'}}>Perolehan</th><th style={{textAlign:'right'}}>Akum. Penyusutan</th><th style={{textAlign:'right'}}>Nilai Buku</th><th style={{textAlign:'right'}}>Susut/Bulan</th><th>Status</th></tr></thead>
        <tbody>{(assets||[]).map(a=><tr key={a.id}><td>{a.asset_code}</td><td>{a.name}</td><td>{a.category||'—'}</td>
          <td style={{textAlign:'right'}}>{money(a.acquisition_cost)}</td><td style={{textAlign:'right'}}>{money(a.accumulated_depreciation)}</td>
          <td style={{textAlign:'right'}}>{money(a.book_value)}</td><td style={{textAlign:'right'}}>{money(a.monthly_depreciation)}</td>
          <td><span className="badge gray">{a.status}</span></td></tr>)}
        {!assets?.length&&<tr><td colSpan={8}>Belum ada aset tetap.</td></tr>}</tbody></table></div>
    </section>
    <section className="panel"><h2>Riwayat Penyusutan</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Periode</th><th>Aset</th><th style={{textAlign:'right'}}>Beban Susut</th><th style={{textAlign:'right'}}>Akumulasi</th><th>Jurnal</th></tr></thead>
        <tbody>{(dep||[]).map(x=><tr key={x.id}><td>{x.period}</td><td>{x.asset_code} · {x.asset_name}</td>
          <td style={{textAlign:'right'}}>{money(x.amount)}</td><td style={{textAlign:'right'}}>{money(x.accumulated_after)}</td>
          <td>{x.journal_entry_id?<span className="badge green">posted</span>:'—'}</td></tr>)}
        {!dep?.length&&<tr><td colSpan={5}>Belum ada penyusutan dijalankan.</td></tr>}</tbody></table></div>
    </section>
  </>;
}

function BudgetPanel({rows,accounts,canWrite,period,onCreated}){
  const [form,setForm]=useState(null);
  async function save(){
    await api('/accounting/budgets',{method:'POST',body:JSON.stringify({period:form.period,account_id:Number(form.account_id),amount:Number(form.amount),notes:form.notes||null})});
    setForm(null);onCreated();
  }
  return <>
    {canWrite&&!form&&<button className="btn primary" onClick={()=>setForm({period:period,account_id:'',amount:'',notes:''})} style={{marginBottom:14}}>+ Set Anggaran</button>}
    {form&&<section className="panel"><h2>Anggaran Baru</h2>
      <div className="form-grid">
        <label>Periode (YYYY)<input value={form.period} onChange={e=>setForm({...form,period:e.target.value})}/></label>
        <label>Akun<select value={form.account_id} onChange={e=>setForm({...form,account_id:e.target.value})}>
          <option value="">— pilih —</option>{(accounts||[]).filter(a=>['REVENUE','EXPENSE'].includes(a.account_type)).map(a=><option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select></label>
        <label>Anggaran<input type="number" value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})}/></label>
        <label>Catatan<input value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" onClick={()=>save().catch(e=>alert(e.message))}>Simpan</button></div>
    </section>}
    <section className="panel"><h2>Anggaran {period}</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Akun</th><th style={{textAlign:'right'}}>Anggaran</th><th style={{textAlign:'right'}}>Realisasi</th></tr></thead>
        <tbody>{(rows||[]).map(b=><tr key={b.id}><td>{b.account_code}</td><td>{b.account_name}</td><td style={{textAlign:'right'}}>{money(b.amount)}</td><td style={{textAlign:'right'}}>—</td></tr>)}
        {!rows?.length&&<tr><td colSpan={4}>Belum ada anggaran untuk periode ini.</td></tr>}</tbody></table></div>
    </section>
  </>;
}
