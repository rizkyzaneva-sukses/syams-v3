import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {useRole} from '../components/Access';

const money=n=>'Rp '+Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:0});
const num=n=>Number(n||0).toLocaleString('id-ID',{maximumFractionDigits:2});
const TODAY=new Date().toISOString().slice(0,10);
const WRITE_ROLES=['CFO_MANAGER','FINANCE_SUPPORT'];
const STATUS_TONE={UNRECONCILED:'amber',MATCHED:'blue',RECONCILED:'green',IGNORED:'gray'};
const STATUS_LABEL={UNRECONCILED:'Belum',MATCHED:'Dugaan Cocok',RECONCILED:'Cocok',IGNORED:'Diabaikan'};

export default function BankingPage(){
 const role=useRole();
 const canWrite=WRITE_ROLES.includes(role);
 const [tab,setTab]=useState('rekon');
 const [err,setErr]=useState('');
 return <div className="page">
  <div className="page-title">
    <div><h1>Bank Reconciliation & Treasury</h1>
      <p>Rekonsiliasi mutasi bank terhadap jurnal, dan posisi kas/bank dari jurnal terposting.</p></div>
  </div>
  {err&&<div className="notice danger" role="alert">{err}</div>}
  <div className="filter-bar">
    <div className="filter-pills">
      <button className={'pill'+(tab==='rekon'?' active open':'')} onClick={()=>setTab('rekon')}>Rekonsiliasi Bank</button>
      <button className={'pill'+(tab==='treasury'?' active open':'')} onClick={()=>setTab('treasury')}>Treasury</button>
    </div>
  </div>
  {tab==='rekon'?<RekonPanel canWrite={canWrite} onError={setErr}/>:<TreasuryPanel onError={setErr}/>}
 </div>;
}

