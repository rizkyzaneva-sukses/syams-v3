import React from 'react';
import {digitsOnly,rupiahInputText} from '../money';

/* Input uang: ketik angka biasa, langsung tampil "Rp. 1.000.000".
   `value` dan `onChange` memakai string digit murni ("1000000"), jadi bisa langsung diganti
   dengan <input type="number"> lama: `Number(form.amount)` tetap bekerja. */
export default function MoneyInput({value,onChange,required,disabled,readOnly,placeholder='Rp. 0',max,id,'aria-label':ariaLabel,className}){
  const text=rupiahInputText(value);
  function handle(e){
    let digits=digitsOnly(e.target.value);
    if(max!=null&&digits!==''&&Number(digits)>Number(max)) digits=String(Math.round(Number(max)));
    onChange(digits);
  }
  return <input id={id} className={'money-input'+(className?' '+className:'')} type="text" inputMode="numeric" autoComplete="off"
    aria-label={ariaLabel} placeholder={placeholder} required={required} disabled={disabled} readOnly={readOnly}
    value={text} onChange={handle}/>;
}
