import React,{useMemo,useState} from 'react';
import MoneyInput from '../components/MoneyInput';
import {formatRupiah,rupiahNumber} from '../money';
import {COST_LINES,calcPrice} from '../pricing';

/* Kalkulator harga jual: isi biaya per pcs, cadangan reject, dan margin → harga jual per pcs, laba, dan omzet pesanan. */
export default function CFOPriceCalculatorPage(){
  const [costs,setCosts]=useState(()=>Object.fromEntries(COST_LINES.map(([k])=>[k,''])));
  const [rejectPct,setRejectPct]=useState('3'),[marginPct,setMarginPct]=useState('30'),[roundTo,setRoundTo]=useState('500'),[qty,setQty]=useState('100'),[ppn,setPpn]=useState('0');
  const result=useMemo(()=>calcPrice({costs:Object.fromEntries(Object.entries(costs).map(([k,v])=>[k,rupiahNumber(v)])),rejectPct,marginPct,roundTo,qty,ppnPct:ppn}),[costs,rejectPct,marginPct,roundTo,qty,ppn]);
  return <div className="page">
    <div className="page-title"><div><h1>Kalkulator Harga Jual</h1><p>HPP per pcs + cadangan reject, lalu harga jual = HPP ÷ (1 − margin). Pembulatan selalu naik agar margin tidak turun.</p></div></div>
    <div className="grid-half">
      <section className="panel form-stack"><div className="panel-head"><h2>Biaya per pcs</h2></div>
        {COST_LINES.map(([key,label])=><label key={key}>{label}<MoneyInput value={costs[key]} onChange={v=>setCosts({...costs,[key]:v})} aria-label={label}/></label>)}
        <div className="form-grid">
          <label>Cadangan reject (%)<input type="number" min="0" max="90" step="0.5" value={rejectPct} onChange={e=>setRejectPct(e.target.value)}/></label>
          <label>Margin dari harga jual (%)<input type="number" min="0" max="95" step="0.5" value={marginPct} onChange={e=>setMarginPct(e.target.value)}/></label>
          <label>Bulatkan ke atas ke<select value={roundTo} onChange={e=>setRoundTo(e.target.value)}>{[100,500,1000,5000].map(n=><option key={n} value={n}>{formatRupiah(n)}</option>)}</select></label>
          <label>Qty pesanan (pcs)<input type="number" min="1" value={qty} onChange={e=>setQty(e.target.value)}/></label>
          <label>PPN (%)<input type="number" min="0" max="30" step="0.5" value={ppn} onChange={e=>setPpn(e.target.value)}/></label>
        </div></section>
      <section className="panel"><div className="panel-head"><h2>Hasil</h2></div>
        <div className="price-result"><small>Harga jual per pcs</small><strong>{formatRupiah(result.price)}</strong>{Number(ppn)>0&&<small>Termasuk PPN {ppn}%: <b>{formatRupiah(result.priceWithPpn)}</b></small>}</div>
        <table className="alert-table"><tbody>
          <tr><td>Biaya per pcs (tanpa reject)</td><td className="num">{formatRupiah(result.base)}</td></tr>
          <tr><td>HPP per pcs (termasuk reject)</td><td className="num"><b>{formatRupiah(result.hpp)}</b></td></tr>
          <tr><td>Laba per pcs</td><td className="num">{formatRupiah(result.profit)}</td></tr>
          <tr><td>Margin sebenarnya</td><td className="num"><b>{result.realMarginPct}%</b></td></tr>
          <tr><td>Omzet {result.units} pcs</td><td className="num">{formatRupiah(result.revenue)}</td></tr>
          <tr><td>Total laba {result.units} pcs</td><td className="num"><b>{formatRupiah(result.totalProfit)}</b></td></tr>
        </tbody></table></section>
    </div>
  </div>;
}
