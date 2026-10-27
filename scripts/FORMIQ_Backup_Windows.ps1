# FORMIQ private Windows launcher. No real secrets are stored or echoed.
# Requires a trusted owner's PC, Windows PowerShell 5.1+, Python 3.12+
# and PostgreSQL 18 client (the restore also needs a LOCAL PG18 server).
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Find-Python {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return @{Exe=$py.Source; Prefix=@('-3')} }
    }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -c 'import sys;sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return @{Exe=$py.Source; Prefix=@()} }
    }
    throw 'Python 3.12+ is required. Install from python.org and rerun.'
}

function Find-Postgres18 {
    $bin = Join-Path $env:ProgramFiles 'PostgreSQL\18\bin'
    if (Test-Path (Join-Path $bin 'pg_dump.exe')) {
        $env:PATH = $bin + [IO.Path]::PathSeparator + $env:PATH
    }
    foreach ($name in @('pg_dump','pg_restore','psql','createdb')) {
        $binary = Get-Command ($name + '.exe') -ErrorAction SilentlyContinue
        if (-not $binary) { throw ('PostgreSQL 18 client missing: ' + $name) }
        $version = (& $binary.Source --version | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $version -notmatch '\(PostgreSQL\)\s+18\.') {
            throw ('PostgreSQL 18 client required for: ' + $name)
        }
    }
}

function Ensure-No-Stored-Secrets {
    foreach ($name in @('DATABASE_URL','TELEGRAM_BOT_TOKEN',
                        'YANDEX_API_KEY','PGPASSWORD','PGPASSFILE')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not [string]::IsNullOrEmpty($value)) {
            throw 'Refusing inherited app/database passwords in environment. Clear them locally first.'
        }
    }
}

function Run-Python([string[]]$Arguments) {
    & $global:PY.Exe @($global:PY.Prefix) @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Operation failed safely. No successful backup/restore is claimed.' }
}

function Select-EncryptedFile {
    $directory = Join-Path $HOME 'FORMIQ-private-backups'
    if (-not (Test-Path $directory)) {
        throw 'No private backup folder yet. Choose option 2 first.'
    }
    $latest = Get-ChildItem -LiteralPath $directory -Filter '*.fiqenc' -File |
              Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $latest) { throw 'No encrypted .fiqenc file found.' }
    Write-Host ('Newest encrypted file: ' + $latest.Name)
    $answer = Read-Host 'Press ENTER for newest file, or type full path to another .fiqenc'
    if ([string]::IsNullOrWhiteSpace($answer)) { return $latest.FullName }
    $candidate = (Resolve-Path -LiteralPath $answer -ErrorAction Stop).Path
    if ([IO.Path]::GetExtension($candidate) -ne '.fiqenc' -or
        -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw 'Selected file must exist and end in .fiqenc'
    }
    return $candidate
}

try {
    Ensure-No-Stored-Secrets
    $global:PY = Find-Python
    Find-Postgres18
    Write-Host 'FORMIQ PRIVATE BACKUP - all prerequisites detected.'
    Write-Host '1 - Check tools (no network or database access)'
    Write-Host '2 - Create encrypted production backup and verify the archive'
    Write-Host '3 - Verify an existing encrypted backup'
    Write-Host '4 - Restore to a NEW empty local formiq_restore and compare with Render'
    Write-Host '5 - Install/upgrade the local cryptography dependency'
    Write-Host '6 - Print SHA256 of an encrypted .fiqenc (also supports downloaded copy)'
    $choice = Read-Host 'Select 1-6'
    switch ($choice) {
        '1' { Write-Host 'TOOLS_OK: Python 3.12+, PostgreSQL client 18' }
        '2' {
            Run-Python @('scripts/formiq_pg_backup.py','backup')
            Write-Host 'NEXT: keep the passphrase separately, then choose option 4.'
        }
        '3' {
            $file = Select-EncryptedFile
            Run-Python @('scripts/formiq_pg_backup.py','verify',$file)
        }
        '4' {
            $file = Select-EncryptedFile
            Write-Host 'A NEW empty local PostgreSQL 18 database formiq_restore is required.'
            Write-Host 'Creating locally with user postgres. The client may prompt for your LOCAL password.'
            & createdb.exe --host=127.0.0.1 --port=5432 --username=postgres formiq_restore
            if ($LASTEXITCODE -ne 0) { throw 'Local database creation refused. Existing data was NOT overwritten.' }
            Run-Python @('scripts/formiq_pg_backup.py','restore',$file)
            Run-Python @('scripts/formiq_pg_restore_audit.py')
            Write-Host 'RESTORE_AND_AGGREGATE_AUDIT_PASSED. No production changes.'
        }
        '5' {
            Run-Python @('-m','pip','install','-r','requirements-backup.txt')
            Write-Host 'Local cryptography dependency installed.'
        }
        '6' {
            $file = Select-EncryptedFile
            $hash = Get-FileHash -LiteralPath $file -Algorithm SHA256
            Write-Host ('Encrypted archive SHA256: ' + $hash.Hash.ToLowerInvariant())
        }
        default { throw 'Invalid option. No operation performed.' }
    }
} catch {
    # Errors deliberately contain no DSNs, passwords or private database rows.
    Write-Host 'NO-GO: operation was not successfully completed. Review prerequisites.' -ForegroundColor Red
    exit 2
}
