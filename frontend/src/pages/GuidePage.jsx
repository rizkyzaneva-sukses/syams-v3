import React,{useState} from 'react';

const FLOW=[
 {step:'Order',role:'CMO',desc:'Buat order + artikel. Rute produksi WAJIB diisi, contoh: Cutting > Sewing > QC.',warn:'Rute produksi tidak bisa diubah setelah order dibuat.'},
 {step:'Quotation',role:'CMO buat, CFO approve',desc:'Isi harga jual & HPP per artikel. CFO menyetujui bila margin memenuhi kebijakan.',warn:'Di atas limit approval CFO, persetujuan naik ke CEO.'},
 {step:'Invoice & Payment',role:'CFO',desc:'Terbitkan invoice, catat pembayaran, lalu rekonsiliasi dengan bukti mutasi bank.',warn:'Nominal terbayar dihitung dari record payment, tidak bisa diketik manual.'},
 {step:'Finance Gate',role:'CFO',desc:'Setujui gate keuangan setelah pembayaran terekonsiliasi. Produksi terkunci sebelum ini.',warn:null},
 {step:'Material',role:'COO buat, CFO beli',desc:'Susun BOM, ajukan material request, terbitkan purchase order sampai status READY.',warn:'Material request harus ≥ kebutuhan BOM, dan PO harus ≥ material request.'},
 {step:'Production Plan',role:'COO',desc:'Buat rencana produksi lalu ubah statusnya menjadi APPROVED.',warn:'Order tipe Sample Only tidak bisa masuk produksi.'},
 {step:'SPK',role:'CMO Support → CMO Manager',desc:'Deby membuat draft, Generate, Preview PDF, lalu Print. Cecep merilis versi tercetak ke produksi setelah semua gate siap.',warn:'Print tidak sama dengan Release.'},
 {step:'Produksi & QC',role:'COO / PIC',desc:'Catat perpindahan proses mengikuti rute artikel, lalu lakukan QC final.',warn:'Urutan proses mengikuti rute yang diisi saat order dibuat.'},
 {step:'Shipment',role:'COO + CFO',desc:'Packing hingga PACKED, minta finance gate pengiriman ke CFO, lalu ubah ke SHIPPED.',warn:'Pengiriman dengan sisa tagihan butuh persetujuan CEO.'},
 {step:'Delivery',role:'COO + CMO',desc:'COO mencatat serah terima fisik dan tanggalnya. CMO mencatat konfirmasi penerimaan dari customer.',warn:'Konfirmasi customer tidak mengubah status fisik shipment.'},
 {step:'Closing',role:'CMO + COO + CFO',desc:'CMO menutup sisi customer, COO menutup operasional, CFO menutup keuangan. Order tertutup bila ketiganya selesai.',warn:'Setiap sisi hanya dapat ditutup oleh pemilik perannya.'},
];

const ROLES=[
 {role:'CEO',desc:'Kebijakan pricing, exception, decision tracker, approval pengiriman bermasalah. Bisa melihat seluruh modul.'},
 {role:'CMO Manager',desc:'Customer, order, quotation, sample/PPM, SPK, konfirmasi penerimaan, closing customer.'},
 {role:'CMO Support',desc:'Menyiapkan draft, Generate, Preview PDF, dan Print SPK tanpa wewenang Release.'},
 {role:'CFO Manager',desc:'Approval quotation, invoice, payment, rekonsiliasi, purchase order, finance gate, closing keuangan.'},
 {role:'Finance Support',desc:'Input invoice dan pembayaran tanpa wewenang approval gate.'},
 {role:'COO Manager',desc:'Material request, BOM, rencana produksi, movement, QC, shipment, serah terima fisik, closing operasional.'},
 {role:'Sample / Printing / Production PIC',desc:'Mengerjakan tugas produksi yang ditugaskan dan mencatat progres.'},
 {role:'CHRO Manager',desc:'Karyawan, training, performance, dan isu kepegawaian.'},
 {role:'HR Support',desc:'Membantu administrasi kepegawaian.'},
 {role:'Shipment Admin',desc:'Administrasi pengiriman dan packing.'},
];

