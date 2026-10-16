import React from 'react';
import {SIZES} from '../sizes';
import {parseExtraSize,serializeExtraSize} from '../control';

/* Extra size = spare internal untuk reject (bukan permintaan buyer). Cukup isi angka
   di ukuran yang butuh spare; tersimpan sebagai "M+2/L+1" seperti kolom EXTRA SIZE di sheet. */
export default function ExtraSizeInput({value,onChange}){
  const map=parseExtraSize(value);
  const legacy=Object.keys(map).filter(s=>!SIZES.includes(s)).sort();
  const total=Object.values(map).reduce((a,b)=>a+b,0);
  const set=(size,raw)=>{const next={...map};if(raw===''||Number(raw)<=0)delete next[size];else next[size]=Number(raw);onChange(serializeExtraSize(next))};
  return <div className="size-breakdown"><div className="size-grid">
    {[...SIZES,...legacy].map(size=><label key={size} className="size-cell"><span>{size}</span>
      <input type="number" min="0" step="1" inputMode="numeric" placeholder="0" aria-label={`Extra ukuran ${size}`} value={map[size]!=null?String(map[size]):''} onChange={e=>set(size,e.target.value)}/></label>)}
    <div className="size-total">Extra <b>{total}</b> pcs</div></div>
    <small className="size-hint">Spare internal untuk reject. Kosongkan bila tidak ada.</small></div>;
}