/* ── Tab Rekonsiliasi Bank ──────────────────────────────────────────────── */
function RekonPanel({canWrite,onError}){
  const [accounts,setAccounts]=useState([]);
  const [accId,setAccId]=useState('');
  const [statusFilter,setStatusFilter]=useState('ALL');
  const [txns,setTxns]=useState([]);
  const [summary,setSummary]=useState(null);
  const [form,setForm]=useState(null);
  const [importForm,setImportForm]=useState(null);
  const [matchFor,setMatchFor]=useState(null);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);

  async function loadAccounts(){
    try{const a=await api('/banking/accounts');setAccounts(a);if(!accId&&a.length)setAccId(String(a[0].id));onError('')}
    catch(e){onError(e.message)}finally{setLoading(false)}
  }
  async function loadTxns(id){
    if(!id)return;
    try{
      const q=statusFilter==='ALL'?'':('?status='+statusFilter);
      const [t,s]=await Promise.all([api(`/banking/accounts/${id}/transactions${q}`),api(`/banking/accounts/${id}/reconciliation-summary`)]);
      setTxns(t);setSummary(s);onError('');
    }catch(e){onError(e.message)}
  }
  useEffect(()=>{loadAccounts()},[]); // eslint-disable-line
  useEffect(()=>{loadTxns(accId)},[accId,statusFilter]); // eslint-disable-line

  async function act(fn){setBusy(true);onError('');try{await fn();await loadTxns(accId)}catch(e){onError(e.message)}finally{setBusy(false)}}

  const saveAccount=()=>act(async()=>{
    const payload={code:form.code,bank_name:form.bank_name,account_no:form.account_no||null,
      account_name:form.account_name||null,currency:form.currency||'IDR',
      opening_balance:Number(form.opening_balance||0),
      gl_account_id:form.gl_account_id?Number(form.gl_account_id):null};
    const created=await api('/banking/accounts',{method:'POST',body:JSON.stringify(payload)});
    setForm(null);await loadAccounts();setAccId(String(created.id));
  });

  const saveImport=()=>act(async()=>{
    const lines=importForm.rows.filter(r=>(r.txn_date)&&(Number(r.debit||0)>0||Number(r.credit||0)>0))
      .map(r=>({txn_date:r.txn_date,description:r.description||null,
        debit:Number(r.debit||0),credit:Number(r.credit||0),
        reference:r.reference||null,balance_after:r.balance_after===''||r.balance_after==null?null:Number(r.balance_after)}));
    await api(`/banking/accounts/${accId}/transactions`,{method:'POST',
      body:JSON.stringify({transactions:lines,import_batch:importForm.import_batch||null})});
    setImportForm(null);
  });

  const reconcile=(txnId,target)=>act(async()=>{
    await api(`/banking/transactions/${txnId}/reconcile`,{method:'POST',body:JSON.stringify(target)});
    setMatchFor(null);
  });
  const unreconcile=txnId=>act(()=>api(`/banking/transactions/${txnId}/unreconcile`,{method:'POST'}));
  const ignore=txnId=>act(()=>api(`/banking/transactions/${txnId}/ignore`,{method:'POST'}));

  const acc=accounts.find(a=>String(a.id)===accId);
  return <>
    <div className="filter-bar">
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Akun Bank
        <select value={accId} onChange={e=>setAccId(e.target.value)}>
          <option value="">— pilih akun —</option>
          {accounts.map(a=><option key={a.id} value={a.id}>{a.code} · {a.bank_name} {a.account_no?('· '+a.account_no):''}</option>)}
        </select></label>
      <label style={{flexDirection:'row',alignItems:'center',gap:6}}>Status
        <select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}>
          <option value="ALL">Semua</option>
          <option value="UNRECONCILED">Belum</option>
          <option value="MATCHED">Dugaan Cocok</option>
          <option value="RECONCILED">Cocok</option>
          <option value="IGNORED">Diabaikan</option>
        </select></label>
      {canWrite&&<>
        <button className="btn" onClick={()=>setForm({code:'',bank_name:'',account_no:'',account_name:'',currency:'IDR',opening_balance:'0',gl_account_id:''})}>+ Akun Bank</button>
        <button className="btn primary" disabled={!accId} onClick={()=>setImportForm({import_batch:'',rows:[{txn_date:TODAY,description:'',debit:'',credit:'',reference:'',balance_after:''}]})}>Import Mutasi</button>
      </>}
    </div>

    {form&&<section className="panel"><h2>Akun Bank Baru</h2>
      <div className="form-grid">
        <label>Kode<input value={form.code} onChange={e=>setForm({...form,code:e.target.value})}/></label>
        <label>Bank<input value={form.bank_name} onChange={e=>setForm({...form,bank_name:e.target.value})}/></label>
        <label>No. Rekening<input value={form.account_no} onChange={e=>setForm({...form,account_no:e.target.value})}/></label>
        <label>Nama Pemilik<input value={form.account_name} onChange={e=>setForm({...form,account_name:e.target.value})}/></label>
        <label>Mata Uang<input value={form.currency} onChange={e=>setForm({...form,currency:e.target.value})}/></label>
        <label>Saldo Awal<input type="number" value={form.opening_balance} onChange={e=>setForm({...form,opening_balance:e.target.value})}/></label>
        <label>Akun COA (id, opsional)<input type="number" value={form.gl_account_id} onChange={e=>setForm({...form,gl_account_id:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="btn" onClick={()=>setForm(null)}>Batal</button>
        <button className="btn primary" disabled={busy||!form.code||!form.bank_name} onClick={saveAccount}>Simpan</button></div>
    </section>}

    {importForm&&<section className="panel"><h2>Import Mutasi (JSON list)</h2>
      <p style={{color:'#64748b'}}>Debit = uang masuk, Credit = uang keluar. Baris kosong diabaikan.</p>
      <div className="form-grid"><label>Batch (opsional)<input value={importForm.import_batch} onChange={e=>setImportForm({...importForm,import_batch:e.target.value})} placeholder="mis. BCA-NOV-2026"/></label></div>
      <div className="table-scroll"><table><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Debit (masuk)</th><th>Credit (keluar)</th><th>Referensi</th><th>Saldo</th><th/></tr></thead>
        <tbody>{importForm.rows.map((r,i)=><tr key={i}>
          <td><input type="date" value={r.txn_date} onChange={e=>updRow(setImportForm,i,{txn_date:e.target.value})}/></td>
          <td><input value={r.description} onChange={e=>updRow(setImportForm,i,{description:e.target.value})}/></td>
          <td><input type="number" min="0" value={r.debit} onChange={e=>updRow(setImportForm,i,{debit:e.target.value,credit:''})}/></td>
          <td><input type="number" min="0" value={r.credit} onChange={e=>updRow(setImportForm,i,{credit:e.target.value,debit:''})}/></td>
          <td><input value={r.reference} onChange={e=>updRow(setImportForm,i,{reference:e.target.value})}/></td>
          <td><input type="number" value={r.balance_after} onChange={e=>updRow(setImportForm,i,{balance_after:e.target.value})}/></td>
          <td>{importForm.rows.length>1&&<button className="icon-btn danger" onClick={()=>setImportForm(f=>({...f,rows:f.rows.filter((_,j)=>j!==i)}))}>×</button>}</td></tr>)}</tbody></table></div>
      <div className="form-actions">
        <button className="btn" onClick={()=>setImportForm(f=>({...f,rows:[...f.rows,{txn_date:TODAY,description:'',debit:'',credit:'',reference:'',balance_after:''}]}))}>+ Baris</button>
        <button className="btn" onClick={()=>setImportForm(null)}>Batal</button>
        <button className="btn primary" disabled={busy} onClick={saveImport}>Import</button></div>
    </section>}

    {summary&&<div className="cards">
      <div className="stat green"><span>Cocok</span><strong>{summary.counts.RECONCILED||0}</strong></div>
      <div className="stat amber"><span>Belum</span><strong>{summary.counts.UNRECONCILED||0}</strong></div>
      <div className="stat blue"><span>Dugaan Cocok</span><strong>{summary.counts.MATCHED||0}</strong></div>
      <div className="stat gray"><span>Diabaikan</span><strong>{summary.counts.IGNORED||0}</strong></div>
      <div className={'stat '+(summary.reconciled?'green':(summary.difference==null?'gray':'red'))}><span>Selisih Saldo Bank vs Jurnal</span>
        <strong>{summary.difference==null?'—':money(summary.difference)}</strong>
        <small>Statement {summary.statement_balance!=null?money(summary.statement_balance):'—'} · Jurnal {summary.journal_balance!=null?money(summary.journal_balance):'—'}</small></div>
    </div>}

    {!accId?<div className="empty">Pilih akun bank untuk melihat mutasi.</div>
      :loading?<p>Memuat...</p>
      :<section className="panel"><h2>Mutasi Bank {acc?('· '+acc.code):''}</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Tanggal</th><th>Keterangan</th><th style={{textAlign:'right'}}>Masuk</th><th style={{textAlign:'right'}}>Keluar</th><th>Referensi</th><th>Status</th><th>Aksi</th></tr></thead>
        <tbody>{txns.map(t=><React.Fragment key={t.id}>
          <tr><td>{t.txn_date}</td><td>{t.description||'—'}</td>
            <td style={{textAlign:'right'}}>{t.debit?num(t.debit):'—'}</td>
            <td style={{textAlign:'right'}}>{t.credit?num(t.credit):'—'}</td>
            <td>{t.reference||'—'}</td>
            <td><span className={'badge '+(STATUS_TONE[t.reconciliation_status]||'gray')}>{STATUS_LABEL[t.reconciliation_status]||t.reconciliation_status}</span>
              {t.matched_journal_line_id&&<small> JL#{t.matched_journal_line_id}</small>}
              {t.matched_payment_id&&<small> PAY#{t.matched_payment_id}</small>}</td>
            <td>{canWrite&&t.reconciliation_status!=='RECONCILED'&&t.reconciliation_status!=='IGNORED'&&<button className="btn sm" onClick={()=>setMatchFor(t)}>Reconcile</button>}
              {canWrite&&t.reconciliation_status==='RECONCILED'&&<button className="btn sm" onClick={()=>unreconcile(t.id).catch(()=>{})}>Unreconcile</button>}
              {canWrite&&!['RECONCILED','IGNORED'].includes(t.reconciliation_status)&&<button className="btn sm" onClick={()=>ignore(t.id).catch(()=>{})}>Ignore</button>}</td></tr>
          {matchFor?.id===t.id&&<tr><td colSpan={7} style={{background:'#f8fafc'}}>
            <MatchPanel txn={t} accountId={accId} onPick={target=>reconcile(t.id,target)} onClose={()=>setMatchFor(null)} busy={busy}/>
          </td></tr>}
        </React.Fragment>)}
        {!txns.length&&<tr><td colSpan={7}>Belum ada mutasi. {canWrite&&'Gunakan tombol Import Mutasi.'}</td></tr>}</tbody>
      </table></div>
    </section>}
  </>;
}

function updRow(setForm,i,patch){setForm(f=>({...f,rows:f.rows.map((r,j)=>j===i?{...r,...patch}:r)}));}

function MatchPanel({txn,accountId,onPick,onClose,busy}){
  const [data,setData]=useState(null),[manual,setManual]=useState({journal_line_id:'',payment_id:''}),[err,setErr]=useState('');
  useEffect(()=>{api(`/banking/accounts/${accountId}/match-suggestions?transaction_id=${txn.id}`)
    .then(setData).catch(e=>setErr(e.message))},[txn.id,accountId]);
  const amt=txn.debit>0?txn.debit:txn.credit;
  return <div style={{padding:'8px 4px'}}>
    <b>Saran Pencocokan</b> {err&&<span className="notice danger" style={{display:'inline-block',marginLeft:8}}>{err}</span>}
    <p style={{color:'#64748b'}}>Nominal {num(amt)} · tanggal jendela ±{data?.window_days||7} hari.</p>
    {!data?<p>Mencari...</p>:<>
      {!!data.journal_line_suggestions.length&&<div className="table-scroll"><table>
        <thead><tr><th>Jurnal</th><th>Tanggal</th><th>Keterangan</th><th style={{textAlign:'right'}}>Nominal</th><th>Selisih hari</th><th/></tr></thead>
        <tbody>{data.journal_line_suggestions.map(s=><tr key={s.journal_line_id}>
          <td>{s.entry_no}</td><td>{s.entry_date}</td><td>{s.description||'—'}</td>
          <td style={{textAlign:'right'}}>{num(s.debit||s.credit)}</td><td>{s.days_diff} hari</td>
          <td><button className="btn sm primary" disabled={busy} onClick={()=>onPick({journal_line_id:s.journal_line_id})}>Cocokkan</button></td></tr>)}</tbody>
      </table></div>}
      {!!data.payment_suggestions.length&&<div className="table-scroll"><table>
        <thead><tr><th>Pembayaran</th><th>Invoice</th><th>Tanggal</th><th style={{textAlign:'right'}}>Nominal</th><th>Selisih hari</th><th/></tr></thead>
        <tbody>{data.payment_suggestions.map(s=><tr key={s.payment_id}>
          <td>PAY#{s.payment_id}</td><td>{s.invoice_no}</td><td>{s.payment_date}</td>
          <td style={{textAlign:'right'}}>{num(s.amount)}</td><td>{s.days_diff!=null?s.days_diff+' hari':'—'}</td>
          <td><button className="btn sm primary" disabled={busy} onClick={()=>onPick({payment_id:s.payment_id})}>Cocokkan</button></td></tr>)}</tbody>
      </table></div>}
      {!data.journal_line_suggestions.length&&!data.payment_suggestions.length&&<div className="empty">Tidak ada saran otomatis. Pilih target manual di bawah.</div>}
    </>}
    <div className="form-grid" style={{marginTop:10}}>
      <label>Journal Line ID<input type="number" value={manual.journal_line_id} onChange={e=>setManual({journal_line_id:e.target.value,payment_id:''})}/></label>
      <label>Payment ID<input type="number" value={manual.payment_id} onChange={e=>setManual({journal_line_id:'',payment_id:e.target.value})}/></label>
    </div>
    <div className="form-actions">
      <button className="btn" onClick={onClose}>Tutup</button>
      <button className="btn primary" disabled={busy||(!manual.journal_line_id&&!manual.payment_id)}
        onClick={()=>onPick(manual.journal_line_id?{journal_line_id:Number(manual.journal_line_id)}:{payment_id:Number(manual.payment_id)})}>Cocokkan Manual</button>
    </div>
  </div>;
}

/* ── Tab Treasury ───────────────────────────────────────────────────────── */
function TreasuryPanel({onError}){
  const [d,setD]=useState(null);
  useEffect(()=>{api('/banking/treasury').then(setD).catch(e=>onError(e.message))},[]); // eslint-disable-line
  if(!d)return <p>Memuat...</p>;
  return <>
    <div className="cards">
      <div className="stat blue"><span>Total Kas & Bank</span><strong>{money(d.total_cash_and_bank)}</strong><small>per {d.as_of}</small></div>
    </div>
    <section className="panel"><h2>Posisi per Akun Kas/Bank (dari jurnal POSTED)</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Akun</th><th style={{textAlign:'right'}}>Saldo</th></tr></thead>
        <tbody>{d.positions.map(p=><tr key={p.account_id}><td>{p.code}</td><td>{p.name}</td>
          <td style={{textAlign:'right'}}>{money(p.balance)}</td></tr>)}
        {!d.positions.length&&<tr><td colSpan={3}>Belum ada akun COA kas/bank (is_cash_account).</td></tr>}</tbody>
      </table></div>
    </section>
    <section className="panel"><h2>Rekening Bank & Saldo Tertandingi</h2>
      <div className="table-scroll"><table>
        <thead><tr><th>Kode</th><th>Bank</th><th>No. Rek</th><th style={{textAlign:'right'}}>Saldo Statement</th><th style={{textAlign:'right'}}>Saldo Jurnal</th><th style={{textAlign:'right'}}>Selisih</th></tr></thead>
        <tbody>{d.bank_accounts.map(a=><tr key={a.id}><td>{a.code}</td>
          <td>{a.bank_name}<br/><small style={{color:'#64748b'}}>{a.account_name||''}</small></td>
          <td>{a.account_no||'—'}</td>
          <td style={{textAlign:'right'}}>{money(a.statement_balance)}</td>
          <td style={{textAlign:'right'}}>{a.journal_balance==null?'—':money(a.journal_balance)}</td>
          <td style={{textAlign:'right'}}>{a.difference==null?'—':(a.difference===0?<span className="badge green">0</span>:money(a.difference))}</td></tr>)}
        {!d.bank_accounts.length&&<tr><td colSpan={6}>Belum ada rekening bank terdaftar.</td></tr>}</tbody>
      </table></div>
      <p style={{color:'#64748b',marginTop:8}}>{d.rule}</p>
    </section>
  </>;
}
