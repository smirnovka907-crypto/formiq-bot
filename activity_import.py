"""Strict CSV activity reports: no provider login, AI, or stored original files.

Supported columns: date,activity,minutes,kcal; values are USER-REPORTED
device activity calories, never total daily energy or a MET measurement.
"""
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MAX_ACTIVITY_CSV_BYTES = 65536
MAX_ACTIVITY_ROWS = 30
ALLOWED_ACTIVITY_HEADERS = ('date', 'activity', 'minutes', 'kcal')


def _normalize(row, zone):
    if not isinstance(row, dict) or set(row) != set(ALLOWED_ACTIVITY_HEADERS):
        raise ValueError('Некорректные поля отчёта активности')
    day = row['date']
    activity = row['activity']
    minutes, kcal = row['minutes'], row['kcal']
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('Дата должна иметь вид ГГГГ-ММ-ДД')
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise ValueError('Несуществующая дата в отчёте') from None
    if parsed.year < 2000 or parsed > datetime.now(ZoneInfo(zone)).date():
        raise ValueError('Дата активности должна быть не позднее сегодняшней')
    if (not isinstance(activity, str) or not 3 <= len(activity.strip()) <= 100
            or re.search(r'[\x00-\x1f\x7f]', activity)
            or activity.lstrip()[0] in '=+-@'):
        raise ValueError('Проверь название активности (3–100 символов)')
    activity = ' '.join(activity.split())
    for value, label, lower, upper in ((minutes, 'минуты', 1, 300),
                                        (kcal, 'ккал', 0, 5000)):
        if isinstance(value, bool) or not (
            (type(value) is int) or
            (isinstance(value, str) and re.fullmatch(r'\d{1,5}', value))):
            raise ValueError('Проверь ' + label + ': целое число')
        if not lower <= int(value) <= upper:
            raise ValueError('Проверь ' + label + ': вне диапазона')
    utc_at = datetime(parsed.year, parsed.month, parsed.day, 12,
                      tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
    normalized = dict(date=parsed.isoformat(), activity=activity,
                      minutes=int(minutes), kcal=int(kcal))
    # Same normalized session in different CSV files must not re-import.
    fingerprint = hashlib.sha256(json.dumps(normalized,
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {**normalized, 'performed_at': utc_at, 'fingerprint': fingerprint}



def _distinguish_same_value_sessions(rows):
    """Preserve separate identical rows *within the same CSV*.

    First occurrence keeps its previous fingerprint for compatibility with
    previously imported rows. Further occurrences use deterministic occurrence
    keys so a network retry is idempotent, but the second physical workout is
    not silently discarded as the first. CSV without timestamps or provider
    activity IDs cannot distinguish two identical sessions across different
    files; do not claim cross-file identity has been proven.
    """
    seen = {}
    result = []
    for row in rows:
        base = row['fingerprint']
        count = seen.get(base, 0) + 1
        seen[base] = count
        if count == 1:
            result.append(row)
        else:
            unique = hashlib.sha256(
                f'formiq-csv-occurrence-v2:{base}:{count}'.encode('ascii')
            ).hexdigest()
            result.append({**row, 'fingerprint': unique})
    return result



def parse_activity_csv(data, filename, mimetype, zone):
    if (not isinstance(filename, str) or
            not filename.casefold().endswith('.csv') or
            len(filename) > 160):
        raise ValueError('Поддерживается только отчёт .csv')
    if mimetype not in ('text/csv', 'text/plain', 'application/vnd.ms-excel',
                        'application/octet-stream', ''):
        raise ValueError('Недопустимый тип файла; нужен CSV')
    if not data or len(data) > MAX_ACTIVITY_CSV_BYTES:
        raise ValueError('Размер CSV должен быть от 1 байта до 64 КБ')
    if b'\x00' in data or data.startswith((b'PK\x03\x04', b'%PDF', b'\x1f\x8b')):
        raise ValueError('Это не текстовый CSV-отчёт')
    try:
        content = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Отчёт должен быть в UTF-8') from None
    if '\r' in content and '\r\n' not in content:
        raise ValueError('Недопустимые переносы строк')
    first = content.splitlines()[0] if content.splitlines() else ''
    delimiter = ';' if first.count(';') > first.count(',') else ','
    try:
        reader = csv.reader(io.StringIO(content, newline=''), delimiter=delimiter,
                            strict=True)
        headers = next(reader, [])
        if [h.strip().casefold() for h in headers] != list(ALLOWED_ACTIVITY_HEADERS):
            raise ValueError('Колонки CSV: date,activity,minutes,kcal (в указанном порядке)')
        records = []
        for raw in reader:
            if not any(cell.strip() for cell in raw):
                continue
            if len(raw) != 4:
                raise ValueError('Каждая строка CSV должна иметь четыре колонки')
            records.append(_normalize(dict(zip(ALLOWED_ACTIVITY_HEADERS, raw)), zone))
            if len(records) > MAX_ACTIVITY_ROWS:
                raise ValueError('Максимум 30 активностей в одном отчёте')
    except csv.Error:
        raise ValueError('Некорректный CSV') from None
    if not records:
        raise ValueError('В CSV нет активностей')
    return _distinguish_same_value_sessions(records)


def corrected_activity_rows(original, edited_rows, zone):
    if (not isinstance(edited_rows, list) or len(edited_rows) != len(original)
            or len(edited_rows) > MAX_ACTIVITY_ROWS):
        raise ValueError('Обнови предпросмотр отчёта')
    # Every row must still correspond to a row in the selected file; the
    # user can correct activity/date/duration/calories BEFORE confirmation.
    return _distinguish_same_value_sessions(
        [_normalize(row, zone) for row in edited_rows])
