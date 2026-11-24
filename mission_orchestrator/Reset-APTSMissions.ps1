param(
    [string]$Root = 'D:\mission_orchestrator'
)

$ErrorActionPreference = 'Stop'
$db = Join-Path $Root 'data\mission_orchestrator.db'
$python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $db -PathType Leaf)) {
    throw "Database tidak ditemukan: $db"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if (-not $candidate) {
        throw 'Python tidak ditemukan. Pastikan virtual environment APTS tersedia.'
    }
    $python = $candidate.Source
}
if ($env:MISSION_DB_DRIVER -and $env:MISSION_DB_DRIVER.ToLowerInvariant() -ne 'sqlite') {
    throw "MISSION_DB_DRIVER bukan sqlite: $env:MISSION_DB_DRIVER"
}
if ($env:MISSION_SQLITE_PATH -and (
    [System.IO.Path]::GetFullPath($env:MISSION_SQLITE_PATH) -ne [System.IO.Path]::GetFullPath($db)
)) {
    throw "MISSION_SQLITE_PATH menunjuk database lain: $env:MISSION_SQLITE_PATH"
}

$listener = Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $pids = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Mission Orchestrator masih aktif pada port 8780 (PID $pids). Hentikan layanan dahulu."
}

Write-Host "Database: $db" -ForegroundColor Yellow
Write-Host 'Seluruh mission (termasuk event, task, plan, archive, dan audit lokal) akan dihapus.' -ForegroundColor Yellow
Write-Host 'Tabel/struktur skema dan registry subsystem tidak akan dihapus.'
$confirmation = Read-Host 'Ketik HAPUS SEMUA MISSION untuk melanjutkan'
if ($confirmation -cne 'HAPUS SEMUA MISSION') {
    Write-Host 'Dibatalkan. Tidak ada data diubah.'
    return
}

$pythonCode = @'
import datetime, os, sqlite3, sys

db_path = os.path.abspath(sys.argv[1])
con = sqlite3.connect(db_path, timeout=5)
con.execute('PRAGMA foreign_keys=ON')

def quote(name):
    return '"' + name.replace('"', '""') + '"'

try:
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    preserved = {'mission_repository_metadata', 'canonical_subsystems', 'subsystem_registry_snapshots', 'subsystem_capability_contracts'}
    targets = {name for name in names if name == 'global_missions' or (name.startswith('mission_') and name not in preserved)}
    if not {'global_missions', 'mission_states', 'mission_envelopes'}.issubset(targets):
        raise RuntimeError('Skema database bukan skema APTS Mission yang diharapkan. Tidak dihapus.')
    if (unexpected := names - preserved - targets):
        raise RuntimeError(f'Tabel lain belum diklasifikasikan: {sorted(unexpected)}')
    refs = {t: {r[2] for r in con.execute('PRAGMA foreign_key_list(' + quote(t) + ')')} for t in names}
    if incoming := {t: refs[t] & targets for t in names - targets if refs[t] & targets}:
        raise RuntimeError(f'Tabel yang dipertahankan masih mengacu pada mission: {incoming}')
    deps = {t: refs[t] & targets for t in targets}
    order = []
    while deps:
        referenced = set().union(*deps.values())
        ready = sorted(t for t in deps if t not in referenced)
        if not ready:
            raise RuntimeError('Siklus foreign key terdeteksi. Penghapusan dibatalkan.')
        order.extend(ready)
        for t in ready:
            del deps[t]
    if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Database awal tidak lolos integrity_check.')
    count_before = {t: con.execute('SELECT COUNT(*) FROM ' + quote(t)).fetchone()[0] for t in targets}
    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(backup_dir, f'mission_before_reset_{stamp}.db')
    bk = sqlite3.connect(backup_path)
    try:
        con.backup(bk)
        if bk.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup gagal integrity_check.')
    finally:
        bk.close()
    print('Backup:', backup_path)
    print('Sebelum:', count_before.get('global_missions', 0), 'mission;', sum(count_before.values()), 'baris pada', len(targets), 'tabel')
    con.execute('BEGIN IMMEDIATE')
    deleted = 0
    for t in order:
        deleted += con.execute('DELETE FROM ' + quote(t)).rowcount
    if con.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Foreign key check gagal; dibatalkan.')
    if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Integrity check gagal; dibatalkan.')
    if any(con.execute('SELECT COUNT(*) FROM ' + quote(t)).fetchone()[0] for t in targets):
        raise RuntimeError('Masih ada data mission; dibatalkan.')
    con.commit()
    print('SUKSES: Dihapus', deleted, 'baris dari', len(targets), 'tabel mission. Total mission sekarang 0.')
    print('Metadata dan registry subsystem tetap dipertahankan.')
except Exception:
    con.rollback()
    raise
finally:
    con.close()
'@
$pythonCode | & $python - $db
if ($LASTEXITCODE -ne 0) {
    throw "Reset gagal (exit code $LASTEXITCODE). Periksa pesan error; backup sudah dibuat jika proses mencapai langkah backup."
}
Write-Host 'Silakan jalankan ulang Mission Orchestrator dan refresh dashboard.' -ForegroundColor Green
