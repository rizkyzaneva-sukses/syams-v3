import React, { useState } from 'react';

// ---------------------------------------------------------------------------
// QC QUICK-LOGIN (trial internal saja)
// ---------------------------------------------------------------------------
// Panel ini HANYA muncul kalau build/dev environment menyalakan flag
//   VITE_QC_QUICK_LOGIN=1   (lihat frontend/.env.local)
// File .env.local tidak ikut ter-commit (di-gitignore), jadi di repo publik /
// production panel ini tidak pernah dirender sama sekali.
//
// Password TIDAK di-hardcode: dibaca dari VITE_QC_QUICK_PASSWORD. Jadi walau
// file source ini ikut publik, tidak ada kredensial yang bisa dibaca di sana.
// ---------------------------------------------------------------------------

const ACCOUNTS = [
  { email: 'ceo@syams.local', label: 'CEO', name: 'Iyan', home: 'Dashboard CEO' },
  { email: 'cmo.manager@syams.local', label: 'CMO Manager', name: 'Cecep', home: 'Prioritas Sales' },
  { email: 'cmo.support@syams.local', label: 'CMO Support', name: 'Deby', home: 'Tugas Hari Ini' },
  { email: 'cfo.manager@syams.local', label: 'CFO Manager', name: 'Lutfi', home: 'Keuangan' },
  { email: 'finance.support@syams.local', label: 'Finance Support', name: '—', home: 'Keuangan' },
  { email: 'coo.manager@syams.local', label: 'COO Manager', name: 'Siti', home: 'Eksekusi Produksi' },
  { email: 'sample.pic@syams.local', label: 'Sample PIC', name: 'Fahrul', home: 'Sample' },
  { email: 'printing.pic@syams.local', label: 'Printing PIC', name: 'Iman', home: 'Printing' },
  { email: 'production.pic@syams.local', label: 'Production PIC', name: '—', home: 'Tugas Produksi' },
  { email: 'chro.manager@syams.local', label: 'CHRO Manager', name: 'Yuni', home: 'SDM' },
  { email: 'hr.support@syams.local', label: 'HR Support', name: '—', home: 'SDM' },
  { email: 'shipment.admin@syams.local', label: 'Shipment Admin', name: '—', home: 'Pengiriman' },
];

export default function QcQuickLogin({ onPick, onAutoLogin }) {
  const enabled = import.meta.env.VITE_QC_QUICK_LOGIN === '1';
  const qcPassword = import.meta.env.VITE_QC_QUICK_PASSWORD || '';
  const [open, setOpen] = useState(false);

  if (!enabled) return null; // production / repo publik: tidak dirender

  return (
    <div className="qc-quick">
      <button
        type="button"
        className="qc-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        🧪 {open ? 'Tutup' : 'Buka'} Panel QC — Login Cepat (trial)
      </button>

      {open && (
        <div className="qc-panel">
          <p className="qc-note">
            Hanya untuk QC internal. Password akun diambil dari konfigurasi lokal
            (<code>.env.local</code>) — tidak tertulis di kode. Panel ini tidak ikut ke repo publik.
          </p>
          <div className="qc-grid">
            {ACCOUNTS.map((a) => (
              <button
                key={a.email}
                type="button"
                className="qc-account"
                onClick={() => onPick(a.email, qcPassword)}
                title={a.email}
              >
                <b>{a.label}</b>
                <span>{a.name !== '—' ? a.name : a.email.split('@')[0]}</span>
                <em>{a.home}</em>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="qc-autologin"
            onClick={() => onAutoLogin(ACCOUNTS[3].email, qcPassword)}
          >
            ⚡ Masuk langsung sebagai CFO (Lutfi)
          </button>
        </div>
      )}
    </div>
  );
}
