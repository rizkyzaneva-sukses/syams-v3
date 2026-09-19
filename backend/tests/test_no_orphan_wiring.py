"""Kunci anti-orphan: tidak boleh ada router/halaman yang kodenya ada tapi tak terpasang.

Temuan nyata di batch 2: 4 router (`ceo_override`, `ceo_performance`,
`cfo_payments`, `coo_handoffs`) dan 2 halaman (`CEOCompanyPerformance`,
`CEOOverride`) sudah ditulis + ada tesnya, tetapi tidak pernah didaftarkan —
sehingga 85 endpoint mengembalikan 404 dan 2 halaman tidak bisa dibuka.

Tes ini membandingkan apa yang ADA di disk dengan apa yang terdaftar, supaya
"lupa mendaftarkan" tidak bisa lagi lolos sebagai "selesai".
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # /tmp/final-syam
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# Router yang TIDAK boleh dipasang lewat `main.py` karena memang bukan bagian API
# (modul bantu). Daftar ini harus tetap kosong-kosong saja bila memungkinkan.
ALLOWED_UNREGISTERED: set[str] = set()


# Halaman di disk yang memang BUKAN rute sendiri. Tiap entri harus punya alasan.
# Ditemukan oleh tes ini sendiri saat pertama dijalankan.
KNOWN_DEAD_PAGES = {
    # Tidak dirujuk dari mana pun: sisa placeholder awal, bukan revisi batch 2.
    # Bukan bagian 20 revisi; dibiarkan apa adanya supaya tidak menghapus kerja
    # orang tanpa keputusan. Kalau nanti dipakai, entri ini harus dihapus.
    "ModuleDashboard",
    "OrderCreate",
    # `Workspace` adalah template rute dinamis (dipakai lewat /:name), bukan
    # halaman statis yang di-`import` di main.jsx.
    "Workspace",
}


def _disk_routers():
    folder = BACKEND / "app" / "routers"
    return {p.stem for p in folder.glob("*.py")
            if not p.stem.startswith("__")} - {"__init__"}


def _registered_routers():
    import re
    src = (BACKEND / "app" / "main.py").read_text()
    registered = set(re.findall(r"([a-z_][a-z0-9_]*)\.router", src))
    m = re.search(r"from \.routers import \(([^)]*)\)", src, re.S)
    if m:
        registered |= {n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()}
    return registered


def test_every_router_file_is_registered_in_main():
    """Router di disk WAJIB terdaftar, kalau tidak endpoint-nya 404 tanpa jejak."""
    orphan = _disk_routers() - _registered_routers() - ALLOWED_UNREGISTERED
    assert not orphan, (
        f"router ada di disk tapi tidak terdaftar di main.py: {sorted(orphan)} — "
        "semua endpoint-nya akan 404"
    )


def test_every_page_file_is_reachable_from_main_jsx():
    """Halaman di disk harus dirujuk main.jsx, kalau tidak user tidak bisa buka."""
    folder = FRONTEND / "src" / "pages"
    pages = {p.stem for p in folder.glob("*.jsx")}
    src = (FRONTEND / "src" / "main.jsx").read_text()
    missing = {name for name in pages
               if name not in KNOWN_DEAD_PAGES and name not in src}
    assert not missing, (
        f"halaman ada di disk tapi tidak dirujuk main.jsx: {sorted(missing)}"
    )


def test_known_dead_pages_are_still_dead():
    """Kalau halaman 'mati' mulai dipakai, entri pengecualian harus dibersihkan."""
    src = (FRONTEND / "src" / "main.jsx").read_text()
    resurrected = {name for name in KNOWN_DEAD_PAGES if name in src}
    assert not resurrected, (
        f"halaman ini sudah dipakai lagi, hapus dari KNOWN_DEAD_PAGES: {sorted(resurrected)}"
    )


def test_newly_registered_routers_are_reachable_in_openapi():
    """Bukti langsung: endpoint router yang tadinya orphan benar-benar terdaftar."""
    import os
    import sys
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("APP_ENV", "testing")
    os.environ.setdefault("SECRET_KEY", "isolated-tests-only-42e77368071baf60a39e476b196052bd")
    os.environ.setdefault("SEED_DEMO", "false")
    sys.path.insert(0, str(BACKEND))

    from app.main import app  # noqa: E402
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/ceo/company-performance",   # ceo_performance (revisi #70-#78)
        "/api/ceo/overrides",             # ceo_override (revisi #74)
        "/api/cfo/payments-queue",        # cfo_payments (revisi #17/#20)
        "/api/coo/handoffs",              # coo_handoffs (revisi #54)
    }
    missing = expected - paths
    assert not missing, f"endpoint router yang seharusnya hidup masih hilang: {sorted(missing)}"


def test_frontend_routes_for_ceo_pages_exist():
    """Halaman CEO yang baru dipasang harus punya rute + hak akses.

    Pencocokan sengaja TIDAK bergantung jenis tanda kutip: file ini memakai
    campuran `'` (0x27) dan `’` (U+2019), jadi memeriksa literal berkutip
    membuat tes gagal padahal entri-nya ada.
    """
    main_src = (FRONTEND / "src" / "main.jsx").read_text()
    business_src = (FRONTEND / "src" / "business.js").read_text()
    for route in ("ceo/company-performance", "ceo/overrides"):
        assert f'path="{route}"' in main_src, f"rute {route} belum terpasang"
        # Cukup path + nilai perannya, tanpa peduli jenis kutip.
        assert route in business_src, f"hak akses {route} belum terdaftar"
        idx = business_src.find(route)
        sekitar = business_src[idx:idx + len(route) + 20]
        assert "'CEO'" in sekitar or "\u2019CEO\u2019" in sekitar or '"CEO"' in sekitar, \
            f"peran CEO belum terdaftar untuk {route}: {sekitar!r}"
    # Sidebar CEO harus menunjuk halaman yang benar, bukan halaman lain.
    layout_src = (FRONTEND / "src" / "components" / "Layout.jsx").read_text()
    assert "/ceo/company-performance" in layout_src, "Company Performance belum masuk sidebar"
    assert "/ceo/overrides" in layout_src, "Override Register belum masuk sidebar"
