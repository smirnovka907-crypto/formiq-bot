"""Private, local PostgreSQL 18 production backup tool for FORMIQ.

Do NOT run on Render, GitHub Actions, or a shared/public computer. It has no
application/webhook access. Never logs DSNs, passwords, database rows or TOC.

Prerequisites: PostgreSQL 18 client utilities, cryptography (see
requirements-backup.txt). Source is only read via pg_dump. No paid services.
"""
import argparse
import getpass
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

MAGIC = b'FORMIQPG18ENC1'
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


class BackupError(Exception):
    """Messages contain NO credentials or personal data."""


def postgres_env(url, *, restore=False):
    """Never pass a secret-bearing PostgreSQL URL on a command line."""
    try:
        parsed = urlsplit(url)
        name = unquote(parsed.path.lstrip('/'))
        host = parsed.hostname or ''
        user = unquote(parsed.username or '')
        password = unquote(parsed.password or '')
        port = parsed.port or 5432
    except (ValueError, TypeError):
        raise BackupError('Invalid private connection URL') from None
    if (parsed.scheme not in ('postgres', 'postgresql')
            or not host or not user or not password or not name
            or not 1 <= port <= 65535):
        raise BackupError('Invalid private connection URL')
    if restore:
        if host not in ('localhost', '127.0.0.1', '::1') or not name.endswith('_restore'):
            raise BackupError('Restore is allowed only to LOCAL *_restore databases')
        if name == 'formiq_db':
            raise BackupError('Production database cannot be a restore target')
    elif name != 'formiq_db' or not host.endswith('.render.com'):
        raise BackupError('Source must be the existing Render formiq_db')
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('PG') or key in ('DATABASE_URL', 'TELEGRAM_BOT_TOKEN',
                                            'YANDEX_API_KEY', 'YANDEX_FOLDER_ID'):
            env.pop(key, None)
    env.update(PGHOST=host, PGPORT=str(port), PGUSER=user,
               PGPASSWORD=password, PGDATABASE=name, PGCONNECT_TIMEOUT='12',
               PGSSLMODE='disable' if restore else 'require',
               PGOPTIONS='-c default_transaction_read_only=on' if not restore else '')
    return env


def check_client(executable):
    binary = shutil.which(executable)
    if not binary:
        raise BackupError('PostgreSQL 18 client utilities are required')
    result = subprocess.run([binary, '--version'], capture_output=True, timeout=10)
    # Do not echo stderr. A mismatched client can corrupt compatibility.
    if result.returncode or b'18.' not in result.stdout:
        raise BackupError('PostgreSQL client version 18 is required')
    return binary


def key_for(passphrase, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
        passphrase.encode('utf-8'))


