import React from 'react';
import {SIZES, parseSizeBreakdown, serializeSizeBreakdown} from '../sizes';

/* Input Size breakdown (permintaan Bos 16 Okt 2026 — revisi):
   SEMUA ukuran baku (XS…XXXXL) langsung disiapkan sebagai kotak qty, sehingga
   operator CUKUP MENGISI ANGKA — tidak perlu memilih dari dropdown, tidak perlu
   mengetik nama ukuran, dan tidak perlu menambah baris. Satu artikel boleh punya
   beberapa ukuran sekaligus (isi beberapa kotak).

   Nilai tetap disimpan sebagai string "SIZE:qty" dipisah koma (mis. "S:10, M:20")
   — sama dengan data lama & seed, jadi tidak ada migrasi DB. Ukuran lama di luar
   daftar (mis. angka 30/32 dari data lama) tetap ditampilkan sebagai kotak
   tambahan agar tidak hilang saat diedit.

   Komponen ini murni terkendali (controlled) dari `value`: karena seluruh kotak
   ukuran standar selalu dirender dari konstanta SIZES, kotak kosong pun tetap
   terlihat — tidak ada lagi kasus "baris baru hilang" seperti versi dropdown. */
export default function SizeBreakdownInput({value, onChange}) {
  const map = parseSizeBreakdown(value);
  const legacy = Object.keys(map).filter(size => !SIZES.includes(size)).sort();
  const sizes = [...SIZES, ...legacy];
  const total = Object.values(map).reduce((sum, qty) => sum + (Number(qty) || 0), 0);

  const setSize = (size, raw) => {
    const next = {...map};
    if (raw === '' || Number(raw) <= 0) delete next[size];
    else next[size] = Number(raw);
    onChange(serializeSizeBreakdown(next));
  };

  return <div className="size-breakdown">
    <div className="size-grid">
      {sizes.map(size => <label key={size}
        className={'size-cell' + (legacy.includes(size) ? ' legacy' : '')}>
        <span>{size}</span>
        <input type="number" min="0" step="1" inputMode="numeric" placeholder="0"
          aria-label={`Qty ukuran ${size}`}
          value={map[size] != null ? String(map[size]) : ''}
          onChange={e => setSize(size, e.target.value)}/>
      </label>)}
      <div className="size-total">Total <b>{total}</b> pcs</div>
    </div>
    <small className="size-hint">Isi angka pada ukuran yang dipakai — boleh lebih dari satu ukuran. Kosongkan yang tidak dipakai.</small>
  </div>;
}
