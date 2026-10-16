import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';

/* Regresi — HIGHLIGHT MENU SIDEBAR.

   Bug yang dijaga: NavLink bawaan React Router mencocokkan path secara PREFIX
   dan menambahkan kelas `active` sendiri, sehingga satu klik bisa menyalakan
   BANYAK menu sekaligus:
     - menu induk /ceo, /cfo, /coo, /chro nyala di tiap sub-halaman;
     - entri ber-query (?tab=...) tidak dibedakan, jadi semua tab nyala bareng;
     - dua menu yang menunjuk path sama keduanya nyala.

   Perbaikan: Layout.jsx memakai <Link> biasa dan menghitung SATU indeks aktif
   sendiri (path sama persis + tab cocok). Berkas ini mengunci perbaikan itu
   secara struktural supaya tidak balik ke NavLink prefix-matching. */

const here=dirname(fileURLToPath(import.meta.url));
const layout=readFileSync(join(here,'..','src','components','Layout.jsx'),'utf8');

test('Layout tidak lagi memakai NavLink (penyebab prefix-match multi-aktif)', () => {
  assert.ok(!/import[^;]*\bNavLink\b/.test(layout),
    'NavLink masih diimpor — ia menambahkan kelas active via prefix-match');
  assert.ok(!/<NavLink\b/.test(layout),
    'Masih ada <NavLink> — ganti dengan <Link> + kelas aktif manual');
});

test('Layout memakai Link dan useLocation untuk hitung menu aktif', () => {
  assert.match(layout, /import[^;]*\bLink\b[^;]*from ['"]react-router-dom['"]/,
    'Link harus diimpor dari react-router-dom');
  assert.match(layout, /useLocation/,
    'useLocation dipakai untuk membaca pathname+search (tab)');
  assert.match(layout, /normPath/, 'harus ada normalisasi path');
});

test('logika aktif mencocokkan path sama persis, bukan berawalan', () => {
  // Tidak boleh ada perbandingan prefix seperti startsWith(path)
  assert.ok(!/startsWith\(/.test(layout),
    'Tidak boleh mencocokkan menu dengan startsWith (prefix-match)');
  assert.match(layout, /normPath\(p\)!==cur/, 'harus pakai perbandingan !== (eksak)');
});

test('entri dengan ?tab= dibedakan lewat parameter tab', () => {
  assert.match(layout, /get\(['"]tab['"]\)/, 'harus membaca parameter tab dari query');
  assert.match(layout, /tab!==null&&tab!==curTab/, 'tab menu harus cocok dengan tab URL');
});

test('kelas aktif dihitung dari satu indeks (satu menu satu klik)', () => {
  assert.match(layout, /i===navActive\?'active':''/, 'nav memakai indeks tunggal navActive');
  assert.match(layout, /i===footActive\?'active':''/, 'footer memakai indeks tunggal footActive');
});
