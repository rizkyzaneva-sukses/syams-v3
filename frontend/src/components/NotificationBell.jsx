import React,{useEffect,useRef,useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {Bell,Check,CheckCheck,Info,AlertTriangle,AlertOctagon,Inbox,ExternalLink} from 'lucide-react';
import {api} from '../api';

/* Lonceng notifikasi untuk topbar.

   Desain sengaja self-contained (inline style, tanpa kelas CSS baru) supaya bisa
   ditempel ke topbar Layout.jsx tanpa menyentuh styles.css. Warna badge mengikuti
   severity: CRITICAL merah, WARNING kuning, INFO biru — sama dengan konvensi
   statusTone() di business.js agar bahasa visual aplikasi tetap satu.

   Sumber data: GET /platform/notifications (sudah difilter server-side ke
   notifikasi milik user / role-nya / broadcast) dan
   GET /platform/notifications/unread-count untuk badge angka. */

const SEV={
  CRITICAL:{color:'#dc2626',bg:'#fef2f2',Icon:AlertOctagon,label:'Kritis'},
  WARNING:{color:'#d97706',bg:'#fffbeb',Icon:AlertTriangle,label:'Peringatan'},
  INFO:{color:'#2563eb',bg:'#eff6ff',Icon:Info,label:'Info'},
};
const CAT_LABEL={
  APPROVAL:'Persetujuan',DUE_DATE:'Tenggat',MATERIAL:'Material',
  FINANCE:'Keuangan',EXCEPTION:'Exception',SYSTEM:'Sistem',
};

function timeAgo(iso){
  if(!iso) return '';
  const then=new Date(iso.endsWith('Z')||iso.includes('+')?iso:iso+'Z');
  const secs=Math.max(0,Math.floor((Date.now()-then.getTime())/1000));
  if(secs<60) return 'baru saja';
  if(secs<3600) return Math.floor(secs/60)+' mnt lalu';
  if(secs<86400) return Math.floor(secs/3600)+' jam lalu';
  if(secs<604800) return Math.floor(secs/86400)+' hari lalu';
  return then.toLocaleDateString('id-ID',{day:'numeric',month:'short'});
}

export default function NotificationBell(){
  const [open,setOpen]=useState(false);
  const [count,setCount]=useState(0);
  const [items,setItems]=useState([]);
  const [loading,setLoading]=useState(false);
  const wrapRef=useRef(null);
  const nav=useNavigate();

  function refreshCount(){
    api('/platform/notifications/unread-count')
      .then(r=>setCount(Number(r?.count||0)))
      .catch(()=>{});
  }

  function loadList(){
    setLoading(true);
    api('/platform/notifications?limit=20')
      .then(rows=>setItems(Array.isArray(rows)?rows:[]))
      .catch(()=>setItems([]))
      .finally(()=>setLoading(false));
  }

  // Polling ringan: badge diperbarui berkala tanpa membuka dropdown.
  useEffect(()=>{refreshCount();const t=setInterval(refreshCount,60000);return ()=>clearInterval(t)},[]);

  // Tutup dropdown saat klik di luar / tekan Escape.
  useEffect(()=>{
    if(!open) return;
    function onDown(e){if(wrapRef.current&&!wrapRef.current.contains(e.target)) setOpen(false)}
    function onKey(e){if(e.key==='Escape') setOpen(false)}
    document.addEventListener('mousedown',onDown);
    document.addEventListener('keydown',onKey);
    return ()=>{document.removeEventListener('mousedown',onDown);document.removeEventListener('keydown',onKey)};
  },[open]);

  function toggle(){
    const next=!open;
    setOpen(next);
    if(next) loadList();
  }

  async function markRead(id){
    setItems(list=>list.map(n=>n.id===id?{...n,is_read:true}:n));
    setCount(c=>Math.max(0,c-1));
    try{await api(`/platform/notifications/${id}/read`,{method:'POST'})}catch{loadList();refreshCount()}
  }

  async function markAllRead(){
    setItems(list=>list.map(n=>({...n,is_read:true})));
    setCount(0);
    try{await api('/platform/notifications/read-all',{method:'POST'})}catch{loadList();refreshCount()}
  }

  function openItem(n){
    // Tandai dibaca lalu navigasi ke halaman terkait bila ada link_path.
    if(!n.is_read) markRead(n.id);
    if(n.link_path){setOpen(false);nav(n.link_path)}
  }

  const badgeColor=count>0?'#dc2626':'#94a3b8';

  return <div ref={wrapRef} style={{position:'relative',marginLeft:'12px'}}>
    <button onClick={toggle} title="Notifikasi" aria-label="Notifikasi"
      style={{position:'relative',width:'40px',height:'40px',borderRadius:'9px',border:'1px solid #e2e8f0',
              background:open?'#eef4fb':'#f4f7fb',cursor:'pointer',display:'grid',placeItems:'center'}}>
      <Bell size={19} color="#334155"/>
      {count>0&&<span style={{position:'absolute',top:'-6px',right:'-6px',minWidth:'18px',height:'18px',
        padding:'0 4px',borderRadius:'9px',background:'#dc2626',color:'white',fontSize:'10px',fontWeight:800,
        display:'grid',placeItems:'center',boxShadow:'0 0 0 2px white'}}>{count>99?'99+':count}</span>}
    </button>

    {open&&<div style={{position:'absolute',top:'calc(100% + 8px)',right:0,width:'380px',maxWidth:'92vw',
        background:'white',border:'1px solid #e5eaf1',borderRadius:'12px',boxShadow:'0 16px 44px rgba(15,23,42,.18)',
        zIndex:120,overflow:'hidden'}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',
          padding:'12px 14px',borderBottom:'1px solid #eef2f7'}}>
        <div style={{display:'flex',alignItems:'center',gap:'8px',fontWeight:800,fontSize:'14px',color:'#10203d'}}>
          Notifikasi
          {count>0&&<span style={{background:badgeColor,color:'white',fontSize:'11px',fontWeight:700,
            borderRadius:'10px',padding:'1px 7px'}}>{count}</span>}
        </div>
        {items.some(n=>!n.is_read)&&<button onClick={markAllRead}
          style={{border:0,background:'transparent',color:'#2563eb',fontSize:'12px',fontWeight:700,
                  cursor:'pointer',display:'flex',alignItems:'center',gap:'4px'}}>
          <CheckCheck size={14}/>Tandai semua
        </button>}
      </div>

      <div style={{maxHeight:'420px',overflowY:'auto'}}>
        {loading?<div style={{padding:'22px',textAlign:'center',color:'#94a3b8',fontSize:'13px'}}>Memuat...</div>
        :items.length===0?<div style={{padding:'30px 18px',textAlign:'center',color:'#94a3b8'}}>
          <Inbox size={30} style={{opacity:.5}}/>
          <div style={{fontSize:'13px',marginTop:'6px'}}>Tidak ada notifikasi</div>
        </div>
        :items.map(n=>{
          const sev=SEV[n.severity]||SEV.INFO;
          return <div key={n.id} onClick={()=>openItem(n)}
            style={{display:'flex',gap:'10px',padding:'12px 14px',cursor:'pointer',
              borderBottom:'1px solid #f1f5f9',background:n.is_read?'white':'#f8fbff'}}>
            <div style={{flexShrink:0,width:'30px',height:'30px',borderRadius:'8px',background:sev.bg,
                display:'grid',placeItems:'center'}}>
              <sev.Icon size={16} color={sev.color}/>
            </div>
            <div style={{flex:1,minWidth:0}}>
              <div style={{display:'flex',alignItems:'center',gap:'6px',marginBottom:'2px'}}>
                {!n.is_read&&<span style={{width:'7px',height:'7px',borderRadius:'50%',background:'#2563eb',flexShrink:0}}/>}
                <span style={{fontSize:'11px',fontWeight:700,color:sev.color,textTransform:'uppercase',letterSpacing:'.3px'}}>
                  {CAT_LABEL[n.category]||n.category}
                </span>
                <span style={{marginLeft:'auto',fontSize:'11px',color:'#94a3b8',flexShrink:0}}>{timeAgo(n.created_at)}</span>
              </div>
              <div style={{fontSize:'13px',fontWeight:n.is_read?600:700,color:'#10203d',
                  whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{n.title}</div>
              {n.body&&<div style={{fontSize:'12px',color:'#64748b',marginTop:'2px',
                  display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflow:'hidden'}}>{n.body}</div>}
              <div style={{display:'flex',alignItems:'center',gap:'10px',marginTop:'5px'}}>
                {n.link_path&&<span style={{fontSize:'11px',color:'#2563eb',display:'flex',alignItems:'center',gap:'3px'}}>
                  <ExternalLink size={11}/>Buka</span>}
                {!n.is_read&&<button onClick={e=>{e.stopPropagation();markRead(n.id)}}
                  style={{border:0,background:'transparent',color:'#64748b',fontSize:'11px',fontWeight:700,
                          cursor:'pointer',display:'flex',alignItems:'center',gap:'3px',padding:0}}>
                  <Check size={11}/>Tandai dibaca
                </button>}
              </div>
            </div>
          </div>;
        })}
      </div>
    </div>}
  </div>;
}
