import React, {useEffect, useRef, useState} from 'react';
import {SIZES} from '../sizes';

/* Input Size breakdown (permintaan Bos 16 Okt 2026):
   ukuran DIPILIH dari dropdown XS…XXXXL (tidak perlu mengetik nama ukuran),
   operator hanya mengisi qty. Baris bisa ditambah/dihapus. Nilai disimpan
   sebagai string "SIZE:qty" dipisah koma — sama dengan data lama, jadi tidak
   ada migrasi DB.

   Baris dipegang sebagai STATE LOKAL supaya baris kosong yang baru ditambah
   tetap terlihat (kalau langsung diserialisasi, baris tanpa qty akan hilang
   sehingga tombol "+ Tambah ukuran" tampak tidak bekerja). */
export default function SizeBreakdownInput({value, onChange}) {
  const [rows, setRows] = useState(() => parse(value));
  const lastSent = useRef(serialize(parse(value)));

  /* Sinkron kalau nilai dari luar berubah dan bukan berasal dari komponen ini
     (mis. form dimuat ulang dari server). `lastSent` mencegah loop balik. */
  useEffect(() => {
    const incoming = serialize(parse(value));
    if (incoming !== lastSent.current) {
      lastSent.current = incoming;
      setRows(parse(value));
    }
  }, [value]);

  const commit = next => {
    setRows(next);
    const out = serialize(next);
    lastSent.current = out;
    onChange(out);
  };
  const setRow = (index, patch) => commit(rows.map((row, i) => i === index ? {...row, ...patch} : row));
  const addRow = () => commit([...rows, {size: firstFreeSize(rows), qty: ''}]);
  const removeRow = index => commit(rows.filter((_, i) => i !== index));
  const total = rows.reduce((sum, row) => sum + (Number(row.qty) || 0), 0);

  return <div className="size-breakdown">
    {rows.map((row, index) => <div className="size-row" key={index}>
      <select aria-label="Ukuran" value={row.size}
        onChange={e => setRow(index, {size: e.target.value})}>
        <option value="">Pilih ukuran</option>
        {SIZES.map(size => <option key={size} value={size}>{size}</option>)}
        {/* Ukuran lama di luar daftar standar tetap ditampilkan agar tidak hilang. */}
        {row.size && !SIZES.includes(row.size) && <option value={row.size}>{row.size}</option>}
      </select>
      <input type="number" min="0" step="1" inputMode="numeric" placeholder="Qty"
        aria-label={`Qty ukuran ${row.size || index + 1}`}
        value={row.qty === '' || row.qty == null ? '' : String(row.qty)}
        onChange={e => setRow(index, {qty: e.target.value})}/>
      {rows.length > 1 && <button type="button" className="btn sm danger"
        onClick={() => removeRow(index)} aria-label="Hapus ukuran">×</button>}
    </div>)}
    <div className="size-foot">
      <button type="button" className="btn sm" onClick={addRow}>+ Tambah ukuran</button>
      <small>Total {total} pcs</small>
    </div>
  </div>;
}

/* String "S:10, M:20" atau objek -> [{size, qty}]. Baris kosong tetap
   dipertahankan supaya operator punya baris siap isi. */
function parse(value) {
  if (!value) return [{size: '', qty: ''}];
  if (typeof value === 'object') {
    const rows = Object.entries(value).map(([size, qty]) => ({size: String(size).toUpperCase(), qty}));
    return rows.length ? rows : [{size: '', qty: ''}];
  }
  const rows = String(value).split(/[,;]/).map(part => {
    const [size, qty] = part.split(':');
    return {size: (size || '').trim().toUpperCase(), qty: (qty || '').trim()};
  }).filter(row => row.size || row.qty);
  return rows.length ? rows : [{size: '', qty: ''}];
}

/* Susun "S:10, M:20" dari baris yang punya ukuran DAN qty > 0; baris belum
   lengkap dibuang dari nilai tersimpan (tapi tetap tampil di layar). */
function serialize(rows) {
  return rows.filter(row => row.size && row.qty !== '' && Number(row.qty) > 0)
    .map(row => `${row.size}:${Number(row.qty)}`).join(', ');
}

/* Ukuran default untuk baris baru: ukuran standar pertama yang belum dipakai. */
function firstFreeSize(rows) {
  const used = new Set(rows.map(row => row.size).filter(Boolean));
  return SIZES.find(size => !used.has(size)) || '';
}
