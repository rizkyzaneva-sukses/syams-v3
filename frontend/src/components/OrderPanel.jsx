import React,{useCallback,useEffect,useState} from 'react';
import {api} from '../api';
import {AuthImage} from './ImageUpload';
import {canActOnStage,canBlock,canChangePic,invoiceTone,sampleTone,stageHint,statusTone} from '../control';

export const TYPE_LABEL={SAMPLE_ONLY:'Sample saja',SAMPLE_PRODUCTION:'Sample + produksi',REPEAT_PRODUCTION:'Produksi saja'};

export function Chip({stage}){
  const tone=statusTone(stage.status);
  return <span className={'stage-chip st-'+tone+(stage.is_current?' is-now':'')} title={stageHint(stage)||stage.label}>{stage.status}</span>;
}

export default function OrderPanel({orderId,role,pics,onClose,onChanged}){
  const [order,setOrder]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [problem,setProblem]=useState(null);   // null = form tertutup
  const reload=useCallback(()=>api('/control/orders/'+orderId).then(setOrder).catch(e=>setErr(e.message)),[orderId]);
  useEffect(()=>{reload()},[reload]);

  async function act(path,body,method='POST'){
    setBusy(true);setErr('');
    try{const next=await api('/control/orders/'+orderId+path,{method,body:JSON.stringify(body||{})});setOrder(o=>({...next,blocks:o?.blocks}));await reload();onChanged();return true}
    catch(e){setErr(e.message);return false}finally{setBusy(false)}
  }
  async function resolve(id){
    const note=window.prompt('Catatan penyelesaian masalah (boleh kosong):');
    if(note===null)return;
    setBusy(true);setErr('');
    try{await api('/control/blocks/'+id+'/resolve',{method:'POST',body:JSON.stringify({note:note||null})});await reload();onChanged()}
    catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  function ask(label){const reason=window.prompt(label);return reason&&reason.trim().length>=3?reason.trim():null}

  const current=order?.stages.find(s=>s.is_current);
  const canDoCurrent=current&&current.kind==='manual'&&canActOnStage(role,current.code);
  return <div className="modal-bg" onClick={onClose}><div className="modal wide" onClick={e=>e.stopPropagation()}>
    <div className="modal-head"><h2>{orderId}{order?` · ${order.buyer}`:''}</h2><button type="button" className="icon-btn" onClick={onClose} aria-label="Tutup">×</button></div>
    <div className="modal-body">
      {err&&<div className="notice danger" role="alert">{err}</div>}
      {!order?<p>Memuat…</p>:<>
        <div className="order-meta">
          <span><b>{order.articles.join(', ')}</b> · {order.total_qty} pcs{order.extra_total?` (+${order.extra_total} extra)`:''}</span>
          <span>{TYPE_LABEL[order.order_type]}</span>
          <span>Deadline {order.deadline||'-'}</span>
          {order.design_image_id?<AuthImage id={order.design_image_id} alt="Desain" className="order-thumb"/>:order.mockup_url&&<a href={order.mockup_url} target="_blank" rel="noreferrer">Lihat mockup ↗</a>}
        </div>
        <div className="cmo-facts" aria-label="Status CMO">
          <span>Invoice <b className={'badge '+invoiceTone(order.invoice_status)}>{order.invoice_status}</b></span>
          <span>Bayar <b className={'badge '+(order.payment==='LUNAS'?'green':'amber')}>{order.payment}</b></span>
          <span>Sample <b className={'badge '+sampleTone(order.sample_status)}>{order.sample_status}</b>{order.revision&&<small> {order.revision}</small>}</span>
          <span>Buyer approval <b className={'badge '+(order.buyer_approval==='PENDING'?'amber':'green')}>{order.buyer_approval}</b></span>
          <span>SPK <b className={'badge '+(order.spk_released?'green':'gray')}>{order.spk_released?'RELEASED':'BELUM'}</b></span>
          <span>Siap ke COO <b className={'badge '+(order.ready_to_coo?'green':'gray')}>{order.ready_to_coo?'YA':'BELUM'}</b></span>
        </div>
        <div className={'now-box '+order.priority.toLowerCase()}>
          <div><small>Tahap sekarang</small><b>{order.current_stage_label}</b>{current?.due_date&&<small> · jatuh tempo {current.due_date}</small>}<div className="next">{order.next_action||'—'}</div></div>
          <div className="now-actions">
            {canDoCurrent&&<button className="btn primary big" disabled={busy||current.has_block} title={current.has_block?'Selesaikan masalah terbuka dulu':''} onClick={()=>act(`/stages/${current.code}/done`,{})}>✓ Selesai</button>}
            {current&&canBlock(role,current.code)&&<button className="btn danger-btn big" disabled={busy} onClick={()=>setProblem({stage_code:current.code,problem:'',next_action:'',pic_name:''})}>⚠ Ada masalah</button>}
            {current?.has_block&&canDoCurrent&&<small className="hint">Ada masalah terbuka — tandai "Masalah selesai" dulu sebelum menyelesaikan tahap.</small>}
            {!current&&<span className="badge green">Semua tahap selesai</span>}
            {current&&current.kind==='auto'&&<small className="hint">Tahap ini mengikuti alur CMO/Finance — selesai sendiri saat gate-nya lolos.</small>}
          </div>
        </div>

        {order.open_blocks.length>0&&<div className="blocks">{order.open_blocks.map(b=><div className="block-row" key={b.id}>
          <div><b>{b.stage_code?b.stage_code.replace('_',' '):'ORDER'}</b> — {b.problem}<br/><small>Next action: {b.next_action}{b.pic_name?` · PIC ${b.pic_name}`:''}</small></div>
          {canBlock(role,b.stage_code)&&<button className="btn sm" disabled={busy} onClick={()=>resolve(b.id)}>Masalah selesai</button>}
        </div>)}</div>}

        {problem&&<form className="problem-form" onSubmit={e=>{e.preventDefault();act('/blocks',{...problem,pic_name:problem.pic_name||null}).then(ok=>{if(ok)setProblem(null)})}}>
          <label>Masalahnya apa? *<textarea required minLength={3} rows={2} value={problem.problem} onChange={e=>setProblem({...problem,problem:e.target.value})} placeholder="Contoh: bahan kurang 20 yard"/></label>
          <label>Next action — mau ngapain? *<textarea required minLength={3} rows={2} value={problem.next_action} onChange={e=>setProblem({...problem,next_action:e.target.value})} placeholder="Contoh: order ulang ke supplier hari ini"/></label>
          <label>PIC penanggung jawab<select value={problem.pic_name} onChange={e=>setProblem({...problem,pic_name:e.target.value})}><option value="">Ikuti PIC tahap</option>{pics.map(p=><option key={p.id} value={p.name}>{p.name}</option>)}</select></label>
          <div className="row-end"><button type="button" className="btn" onClick={()=>setProblem(null)}>Batal</button><button className="btn primary" disabled={busy}>Simpan masalah</button></div>
        </form>}

        <h3>Semua tahap</h3>
        <table className="stage-list"><thead><tr><th>Tahap</th><th>Status</th><th>SLA</th><th>PIC</th><th>Keterangan</th><th></th></tr></thead><tbody>
          {order.stages.map(s=>{
            const mine=s.kind==='manual'&&s.toggleable&&!s.from_data&&canActOnStage(role,s.code);
            return <tr key={s.code} className={s.is_current?'is-current':''}>
              <td><b>{s.label}</b>{s.kind==='auto'&&<small> otomatis</small>}</td><td><Chip stage={s}/></td>
              <td>{s.sla_days} hr</td>
              <td>{s.pic||'-'}{s.pic_override&&<small> *</small>}</td>
              <td className="wrap"><small>{stageHint(s)}{s.from_data?' · otomatis dari data modul lain':''}{s.note?` · ${s.note}`:''}</small></td>
              <td className="row-actions">
                {mine&&s.status!=='SELESAI'&&s.status!=='-'&&!s.is_current&&<button className="btn sm" disabled={busy} onClick={()=>act(`/stages/${s.code}/done`,{})}>Selesai</button>}
                {mine&&s.status!=='SELESAI'&&s.status!=='-'&&<button className="btn sm" disabled={busy} onClick={()=>{const r=ask('Alasan tahap ini dilewati (tidak dipakai):');if(r)act(`/stages/${s.code}/skip`,{reason:r})}}>Lewati</button>}
                {mine&&s.status==='-'&&<button className="btn sm" disabled={busy} onClick={()=>act(`/stages/${s.code}/enable`,{})}>Pakai</button>}
                {mine&&s.status==='SELESAI'&&<button className="btn sm" disabled={busy} onClick={()=>{const r=ask('Alasan membuka kembali tahap ini:');if(r)act(`/stages/${s.code}/reopen`,{reason:r})}}>Buka lagi</button>}
                {canChangePic(role)&&s.kind==='manual'&&s.status!=='-'&&<select aria-label={'PIC '+s.label} value={s.pic_override?s.pic:''} disabled={busy} onChange={e=>act(`/stages/${s.code}/pic`,{pic_name:e.target.value||null},'PUT')}><option value="">PIC default</option>{pics.map(p=><option key={p.id} value={p.name}>{p.name}</option>)}</select>}
              </td></tr>;})}
        </tbody></table>
        {order.blocks?.some(b=>b.resolved_at)&&<details><summary>Riwayat masalah</summary>{order.blocks.filter(b=>b.resolved_at).map(b=><div key={b.id} className="block-row done"><div>{b.stage_code||'ORDER'} — {b.problem}<br/><small>Selesai {String(b.resolved_at).slice(0,10)}{b.resolution_note?` · ${b.resolution_note}`:''}</small></div></div>)}</details>}
      </>}
    </div>
  </div></div>;
}