def encrypt_stream(input_stream, output_stream, passphrase):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    salt, nonce = secrets.token_bytes(SALT_SIZE), secrets.token_bytes(NONCE_SIZE)
    key = key_for(passphrase, salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    output_stream.write(MAGIC + salt + nonce)
    amount = 0
    while True:
        chunk = input_stream.read(CHUNK)
        if not chunk:
            break
        amount += len(chunk)
        output_stream.write(encryptor.update(chunk))
    output_stream.write(encryptor.finalize())
    output_stream.write(encryptor.tag)
    return amount


def decrypt_stream(archive, output_stream, passphrase):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    size = archive.stat().st_size
    header_len = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if size < header_len + TAG_SIZE + 1:
        raise BackupError('Encrypted archive is incomplete')
    with archive.open('rb') as source:
        header = source.read(header_len)
        if header[:len(MAGIC)] != MAGIC:
            raise BackupError('Not a FORMIQ encrypted archive')
        salt = header[len(MAGIC):len(MAGIC) + SALT_SIZE]
        nonce = header[len(MAGIC) + SALT_SIZE:]
        source.seek(-TAG_SIZE, 2)
        tag = source.read(TAG_SIZE)
        source.seek(header_len)
        decryptor = Cipher(algorithms.AES(key_for(passphrase, salt)),
                           modes.GCM(nonce, tag)).decryptor()
        remaining = size - header_len - TAG_SIZE
        while remaining:
            chunk = source.read(min(CHUNK, remaining))
            if not chunk:
                raise BackupError('Encrypted archive truncated')
            remaining -= len(chunk)
            output_stream.write(decryptor.update(chunk))
        decryptor.finalize()  # Raises InvalidTag on wrong password or tampering.


def validate_archive(archive, passphrase):
    """Authenticate encrypted data and parse PostgreSQL TOC, with no plaintext file."""
    binary = check_client('pg_restore')
    p = subprocess.Popen([binary, '--list'], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    class ListOnlySink:
        # pg_restore --list may finish after reading only the archive TOC.
        # Still decrypt ALL encrypted data to authenticate its GCM tag.
        def write(self, part):
            if p.stdin and not p.stdin.closed:
                try:
                    p.stdin.write(part)
                except BrokenPipeError:
                    pass

    try:
        decrypt_stream(archive, ListOnlySink(), passphrase)
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass
        if p.wait(timeout=90) != 0:
            raise BackupError('PostgreSQL archive listing failed')
    except Exception:
        if p.stdin and not p.stdin.closed:
            try:
                p.stdin.close()
            except BrokenPipeError:
                pass
        if p.poll() is None:
            p.kill()
        p.wait()
        raise


def private_directory(location):
    path = Path(location).expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise BackupError('Backup must be outside the GitHub project')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'posix':
        os.chmod(path, 0o700)
    return path


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for part in iter(lambda: file.read(CHUNK), b''):
            digest.update(part)
    return digest.hexdigest()


def ask_passphrase(confirm=False):
    value = getpass.getpass('Private backup passphrase (not visible): ')
    if len(value) < 20:
        raise BackupError('Passphrase must be at least 20 characters')
    if confirm and getpass.getpass('Repeat private passphrase: ') != value:
        raise BackupError('Passphrases do not match')
    return value


def create_backup(destination, url, passphrase):
    binary = check_client('pg_dump')
    restorer = check_client('pg_restore')
    del restorer
    env = postgres_env(url)
    directory = private_directory(destination)
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = 'formiq-production-' + tag + '-' + secrets.token_hex(4) + '.fiqenc'
    final, partial = directory / name, directory / (name + '.partial')
    process = None
    try:
        with partial.open('xb') as output:
            if os.name == 'posix':
                os.chmod(partial, 0o600)
            process = subprocess.Popen(
                [binary, '--format=custom', '--no-owner', '--no-acl'],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            try:
                amount = encrypt_stream(process.stdout, output, passphrase)
            finally:
                process.stdout.close()
            if process.wait(timeout=120) != 0 or amount < 8:
                raise BackupError('pg_dump failed; encrypted partial file discarded')
            output.flush()
            os.fsync(output.fileno())
        # Never declare backup successful without authenticated decrypt + TOC.
        validate_archive(partial, passphrase)
        partial.replace(final)
        return final, checksum(final)
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()
        if partial.exists():
            partial.unlink()


def restore_locally(archive, passphrase, target_url):
    """Restore only to a pre-created EMPTY database on localhost."""
    validate_archive(archive, passphrase)
    env = postgres_env(target_url, restore=True)
    psql = check_client('psql')
    binary = check_client('pg_restore')
    query = ("SELECT (current_setting('server_version_num')::integer / 10000 = 18) "
             "AND (SELECT COUNT(*) FROM pg_catalog.pg_class "
             "WHERE relnamespace = 'public'::regnamespace "
             "AND relkind IN ('r','p','v','m','S')) = 0")
    test = subprocess.run([psql, '-X', '-A', '-t', '-c', query], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    if test.returncode or test.stdout.strip() != b't':
        raise BackupError('Restore target must be an empty local PostgreSQL 18 database')
    proc = subprocess.Popen([binary, '--no-owner', '--no-acl',
                             '--exit-on-error', '--single-transaction',
                             '--dbname', env['PGDATABASE']],
                            env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        decrypt_stream(archive, proc.stdin, passphrase)
        proc.stdin.close()
        if proc.wait(timeout=900) != 0:
            raise BackupError('Isolated restore failed; inspect locally, not in chat')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='FORMIQ encrypted local PG18 backups')
    sub = parser.add_subparsers(dest='action', required=True)
    mk = sub.add_parser('backup')
    mk.add_argument('--directory', default='~/FORMIQ-private-backups')
    for verb in ('verify', 'restore'):
        opt = sub.add_parser(verb)
        opt.add_argument('file', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'backup':
            url = getpass.getpass('Render PostgreSQL EXTERNAL URL (hidden): ')
            secret = ask_passphrase(confirm=True)
            file, digest = create_backup(args.directory, url, secret)
            print('ENCRYPTED_BACKUP_CREATED_AND_FORMAT_CHECKED')
            print('Location:', file)
            print('SHA256 encrypted archive:', digest)
            print('Keep the passphrase in a separate password manager.')
            print('Copy encrypted file to private off-device storage.')
        else:
            archive = args.file.expanduser().resolve(strict=True)
            secret = ask_passphrase()
            if args.action == 'verify':
                validate_archive(archive, secret)
                print('ENCRYPTED_ARCHIVE_AUTHENTICATED_AND_TOC_OK')
                print('SHA256 encrypted archive:', checksum(archive))
            else:
                target = getpass.getpass('LOCAL empty *_restore PostgreSQL URL (hidden): ')
                restore_locally(archive, secret, target)
                print('LOCAL_ISOLATED_PG18_RESTORE_COMPLETED; run data checks')
        return 0
    except Exception:
        # Library and DB errors can contain credentials. Never reveal them here.
        print('BLOCKED: backup/verification/restore failed; NO production release',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
