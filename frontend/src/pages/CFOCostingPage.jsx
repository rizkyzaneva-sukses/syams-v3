import React,{useEffect,useMemo,useState} from 'react';
import {useOutletContext, useSearchParams} from 'react-router-dom';
import {api} from '../api';

/* Revisi #21 (CFO-007 Actual Cost & Actual HPP) + #24 (CFO-010 Operational Cost)
   + #25 (CFO-011 Payroll, Team Bonus & Attendance)
   + #26 (CFO-012 Financial Statements)
   + #27 (CFO-013 Budget & Cash Planning)
   + #30 (CFO-002 HPP, Pricing & 30% Markup).
*/

const DIRECTIONS={OVER:'danger',UNDER:'warning',ON_TRACK:'ok'};
const STATUS_TONE={REVIEWED:'ok',OPEN:'info',NO_DATA:'muted'};

function rupiah(value){
  const n=Number(value??0);
  if(!Number.isFinite(n)) return '-';
  const sign=n<0?'-':'';
  return sign+'Rp '+Math.abs(n).toLocaleString('id-ID',{maximumFractionDigits:2});
}
function priceQty(value){return value==null||value===''?null:String(value);}

export default function CFOCostingPage(){
  const {me}=useOutletContext();
  const role=me?.role;
  const canView=['CFO_MANAGER','FINANCE_SUPPORT','CEO'].includes(role);
  const canFilter=['CFO_MANAGER','CEO'].includes(role);

  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') || 'variance';
  function setTab(t){
    setSearchParams({tab: t});
  }

  const [variance,setVariance]=useState(null);
  const [operational,setOperational]=useState(null);
  const [payrollBonus,setPayrollBonus]=useState(null);
  const [statements,setStatements]=useState(null);
  const [budgetPlan,setBudgetPlan]=useState(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [statusFilter,setStatusFilter]=useState('ALL');
  const [period,setPeriod]=useState('month');
  const [windowRange,setWindowRange]=useState({date_from:'',date_to:''});
  const [openOrder,setOpenOrder]=useState(null);
  const [openArticle,setOpenArticle]=useState(null);

  useEffect(()=>{
    if(!canView) return;
    let cancelled=false;
    setLoading(true);setError('');
    const params=new URLSearchParams({status:statusFilter,limit:'200'});
    if(canFilter&&windowRange.date_from) params.set('date_from',windowRange.date_from);
    if(canFilter&&windowRange.date_to) params.set('date_to',windowRange.date_to);
    const opsParams=new URLSearchParams({period});
    if(canFilter&&windowRange.date_from) opsParams.set('date_from',windowRange.date_from);
    if(canFilter&&windowRange.date_to) opsParams.set('date_to',windowRange.date_to);
    
    Promise.all([
      api('/cfo/actual-cost-variance?'+params.toString()).catch(()=>null),
      api('/cfo/operational-cost?'+opsParams.toString()).catch(()=>null),
      api('/cfo/payroll-and-bonus').catch(()=>null),
      api('/cfo/financial-statements').catch(()=>null),
      api('/cfo/budget-cash-planning').catch(()=>null),
    ]).then(([v,o,pb,fs,bp])=>{
      if(!cancelled){
        setVariance(v);
        setOperational(o);
        setPayrollBonus(pb);
        setStatements(fs);
        setBudgetPlan(bp);
      }
    })
      .catch(e=>{if(!cancelled) setError(e.message)})
      .finally(()=>{if(!cancelled) setLoading(false)});
    return ()=>{cancelled=true};
  },[canView,canFilter,statusFilter,period,windowRange.date_from,windowRange.date_to]);

  const orders=useMemo(()=>variance?.orders||[],[variance]);
  const totals=variance?.totals;
  const opt=operational?.totals;
  const registerReady=operational?.operational_cost_register?.available;

  if(!canView) return <div className="page"><div className="notice danger">Laporan biaya aktual & biaya operasional hanya untuk CFO dan CEO.</div></div>;

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>CFO Costing, Finance &amp; Statements</h1>
        <p>Kontrol HPP, biaya operasional, payroll &amp; bonus tim, laporan keuangan, dan perencanaan kas.</p>
      </div>
    </div>
    {error&&<div className="notice danger">{error}</div>}

    <div className="filter-pills" style={{display:'flex',flexWrap:'wrap',gap:6,marginBottom:16}}>
      <button className={'pill'+(tab==='variance'?' active':'')} onClick={()=>setTab('variance')}>Actual Cost vs HPP</button>
      <button className={'pill'+(tab==='operational'?' active':'')} onClick={()=>setTab('operational')}>Biaya Operasional</button>
      <button className={'pill'+(tab==='payroll'?' active':'')} onClick={()=>setTab('payroll')}>Payroll</button>
      <button className={'pill'+(tab==='bonus'?' active':'')} onClick={()=>setTab('bonus')}>Team Bonus</button>
      <button className={'pill'+(tab==='attendance'?' active':'')} onClick={()=>setTab('attendance')}>Attendance</button>
      <button className={'pill'+(tab==='statements'?' active':'')} onClick={()=>setTab('statements')}>Financial Statements</button>
      <button className={'pill'+(tab==='budget'?' active':'')} onClick={()=>setTab('budget')}>Budget &amp; Cash Planning</button>
    </div>

    {canFilter&&['variance','operational'].includes(tab)&&<section className="panel">
      <div className="filter-bar">
        {tab==='variance'&&<label>Status
          <select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}>
            <option value="ALL">Semua</option>
            <option value="OVER">OVER — biaya di atas rencana</option>
            <option value="UNDER">UNDER — biaya di bawah rencana</option>
            <option value="ON_TRACK">ON_TRACK — sama dengan rencana</option>
            <option value="NO_DATA">NO_DATA — belum ada biaya aktual</option>
            <option value="REVIEWED">REVIEWED — sudah dikunci CFO</option>
          </select>
        </label>}
        {tab==='operational'&&<label>Periode
          <select value={period} onChange={e=>setPeriod(e.target.value)}>
            <option value="month">Bulanan</option>
            <option value="quarter">Kuartal</option>
            <option value="year">Tahunan</option>
            <option value="all">Semua periode</option>
          </select>
        </label>}
        <label>Dari tanggal<input type="date" value={windowRange.date_from} onChange={e=>setWindowRange({...windowRange,date_from:e.target.value})}/></label>
        <label>Sampai tanggal<input type="date" value={windowRange.date_to} onChange={e=>setWindowRange({...windowRange,date_to:e.target.value})}/></label>
        <button className="btn" onClick={()=>setWindowRange({date_from:'',date_to:''})}>Reset rentang</button>
      </div>
    </section>}

    {loading&&<div className="empty">Memuat laporan biaya...</div>}

    {!loading&&tab==='variance'&&<>
      {totals&&<div className="cards">
        <div className="stat blue"><strong>{rupiah(totals.quotation_hpp)}</strong><span>HPP quotation (estimasi)</span></div>
        <div className="stat"><strong>{rupiah(totals.actual_total_cost)}</strong><span>HPP aktual (pemakaian nyata)</span></div>
        <div className={'stat '+(Number(totals.variance)>0?'red':'green')}><strong>{rupiah(totals.variance)}</strong><span>Selisih {totals.variance_percent?`(${totals.variance_percent}%)`:''}</span></div>
        <div className="stat amber"><strong>{totals.over_count} / {totals.under_count}</strong><span>Order OVER / UNDER</span></div>
        <div className="stat"><strong>{totals.reviewed_count} / {totals.orders}</strong><span>Sudah dikunci CFO</span></div>
      </div>}

      {variance?.basis&&<p className="revision-field-hint">Sumber aktual: {variance.basis.actual_source.join(', ')} · Sumber estimasi: {variance.basis.estimated_source} · {variance.basis.correction}</p>}

      <section className="panel">
        <div className="panel-head"><h2>Per Order ID — HPP quotation vs HPP aktual</h2></div>
        {!orders.length&&<div className="empty">Tidak ada order pada filter ini.</div>}
        {orders.length>0&&<div className="table-scroll"><table>
          <thead><tr>
            <th>Order ID</th><th>Buyer</th><th>HPP quotation</th><th>HPP aktual</th><th>Selisih</th><th>%</th><th>Arah</th><th>Status</th><th>Pemakaian lengkap</th><th></th>
          </tr></thead>
          <tbody>{orders.map(o=><React.Fragment key={o.order_fk}>
            <tr>
              <td className="td-sm">{o.order_id}</td>
              <td>{o.buyer}</td>
              <td>{rupiah(o.quotation_hpp)}</td>
              <td>{rupiah(o.actual)}</td>
              <td className="td-sm">{rupiah(o.variance)}</td>
              <td>{o.variance_percent!=null?`${o.variance_percent}%`:'—'}</td>
              <td><span className={'badge '+DIRECTIONS[o.direction]}>{o.direction}</span></td>
              <td><span className={'badge '+(STATUS_TONE[o.status]||'muted')}>{o.status}</span></td>
              <td>{o.has_actual_data?(o.material_usage_complete?'Ya':'Belum'):'Belum ada biaya'}</td>
              <td className="td-action"><button className="btn mini" onClick={()=>{setOpenOrder(openOrder===o.order_fk?null:o.order_fk);setOpenArticle(null)}}>{openOrder===o.order_fk?'Tutup':'Telusuri'}</button></td>
            </tr>
            {openOrder===o.order_fk&&<tr><td colSpan={10}>
              <div className="revision-detail-link">
                <b>Penyebab selisih</b>
                {o.causes.length===0&&<p className="revision-field-hint">Tidak ada selisih yang perlu ditelusuri.</p>}
                <ul>{o.causes.map((c,i)=><li key={i}>
                  <b>{c.cause}</b> — {c.detail} <small>Owner: {c.owner}</small>{' '}
                  {c.evidence?.length?<small>Bukti: {c.evidence.join(', ')}</small>:<small>Belum ada referensi bukti{c.traceable?'':' — belum bisa ditelusuri'}</small>}
                </li>)}</ul>
                <p className="revision-field-hint">
                  Quotation: {o.quotation_no||'—'} (versi {o.quotation_version??'—'}, sumber {o.hpp_source}) ·
                  Cut-off {o.cut_off} · Review: {o.review.reviewed?`dikunci ${o.review.reviewed_at} (${rupiah(o.review.reviewed_total)})`:'belum dikunci'} ·
                  Aksi: {o.articles[0]?.next_action||'—'}
                </p>
                <p className="revision-field-hint">Rencana material BOM: {rupiah(o.planned_material_cost)} · Material aktual: {rupiah(o.actual_material_cost)} · Margin aktual: {o.actual_margin_percent!=null?`${o.actual_margin_percent}%`:'belum tersedia'}</p>
              </div>
              <div className="table-scroll"><table>
                <thead><tr><th>Article ID</th><th>Qty</th><th>HPP quotation</th><th>Aktual</th><th>Selisih</th><th>%</th><th>Waste (qty)</th><th>Bukti</th></tr></thead>
                <tbody>{o.articles.map(a=><tr key={a.article_id}>
                  <td>{a.article_code}</td>
                  <td>{a.qty}</td>
                  <td>{rupiah(a.quotation_hpp)}</td>
                  <td>{rupiah(a.actual_total_cost)}</td>
                  <td className="td-sm">{rupiah(a.variance)}</td>
                  <td>{a.variance_percent!=null?`${a.variance_percent}%`:'—'}</td>
                  <td>{a.waste_qty}</td>
                  <td className="td-action"><button className="btn mini" onClick={()=>setOpenArticle(openArticle===a.article_id?null:a.article_id)}>{openArticle===a.article_id?'Tutup':'Sumber'}</button></td>
                </tr>)}
                {openArticle&&o.articles.filter(a=>a.article_id===openArticle).map(a=><tr key={'src-'+a.article_id}><td colSpan={8}>
                  <b>Jejak sumber {a.article_code}</b>
                  <div className="table-scroll"><table>
                    <thead><tr><th>Sumber</th><th>ID</th><th>Kategori</th><th>Material</th><th>Qty</th><th>Harga satuan aktual</th><th>Nominal</th><th>Referensi bukti</th><th>Dicatat</th></tr></thead>
                    <tbody>{a.evidence.map(e=><tr key={e.source+e.entry_id}>
                      <td className="td-sm">{e.source}</td><td>{e.entry_id}</td><td>{e.entry_category}</td>
                      <td>{e.material_name||'—'}</td><td>{priceQty(e.qty)??'—'}</td>
                      <td>{e.actual_unit_cost?rupiah(e.actual_unit_cost):'—'}</td>
                      <td>{rupiah(e.amount)}</td><td className="td-sm">{e.source_ref||'—'}</td>
                      <td className="td-sm">{e.recorded_at||'—'}</td>
                    </tr>)}</tbody>
                  </table></div>
                  {!a.evidence.length&&<p className="revision-field-hint">Belum ada entri biaya aktual untuk artikel ini.</p>}
                </td></tr>)}
                </tbody>
              </table></div>
            </td></tr>}
          </React.Fragment>)}</tbody>
        </table></div>}
      </section>
    </>}

    {!loading&&tab==='operational'&&<>
      {opt&&<div className="cards">
        <div className="stat blue"><strong>{rupiah(opt.hpp_total)}</strong><span>HPP produksi (material + upah/overhead)</span></div>
        <div className="stat amber"><strong>{rupiah(opt.operational_total)}</strong><span>Biaya operasional (di luar HPP)</span></div>
        <div className="stat"><strong>{rupiah(opt.hpp_material)}</strong><span>Material terpakai</span></div>
        <div className="stat"><strong>{rupiah(opt.purchase_orders_not_hpp)}</strong><span>Pembelian material (bukan HPP)</span></div>
        <div className="stat red"><strong>{rupiah(opt.unclassified_total)}</strong><span>Belum terklasifikasi</span></div>
      </div>}

      <p className="revision-field-hint">Window: {operational?.window?.date_from||'awal'} s/d {operational?.window?.date_to||'sekarang'} · {operational?.separation_rule?.NON_HPP}</p>

      {!registerReady&&<div className="notice">
        Register biaya operasional formal belum tersedia di database: kolom/tabel biaya operasional
        (OPEX, asset/capex, advance, reimbursement, vendor, cost center, approval, payment status,
        accounting period) belum ada di model. Kebutuhan sudah ditulis di <b>REQUESTS/cfo_costing.md</b>.
        Angka di bawah hanya yang bisa dihitung hari ini tanpa tabel baru.
      </div>}

      <section className="panel">
        <div className="panel-head"><h2>Per periode</h2></div>
        {!operational?.periods?.length&&<div className="empty">Belum ada biaya tercatat pada window &amp; periode ini.</div>}
        {operational?.periods?.length>0&&<div className="table-scroll"><table>
          <thead><tr><th>Periode</th><th>HPP produksi</th><th>Biaya operasional</th><th>Jumlah entri</th><th>Order terkait</th></tr></thead>
          <tbody>{operational.periods.map(p=><React.Fragment key={p.period}>
            <tr><td>{p.period}</td><td>{rupiah(p.hpp_total)}</td><td>{rupiah(p.non_hpp_total)}</td><td>{p.entry_count}</td><td className="td-sm">{p.orders.join(', ')||'—'}</td></tr>
            {p.categories.length>0&&<tr><td colSpan={5}>
              <div className="table-scroll"><table>
                <thead><tr><th>Kategori</th><th>Entri</th><th>Nominal</th></tr></thead>
                <tbody>{p.categories.map(c=><tr key={c.key}><td>{c.label}</td><td>{c.entry_count}</td><td>{rupiah(c.amount)}</td></tr>)}</tbody>
              </table></div>
            </td></tr>}
          </React.Fragment>)}</tbody>
        </table></div>}
      </section>

      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2>Biaya operasional per kategori</h2></div>
          {!operational?.operational_by_category?.length&&<div className="empty">Belum ada biaya operasional terklasifikasi.</div>}
          {operational?.operational_by_category?.length>0&&<div className="table-scroll"><table>
            <thead><tr><th>Kategori</th><th>Entri</th><th>Nominal</th></tr></thead>
            <tbody>{operational.operational_by_category.map(c=><tr key={c.key}><td>{c.label}</td><td>{c.entry_count}</td><td>{rupiah(c.amount)}</td></tr>)}</tbody>
          </table></div>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>HPP produksi per kategori</h2></div>
          {!operational?.hpp_by_category?.length&&<div className="empty">Belum ada HPP produksi tercatat.</div>}
          {operational?.hpp_by_category?.length>0&&<div className="table-scroll"><table>
            <thead><tr><th>Kategori</th><th>Entri</th><th>Nominal</th></tr></thead>
            <tbody>{operational.hpp_by_category.map(c=><tr key={c.key}><td>{c.label}</td><td>{c.entry_count}</td><td>{rupiah(c.amount)}</td></tr>)}</tbody>
          </table></div>}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Klasifikasi kategori biaya</h2></div>
        <p className="revision-field-hint">Kategori tidak dikenal tidak pernah otomatis masuk HPP — ditahan di luar sampai CFO mengklasifikasi.</p>
        {!operational?.classification?.length&&<div className="empty">Belum ada entri untuk diklasifikasi.</div>}
        {operational?.classification?.length>0&&<div className="table-scroll"><table>
          <thead><tr><th>Kategori</th><th>Bucket</th><th>Entri</th><th>Nominal</th><th>Dasar</th></tr></thead>
          <tbody>{operational.classification.map(c=><tr key={c.category}>
            <td>{c.category}</td>
            <td><span className={'badge '+(c.bucket==='HPP_PRODUCTION'?'ok':c.bucket==='NON_HPP'?'info':'warning')}>{c.bucket}</span></td>
            <td>{c.entry_count}</td><td>{rupiah(c.amount)}</td><td className="td-sm">{c.reason}</td>
          </tr>)}</tbody>
        </table></div>}
      </section>

      {operational?.purchase_orders_not_hpp?.length>0&&<section className="panel">
        <div className="panel-head"><h2>Pembelian material — bukan HPP produksi</h2></div>
        <p className="revision-field-hint">Purchasing adalah biaya pengadaan; HPP memakai material yang benar-benar terpakai. Tidak pernah dijumlahkan ke HPP.</p>
        <div className="table-scroll"><table>
          <thead><tr><th>PO</th><th>Order ID</th><th>Supplier</th><th>Item</th><th>Status</th><th>Nominal</th><th>Tanggal</th></tr></thead>
          <tbody>{operational.purchase_orders_not_hpp.map(p=><tr key={p.po_no}>
            <td className="td-sm">{p.po_no}</td><td className="td-sm">{p.order_id||'—'}</td><td>{p.supplier||'—'}</td>
            <td>{p.item||'—'}</td><td>{p.status}</td><td>{rupiah(p.amount)}</td><td className="td-sm">{p.incurred_at||'—'}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}

      <section className="panel">
        <div className="panel-head"><h2>Buku besar biaya (audit trail)</h2></div>
        {!operational?.ledger?.length&&<div className="empty">Belum ada entri biaya pada window ini.</div>}
        {operational?.ledger?.length>0&&<div className="table-scroll"><table>
          <thead><tr><th>Bucket</th><th>Kategori</th><th>Order ID</th><th>Artikel</th><th>Departemen</th><th>Deskripsi</th><th>Nominal</th><th>Sumber</th><th>Referensi bukti</th><th>Tanggal</th></tr></thead>
          <tbody>{operational.ledger.map((r,i)=><tr key={r.source+'-'+r.source_id}>
            <td><span className={'badge '+(r.bucket==='HPP_PRODUCTION'?'ok':r.bucket==='NON_HPP'?'info':'warning')}>{r.bucket}</span></td>
            <td>{r.category}</td><td className="td-sm">{r.order_id||'—'}</td><td className="td-sm">{r.article_code||'—'}</td>
            <td>{r.department||'—'}</td><td>{r.description}</td><td>{rupiah(r.amount)}</td>
            <td className="td-sm">{r.source} #{r.source_id}</td><td className="td-sm">{r.source_ref||'—'}</td><td className="td-sm">{r.incurred_at||'—'}</td>
          </tr>)}</tbody>
        </table></div>}
      </section>
    </>}

    {!loading&&tab==='payroll'&&payrollBonus&&<>
      <div className="cards">
        <div className="stat blue"><strong>{rupiah(payrollBonus.payroll.total_net)}</strong><span>Total Gaji Bersih</span></div>
        <div className="stat"><strong>{payrollBonus.payroll.count}</strong><span>Total Karyawan Aktif</span></div>
        <div className="stat green"><strong>Siap Diproses</strong><span>Status Pembayaran CFO</span></div>
      </div>
      <section className="panel">
        <div className="panel-head"><h2>Register Payroll Karyawan — Periode {payrollBonus.period}</h2></div>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>No Pegawai</th><th>Nama</th><th>Divisi</th><th>Posisi</th><th>Gaji Pokok</th><th>Tunjangan</th><th>Potongan</th><th>Gaji Bersih</th><th>Persetujuan CFO</th><th>Status Bayar</th><th>Bukti / Referensi</th>
          </tr></thead>
          <tbody>{payrollBonus.payroll.rows.map(r=><tr key={r.employee_id}>
            <td><b>{r.employee_no}</b></td><td>{r.name}</td><td>{r.division}</td><td>{r.position}</td>
            <td>{rupiah(r.base_pay)}</td><td>{rupiah(r.allowance)}</td><td>{rupiah(r.deduction)}</td><td><b>{rupiah(r.net_pay)}</b></td>
            <td><span className={'badge '+(r.approval_status==='APPROVED'?'ok':'warning')}>{r.approval_status}</span></td>
            <td><span className="badge info">{r.payment_status}</span></td><td><small>{r.evidence}</small></td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}

    {!loading&&tab==='bonus'&&payrollBonus&&<>
      <div className="notice info" style={{marginBottom:16}}>
        <b>Kebijakan Team Bonus Terkunci (CFO-011):</b> Bonus wajib dihitung <b>PER TIM</b> (Divisi), bukan per individu. Dihitung dari 10% pool net profit kuartal perusahaan, dibagi merata kepada anggota tim yang aktif.
      </div>
      <div className="cards">
        <div className="stat purple"><strong>{rupiah(payrollBonus.team_bonus.total_pool)}</strong><span>Total Pool Bonus Perusahaan</span></div>
        <div className="stat green"><strong>{payrollBonus.team_bonus.rows.length} Tim</strong><span>Tim Berhak Menerima</span></div>
      </div>
      <section className="panel">
        <div className="panel-head"><h2>Distribusi Team Bonus per Divisi — Kuartal Q1 2026</h2></div>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>ID Tim</th><th>Nama Tim</th><th>Dasar Net Profit</th><th>Aturan Rate</th><th>Pool Bonus Tim</th><th>Jumlah Anggota</th><th>Estimasi / Anggota</th><th>Kelayakan</th><th>Persetujuan</th><th>Audit Trail</th>
          </tr></thead>
          <tbody>{payrollBonus.team_bonus.rows.map(t=><tr key={t.team_id}>
            <td><b>{t.team_id}</b></td><td>{t.team_name}</td><td>{rupiah(t.net_profit_base)}</td>
            <td><small>{t.rate_rule}</small></td><td><b>{rupiah(t.pool_bonus)}</b></td><td>{t.headcount} orang</td>
            <td><strong style={{color:'#16a34a'}}>{rupiah(t.per_member_est)}</strong></td>
            <td><span className="badge ok">{t.eligibility}</span></td><td><span className="badge ok">{t.approval}</span></td>
            <td><small>{t.audit}</small></td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}

    {!loading&&tab==='attendance'&&payrollBonus&&<>
      <div className="notice info" style={{marginBottom:16}}>
        <b>{payrollBonus.attendance.summary}:</b> Log kehadiran diverifikasi langsung oleh keuangan CFO untuk mencegah manipulasi perhitungan upah dan lembur.
      </div>
      <section className="panel">
        <div className="panel-head"><h2>Rekap Presensi Karyawan (Input Sumber Payroll)</h2></div>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>No Pegawai</th><th>Nama</th><th>Divisi</th><th>Shift</th><th>Hadir (Hari)</th><th>Absen</th><th>Terlambat (Mnt)</th><th>Lembur (Jam)</th><th>Status</th><th>Sumber Verifikasi</th>
          </tr></thead>
          <tbody>{payrollBonus.attendance.rows.map(a=><tr key={a.employee_id}>
            <td><b>{a.employee_no}</b></td><td>{a.name}</td><td>{a.division}</td><td>{a.shift}</td>
            <td>{a.present_days}</td><td>{a.absent_days}</td><td>{a.lateness_minutes} mnt</td><td>{a.overtime_hours} jam</td>
            <td><span className="badge ok">{a.status}</span></td><td><small>{a.source}</small></td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}

    {!loading&&tab==='statements'&&statements&&<>
      <div className="notice info" style={{marginBottom:16}}>
        <b>Status Laporan Keuangan:</b> {statements.period_status} · Disiapkan oleh: {statements.prepared_by} · {statements.audit}
      </div>
      <div className="grid2">
        <section className="panel">
          <div className="panel-head"><h2>Laporan Laba Rugi (Profit &amp; Loss)</h2></div>
          <div className="table-scroll"><table>
            <tbody>
              <tr><td><b>Pendapatan Penjualan (Revenue)</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.p_and_l.revenue)}</b></td></tr>
              <tr><td>HPP Material Terpakai</td><td style={{textAlign:'right'}}>{rupiah(statements.p_and_l.cogs_material)}</td></tr>
              <tr><td>HPP Tenaga Kerja Langsung &amp; Overhead</td><td style={{textAlign:'right'}}>{rupiah(statements.p_and_l.cogs_labor)}</td></tr>
              <tr style={{background:'#f8fafc'}}><td><b>Total HPP (COGS)</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.p_and_l.cogs_total)}</b></td></tr>
              <tr style={{background:'#f0fdf4'}}><td><b>Laba Kotor (Gross Profit)</b></td><td style={{textAlign:'right'}}><strong style={{color:'#16a34a'}}>{rupiah(statements.p_and_l.gross_profit)} ({statements.p_and_l.gross_margin_percent}%)</strong></td></tr>
              <tr><td>Biaya Operasional (OPEX)</td><td style={{textAlign:'right'}}>{rupiah(statements.p_and_l.opex)}</td></tr>
              <tr style={{background:'#eff6ff'}}><td><b>Laba Bersih Operasional</b></td><td style={{textAlign:'right'}}><strong style={{color:'#1e40af'}}>{rupiah(statements.p_and_l.net_profit)} ({statements.p_and_l.net_margin_percent}%)</strong></td></tr>
            </tbody>
          </table></div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2>Laporan Arus Kas (Cash Flow)</h2></div>
          <div className="table-scroll"><table>
            <tbody>
              <tr><td>Arus Kas Masuk Operasional (Penerimaan Piutang)</td><td style={{textAlign:'right',color:'#16a34a'}}>{rupiah(statements.cash_flow.operating_inflow)}</td></tr>
              <tr><td>Pembayaran Hutang Supplier &amp; Makloon (AP)</td><td style={{textAlign:'right',color:'#dc2626'}}>-{rupiah(statements.cash_flow.supplier_payments)}</td></tr>
              <tr><td>Pembayaran Payroll Karyawan</td><td style={{textAlign:'right',color:'#dc2626'}}>-{rupiah(statements.cash_flow.payroll_payments)}</td></tr>
              <tr><td>Pembayaran Biaya Operasional (OPEX)</td><td style={{textAlign:'right',color:'#dc2626'}}>-{rupiah(statements.cash_flow.opex_payments)}</td></tr>
              <tr style={{background:'#f8fafc'}}><td><b>Arus Kas Bersih Operasi</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.cash_flow.net_operating_cash)}</b></td></tr>
              <tr style={{background:'#f0fdf4'}}><td><b>Saldo Kas &amp; Bank Akhir</b></td><td style={{textAlign:'right'}}><strong style={{color:'#16a34a'}}>{rupiah(statements.cash_flow.ending_cash)}</strong></td></tr>
            </tbody>
          </table></div>
        </section>
      </div>

      <section className="panel" style={{marginTop:20}}>
        <div className="panel-head"><h2>Neraca Keuangan (Balance Sheet)</h2></div>
        <div className="grid2">
          <div className="table-scroll"><table>
            <thead><tr><th colSpan={2}>Aset (Aktiva)</th></tr></thead>
            <tbody>
              <tr><td>Kas &amp; Bank</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.assets.cash_and_bank)}</td></tr>
              <tr><td>Piutang Usaha (AR)</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.assets.accounts_receivable)}</td></tr>
              <tr><td>Persediaan Barang &amp; Bahan Baku</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.assets.inventory)}</td></tr>
              <tr><td>Aset Tetap (Peralatan &amp; Mesin)</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.assets.fixed_assets)}</td></tr>
              <tr style={{background:'#eff6ff'}}><td><b>Total Aset</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.balance_sheet.assets.total_assets)}</b></td></tr>
            </tbody>
          </table></div>

          <div className="table-scroll"><table>
            <thead><tr><th colSpan={2}>Kewajiban &amp; Ekuitas (Pasiva)</th></tr></thead>
            <tbody>
              <tr><td>Hutang Usaha Supplier &amp; Makloon (AP)</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.liabilities.accounts_payable)}</td></tr>
              <tr><td>Beban Akrual / Payroll</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.liabilities.accrued_payroll)}</td></tr>
              <tr style={{background:'#fef2f2'}}><td><b>Total Kewajiban</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.balance_sheet.liabilities.total_liabilities)}</b></td></tr>
              <tr><td>Modal Disetor</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.equity.capital)}</td></tr>
              <tr><td>Laba Ditahan</td><td style={{textAlign:'right'}}>{rupiah(statements.balance_sheet.equity.retained_earnings)}</td></tr>
              <tr style={{background:'#f0fdf4'}}><td><b>Total Ekuitas &amp; Kewajiban</b></td><td style={{textAlign:'right'}}><b>{rupiah(statements.balance_sheet.equity.total_equity)}</b></td></tr>
            </tbody>
          </table></div>
        </div>
      </section>
    </>}

    {!loading&&tab==='budget'&&budgetPlan&&<>
      <div className="cards">
        <div className="stat blue"><strong>{rupiah(budgetPlan.cash_planning.opening_cash)}</strong><span>Kas Pembuka</span></div>
        <div className="stat green"><strong>{rupiah(budgetPlan.cash_planning.expected_collection)}</strong><span>Proyeksi Penerimaan Piutang</span></div>
        <div className="stat amber"><strong>{rupiah(budgetPlan.cash_planning.expected_ap_payment)}</strong><span>Komitmen Pembayaran AP</span></div>
        <div className="stat purple"><strong>{rupiah(budgetPlan.cash_planning.projected_ending_cash)}</strong><span>Proyeksi Kas Akhir</span></div>
      </div>

      <div className="notice" style={{marginBottom:16, borderLeft: '4px solid #10b981'}}>
        <b>Keputusan Kas &amp; Likuiditas:</b> {budgetPlan.cash_planning.decision_needed}
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Anggaran Belanja per Departemen / Cost Center</h2></div>
        <div className="table-scroll"><table>
          <thead><tr>
            <th>Departemen</th><th>Alokasi Anggaran</th><th>Realisasi Aktual</th><th>Komitmen PO/PR</th><th>Sisa Anggaran</th><th>Status Anggaran</th>
          </tr></thead>
          <tbody>{budgetPlan.department_budgets.map(b=><tr key={b.department}>
            <td><b>{b.department}</b></td>
            <td>{rupiah(b.budget)}</td>
            <td>{rupiah(b.actual)}</td>
            <td>{rupiah(b.committed)}</td>
            <td><strong style={{color:'#16a34a'}}>{rupiah(b.remaining)}</strong></td>
            <td><span className={'badge '+(b.status==='ON_TRACK'?'ok':'warning')}>{b.status}</span></td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}
  </div>;
}
