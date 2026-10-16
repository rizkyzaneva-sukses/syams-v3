import React,{useEffect,useRef,useState} from 'react';
import {api} from '../api';

/* Gambar dari server butuh token login, jadi tidak bisa langsung dipakai di <img src>.
   AuthImage mengunduhnya sebagai blob lalu menampilkannya. */
export function useImageUrl(id){
  const [url,setUrl]=useState(null);
  useEffect(()=>{
    if(!id){setUrl(null);return}
    let alive=true,made=null;
    api('/files/images/'+id,{responseType:'blob'}).then(blob=>{if(!alive)return;made=URL.createObjectURL(blob);setUrl(made)}).catch(()=>alive&&setUrl(null));
    return()=>{alive=false;if(made)URL.revokeObjectURL(made)};
  },[id]);
  return url;
}

export function AuthImage({id,alt='',className,style}){
  const url=useImageUrl(id);
  return url?<img src={url} alt={alt} className={className} style={style}/>:null;
}

/* Unggah gambar (logo / desain / size chart): pilih file → langsung tersimpan → tampil pratinjau.
   `value` = id gambar tersimpan; `onChange(id|null)`. Menggantikan kolom "link Drive". */
export default function ImageUpload({kind,value,onChange,label,hint,disabled}){
  const input=useRef(null);
  const [busy,setBusy]=useState(false),[err,setErr]=useState('');
  async function pick(event){
    const file=event.target.files?.[0];
    event.target.value='';
    if(!file)return;
    if(!file.type.startsWith('image/')){setErr('Pilih file gambar (PNG, JPG, atau WEBP)');return}
    if(file.size>8*1024*1024){setErr('Ukuran gambar maksimal 8 MB');return}
    setBusy(true);setErr('');
    try{
      const body=new FormData();body.append('kind',kind);body.append('file',file);
      const saved=await api('/files/images',{method:'POST',body});
      onChange(saved.id);
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  return <div className="image-upload">
    {label&&<span className="image-upload-label">{label}</span>}
    <div className={'image-upload-box'+(value?' has-image':'')}>
      {value?<AuthImage id={value} alt={label||'Gambar'} className="image-upload-preview"/>:<span className="image-upload-empty">{busy?'Mengunggah…':'Belum ada gambar'}</span>}
    </div>
    <div className="image-upload-actions">
      <button type="button" className="btn sm" disabled={busy||disabled} onClick={()=>input.current?.click()}>{value?'Ganti gambar':'Pilih gambar'}</button>
      {value&&!disabled&&<button type="button" className="btn sm" onClick={()=>onChange(null)}>Hapus</button>}
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" onChange={pick} hidden aria-label={label||'Unggah gambar'}/>
    </div>
    {hint&&!err&&<small>{hint}</small>}{err&&<small className="danger" role="alert">{err}</small>}
  </div>;
}
