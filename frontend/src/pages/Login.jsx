import React,{useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {api,setToken} from '../api';
import QcQuickLogin from '../components/QcQuickLogin';
const ROLE_HOME={CMO_SUPPORT:'/cmo/today',CMO_MANAGER:'/cmo/priority',CHRO_MANAGER:'/chro',HR_SUPPORT:'/chro',CFO_MANAGER:'/cfo',COO_MANAGER:'/coo',CEO:'/ceo',SAMPLE_PIC:'/sample/today',PRINTING_PIC:'/printing/today',PRODUCTION_PIC:'/tasks',SHIPMENT_ADMIN:'/cfo/shipments',FINANCE_SUPPORT:'/cfo'};
export default function Login(){const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[err,setErr]=useState(''); const nav=useNavigate();
 async function doLogin(em,pw){setErr('');const r=await api('/auth/login',{method:'POST',body:JSON.stringify({email:em,password:pw})});setToken(r.access_token);const me=await api('/auth/me');nav(ROLE_HOME[me.role]||'/master')}
 async function submit(e){e.preventDefault();try{await doLogin(email,password)}catch(x){setErr(x.message)}}
 async function quickLogin(em,pw){setEmail(em);setPassword(pw);try{await doLogin(em,pw)}catch(x){setErr(x.message)}}
 return <div className="login-wrap"><div className="login-card"><div className="brand big"><b>BOS SYAMS</b><span>Business Operating System</span></div><h1>Masuk</h1><p>Satu aplikasi, akses sesuai peran.</p><form onSubmit={submit}><label>Email<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label>{err&&<div className="error">{err}</div>}<button className="primary">Masuk</button></form><QcQuickLogin onPick={(em,pw)=>{setEmail(em);setPassword(pw)}} onAutoLogin={quickLogin}/></div></div>}
