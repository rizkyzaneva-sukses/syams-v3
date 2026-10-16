import React,{useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';

/* 15 tugas CFO dalam satu papan — setiap kartu membuka halaman kerjanya (Finance Support sudah dihapus; semua di CFO). */
export default function CFOTaskGrid(){
  const [tasks,setTasks]=useState([]),[err,setErr]=useState('');
  useEffect(()=>{api('/cfo/workspace').then(d=>setTasks(d.tasks)).catch(e=>setErr(e.message))},[]);
  if(err)return null;
  return <section className="panel"><div className="panel-head"><h2>Ruang Kerja CFO</h2><span>{tasks.length} tugas</span></div>
    <div className="task-grid">{tasks.map((t,i)=><Link key={t.key} to={t.path} className="task-card"><span className="task-no">{i+1}</span><b>{t.title}</b><small>{t.metric}</small></Link>)}</div></section>;
}
