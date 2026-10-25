"""Local, deterministic parser for genuine Fitdays/scale exports. No AI or remote calls."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


MAX_FILE_SIZE = 2_000_000
MAX_ROWS = 2500
NAMES = {
    'date': {'date','datetime','time','timestamp','datum','fecha','дата','датавремя','время','measuredat','measurementdate'},
    'weight': {'weight','weightkg','weightlbs','weightlb','вес','вескг','gewicht','gewichtkg','bodyweight','体重'},
    'fat': {'bodyfat','bodyfatpct','bodyfatpercentage','bodyfatrate','fat','жир','жирпроцент','жироваямасса','körperfett','lichaamsvet','体脂率'},
    'muscle': {'musclemass','musclemasskg','musclemasslbs','мышечнаямасса','мышцымасса','spiermassa','肌肉量'},
    'water': {'bodywater','bodywaterpct','water','вода','водаворганизме','watergewicht','hydration','体水分'},
    'visceral': {'visceralfat','висцеральныйжир','visceraalvet','内脏脂肪'},
    'bmr': {'bmr','bmrcalories','basalmetabolicrate','основнойобмен','базовыйобмен','基础代谢'},
    'bmi': {'bmi','имт','bodymassindex'},
}
def norm(raw):
    return re.sub(r'[^a-zа-яё0-9]', '', str(raw or '').casefold())

def as_number(raw, lo, hi, *, pounds=False):
    if raw is None or raw=='':
        return None
    if isinstance(raw,(int,float,Decimal)):
        value=Decimal(str(raw))
    else:
        text=str(raw).strip().replace('\u00a0','').replace(' ','').replace(',','.')
        match=re.search(r'[-+]?\d+(?:\.\d+)?',text)
        if not match or text in ('--','-'):
            return None
        try:value=Decimal(match.group(0))
        except InvalidOperation:return None
        pounds = pounds or 'lb' in text.lower() or 'фунт' in text.lower()
    if not value.is_finite():
        return None
    if pounds:value *= Decimal('0.45359237')
    if not lo <= value <= hi:
        return None
    return float(value.quantize(Decimal('0.01')))

def parse_time(raw, zone):
    if isinstance(raw,datetime):
        dt=raw
    elif isinstance(raw,date):
        dt=datetime.combine(raw,time(0))
    else:
        text=str(raw or '').strip()
        if not text:return None
        dt=None
        try:dt=datetime.fromisoformat(text.replace('Z','+00:00'))
        except ValueError:pass
        if dt is None:
            for fmt in ('%Y-%m-%d %H:%M:%S','%Y/%m/%d %H:%M:%S','%d.%m.%Y %H:%M:%S',
                        '%d.%m.%Y %H:%M','%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M',
                        '%H:%M %d/%m/%Y','%H:%M %d.%m.%Y','%H:%M %b.%d %Y',
                        '%H:%M %b.%d, %Y','%b.%d %Y %H:%M','%Y-%m-%d','%d.%m.%Y',
                        '%d/%m/%Y','%Y/%m/%d','%m/%d/%Y %H:%M'):
                try:dt=datetime.strptime(text,fmt);break
                except ValueError:pass
        if dt is None:return None
    if dt.tzinfo is None:dt=dt.replace(tzinfo=ZoneInfo(zone))
    dt=dt.astimezone(timezone.utc)
    if not datetime(2000,1,1,tzinfo=timezone.utc) <= dt <= datetime.now(timezone.utc)+timedelta(days=2):
        return None
    return dt.isoformat()

def read_grid(data,filename):
    if not data or len(data)>MAX_FILE_SIZE:
        raise ValueError('Файл должен быть не больше 2 МБ')
    if not str(filename).lower().endswith(('.csv','.xlsx','.xls')):
        raise ValueError('Поддерживаются только отчёты CSV, XLSX и XLS')
    if data.startswith(b'PK\x03\x04'):
        import openpyxl
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members=archive.infolist()
                if len(members)>250 or sum(x.file_size for x in members)>12_000_000:
                    raise ValueError('Отчёт Excel слишком большой')
            wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
            try:
                ws=wb.active
                return [[str(c) if c is not None else '' for c in line] for idx,line in enumerate(ws.iter_rows(values_only=True)) if idx<MAX_ROWS+50]
            finally:wb.close()
        except (zipfile.BadZipFile,KeyError,ValueError,TypeError,OSError) as exc:
            if isinstance(exc,ValueError):raise
            raise ValueError('Не удалось прочитать Excel-отчёт') from None
    if data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        import xlrd
        try:
            book=xlrd.open_workbook(file_contents=data,on_demand=True)
            sheet=book.sheet_by_index(0)
            return [[str(xlrd.xldate_as_datetime(c.value,book.datemode)) if c.ctype==xlrd.XL_CELL_DATE
                     else str(c.value) for c in sheet.row(i)]
                    for i in range(min(sheet.nrows,MAX_ROWS+50))]
        except (ValueError,IndexError,xlrd.XLRDError):
            raise ValueError('Не удалось прочитать XLS-отчёт') from None
    content=None
    for enc in ('utf-8-sig','utf-16','cp1251','cp1252'):
        try:
            content=data.decode(enc)
            if '\x00' in content:continue
            break
        except UnicodeError:continue
    if not content:
        raise ValueError('Файл не является текстовым CSV/Excel-отчётом')
    try:
        dialect=csv.Sniffer().sniff(content[:8192],delimiters=',;\t')
        rows=csv.reader(io.StringIO(content),dialect)
    except csv.Error:
        rows=csv.reader(io.StringIO(content),delimiter=',')
    return [row for i,row in enumerate(rows) if i<MAX_ROWS+50]

def parse_report(data,filename,user_zone):
    """Return validated server-authoritative, timezone-normalized weigh-ins."""
    try:ZoneInfo(user_zone)
    except (KeyError,TypeError,ValueError):raise ValueError('Неизвестный часовой пояс') from None
    grid=read_grid(data,filename)
    header_at=None;columns={}
    for idx,row in enumerate(grid[:35]):
        proposed={}
        for j,name in enumerate(row):
            key=norm(name)
            for field,aliases in NAMES.items():
                if key in aliases and field not in proposed:proposed[field]=j
        if 'date' in proposed and 'weight' in proposed:
            header_at=idx;columns=proposed;break
    if header_at is None:
        raise ValueError('Не найдены колонки даты и веса. Выгрузи историю Fitdays в CSV/XLSX/XLS')
    result=[];seen=set();invalid=0
    for raw in grid[header_at+1:]:
        if not any(str(x).strip() for x in raw):continue
        def val(name):
            position=columns.get(name)
            return raw[position] if position is not None and len(raw)>position else ''
        stamp=parse_time(val('date'),user_zone)
        weight_text=str(val('weight')).lower()
        weight=as_number(val('weight'),20,400,pounds='lb' in norm(grid[header_at][columns['weight']]) or 'фунт' in weight_text)
        if not stamp or weight is None:
            invalid+=1;continue
        if stamp in seen:
            invalid+=1;continue
        seen.add(stamp)
        fields={'measured_at':stamp,'weight_kg':weight}
        for field,lo,hi,output in (('fat',0,80,'body_fat_pct'),('muscle',0,250,'muscle_mass_kg'),
                                   ('water',0,90,'body_water_pct'),('visceral',0,100,'visceral_fat'),
                                   ('bmr',100,6000,'bmr_kcal'),('bmi',10,80,'bmi')):
            value=as_number(val(field),lo,hi,pounds=field=='muscle' and
                ('lb' in norm(grid[header_at][columns[field]]) if field in columns else False))
            if value is not None:fields[output]=value
        result.append(fields)
    if not result:
        raise ValueError('В отчёте нет корректных измерений веса и даты')
    result.sort(key=lambda row:row['measured_at'])
    return {'rows':result,'invalid':invalid,'source':'Fitdays/CSV Excel'}
