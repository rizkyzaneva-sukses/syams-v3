/* Daftar mata uang resmi yang dipakai BOS SYAMS (permintaan Bos 16 Okt 2026).
   Dipusatkan di sini supaya form PO, Quotation, dsb. memakai pilihan yang sama
   dan tidak ada lagi input bebas yang bisa salah ketik. */
export const CURRENCIES = ['IDR', 'EUR', 'USD', 'AUSD', 'MYR', 'SGD'];
export const DEFAULT_CURRENCY = 'IDR';

/* Opsi untuk <select>: kalau baris lama menyimpan kode di luar daftar resmi
   (mis. data lama 'CNY'), kode itu tetap ditampilkan paling atas supaya tidak
   diam-diam berubah saat disimpan. */
export function currencyOptions(current) {
  const value = (current || '').toUpperCase();
  if (value && !CURRENCIES.includes(value)) return [value, ...CURRENCIES];
  return CURRENCIES;
}