const FAQ=[
 {q:'Kenapa SPK tidak bisa dirilis?',a:'Pastikan Deby sudah Generate dan Print SPK. Cecep baru dapat Release setelah quotation, finance gate, material, rencana produksi, dan rute artikel memenuhi syarat. Halaman detail order menampilkan alasan gate yang masih tertahan.'},
 {q:'Saya lupa mengisi rute produksi, bagaimana?',a:'Rute tidak bisa diperbaiki setelah order dibuat karena belum ada fitur ubah artikel. Order tersebut harus dibuat ulang. Pastikan kolom Rute Produksi terisi sebelum menyimpan.'},
 {q:'Siapa yang mencatat status DELIVERED?',a:'COO Manager mencatat serah terima fisik beserta tanggalnya setelah shipment SHIPPED. CMO Manager mencatat konfirmasi customer secara terpisah.'},
 {q:'Kenapa menu tertentu tidak muncul?',a:'Menu disaring sesuai wewenang peran Anda. Kalau memang membutuhkannya, minta administrator meninjau peran akun Anda.'},
 {q:'Kenapa closing tidak bisa diselesaikan sendiri?',a:'Penutupan sisi customer, operasional, dan keuangan dipisah ke CMO, COO, dan CFO sebagai kontrol internal.'},
 {q:'Kenapa nominal terbayar di invoice tidak bisa diketik?',a:'Nilainya dijumlahkan otomatis dari catatan pembayaran supaya tidak ada selisih. Tambahkan record pembayaran untuk mengubahnya.'},
];

export default function GuidePage(){
 const [open,setOpen]=useState(null);
 return <div className="page">
  <div className="page-title"><div>
   <h1>Panduan Penggunaan</h1>
   <p>Alur kerja order dari awal sampai ditutup, beserta aturan yang sering menghambat.</p>
  </div></div>

  <div className="notice info">
   Sistem menolak lompatan tahap. Kalau sebuah tombol tidak bisa ditekan, biasanya ada tahap sebelumnya yang belum selesai — alasannya ditampilkan di halaman detail order.
  </div>

  <div className="panel">
   <h2>Alur Order</h2>
   <div className="flow-list">
    {FLOW.map((f,i)=><div className="flow-row" key={f.step}>
     <div className="flow-step-circle">{i+1}</div>
     <div style={{flex:1}}>
      <div className="flow-step-label">{f.step}</div>
      <div className="flow-step-role">{f.role}</div>
      <p style={{margin:'4px 0 0'}}>{f.desc}</p>
      {f.warn&&<p className="mini" style={{margin:'4px 0 0',opacity:.85}}>Catatan: {f.warn}</p>}
     </div>
    </div>)}
   </div>
  </div>

  <div className="panel">
   <h2>Wewenang Peran</h2>
   <table>
    <thead><tr><th>Peran</th><th>Tanggung jawab</th></tr></thead>
    <tbody>{ROLES.map(r=><tr key={r.role}><td><strong>{r.role}</strong></td><td>{r.desc}</td></tr>)}</tbody>
   </table>
  </div>

  <div className="panel">
   <h2>Pertanyaan yang Sering Muncul</h2>
   {FAQ.map((f,i)=><div key={i} style={{borderBottom:'1px solid rgba(148,163,184,.2)',padding:'10px 0'}}>
    <button type="button" className="btn" style={{width:'100%',textAlign:'left',background:'transparent',border:0,padding:0,cursor:'pointer',fontWeight:600}}
      onClick={()=>setOpen(open===i?null:i)} aria-expanded={open===i}>
     {open===i?'− ':'+ '}{f.q}
    </button>
    {open===i&&<p style={{margin:'8px 0 0'}}>{f.a}</p>}
   </div>)}
  </div>
 </div>;
}
