"""FORMIQ TZ4/A: deterministic, fail-closed FOOD ingredient conflict filter.

Allergen names alone are NOT evidence of a product's composition.
Only verified and recent manufacturer/provider ingredient statements, trusted by
server-side code, may pass the automatic-selection gate. Neither AI nor the
Mini App can set the trusted flag via an API request.
"""
import re
from datetime import datetime, timezone, timedelta
from unicodedata import normalize

CATALOG_VERSION = 'food-allergen-v1-2026-10-26'
MAX_EVIDENCE_AGE = timedelta(days=30)

# Auditable, deliberately conservative aliases; not a clinical exhaustive list.
# Terms refer to food allergens / confirmed protein derivatives, not product categories.
ALIASES = {
    'egg': (
        'яйцо','яйца','яиц','яйц','яйцу','яйцом','яйцами','яйцах',
        'яичный','яичная','яичные','яичного','яичной','яичным',
        'яичными','яичную','яичное','яичном','яичному','яичных',
        'желток','желтки','белок яйца','яичный белок','яичный порошок',
        'альбумин яйца','яичный альбумин',
        'овальбумин','овальбумина','овальбумином',
        'овомукоид','овомукоида','овомукоидом',
        'лизоцим e1105','лизоцим e 1105','e1105','e 1105','egg','eggs','egg white',
        'egg yolk','egg powder','ovalbumin','ovomucoid','egg albumin',
        'lysozyme e1105','quail egg','перепелиные яйца',
        'перепелиное яйцо','перепелиных яиц','куриных яиц'),
    'peanut': ('арахис','арахисовый','арахисовая','peanut','groundnut'),
    'milk': ('молоко','молочный белок','казеин','казеинат','сыворотка молочная',
             'whey protein','milk','casein','caseinate','lactalbumin'),
    'soy': ('соя','соевый','соевое','соевый белок','soy','soya','soy protein'),
    'wheat': ('пшеница','пшеничный','пшеничная','wheat','gluten wheat'),
    'fish': ('рыба','рыбный белок','fish','fish protein'),
    'crustacean': ('креветка','краб','омар','креветки','shrimp','prawn','crab','lobster'),
    'sesame': ('кунжут','тахини','sesame','tahini'),
    'tree_nut': ('миндаль','фундук','грецкий орех','кешью','фисташка',
                 'almond','hazelnut','walnut','cashew','pistachio'),
}
DISPLAY = {
 'egg':'Яйца','peanut':'Арахис','milk':'Молоко','soy':'Соя',
 'wheat':'Пшеница','fish':'Рыба','crustacean':'Ракообразные',
 'sesame':'Кунжут','tree_nut':'Орехи',
}
SOURCE_TYPES = frozenset(('manufacturer','licensed_provider','verified_internal'))


def _plain(value):
    if not isinstance(value,str):
        return ''
    return ' '.join(normalize('NFKC',value).casefold().replace('ё','е').split())


def _has_alias(value, alias):
    text=_plain(value)
    target=_plain(alias)
    # Unicode-aware boundaries, no partial substring matches.
    return bool(target and re.search(r'(?<!\w)'+re.escape(target)+r'(?!\w)',text))


def canonical_food(raw):
    """Known canonical group or exact everyday alias; unknown cannot be assumed safe."""
    val=_plain(raw)
    if val in ALIASES:
        return val
    for key,terms in ALIASES.items():
        if any(val==_plain(t) for t in terms):
            return key
    return None


def normalise_restrictions(rows):
    if not isinstance(rows,list) or len(rows)>30:
        raise ValueError('Укажи не более 30 пищевых ограничений')
    result=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'name','kind'}:
            raise ValueError('Проверь название и тип пищевого ограничения')
        name=row.get('name')
        kind=row.get('kind')
        if not isinstance(name,str) or not 1<=len(name.strip())<=70 or any(x in name for x in '<>\r\n'):
            raise ValueError('Название продукта должно содержать от 1 до 70 символов')
        if kind not in ('allergy','intolerance'):
            raise ValueError('Выбери тип: аллергия или непереносимость')
        clean=' '.join(name.split())
        canonical=canonical_food(clean)
        duplicate=canonical or _plain(clean)
        if any((x['canonical'] or _plain(x['name']))==duplicate for x in result):
            raise ValueError('Одно и то же ограничение указано несколько раз')
        result.append({'name':clean,'kind':kind,'canonical':canonical})
    if not result:
        raise ValueError('Укажи хотя бы один продукт')
    return result


def _verified(ingredients):
    if not isinstance(ingredients,dict):
        return False
    if ingredients.get('source_type') not in SOURCE_TYPES:
        return False
    if not isinstance(ingredients.get('source_id'),str) or not ingredients['source_id'].strip():
        return False
    raw=ingredients.get('verified_at')
    if not isinstance(raw,str):
        return False
    try:
        stamp=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if stamp.tzinfo is None:
            return False
        age=datetime.now(timezone.utc)-stamp.astimezone(timezone.utc)
        return timedelta(0)<=age<=MAX_EVIDENCE_AGE
    except ValueError:
        return False


def evaluate_composition(candidate, restrictions, *, trusted_server_source=False):
    """Returns (excluded | needs_review | no_conflicts_detected), never 'safe'.

    Caller-supplied verified flags, AI assertions or an 'egg-free' product name
    never certify source integrity. The trusted argument is server-only.
    """
    if not restrictions:
        return {'status':'needs_review','reason':'Нет подтверждённых пищевых ограничений'}
    if not isinstance(candidate,dict):
        return {'status':'needs_review','reason':'Неизвестный состав продукта'}
    evidence=candidate.get('composition')
    if not isinstance(evidence,dict):
        return {'status':'needs_review','reason':'Неизвестный состав продукта'}
    ingredient_list=evidence.get('ingredients')
    trace_list=evidence.get('may_contain')
    items=ingredient_list if isinstance(ingredient_list,list) else []
    traces=trace_list if isinstance(trace_list,list) else []
    # First detect every known contraindication, even if other parts of the
    # package statement are missing or a different allergy lacks mapping.
    incomplete_restrictions=False
    for restriction in restrictions:
        words=(ALIASES.get(restriction.get('canonical'))
               if isinstance(restriction,dict) else None)
        if not words:
            incomplete_restrictions=True
            continue
        for ingredient in items:
            if any(_has_alias(ingredient,word) for word in words):
                return {'status':'excluded','reason':'В составе найден запрещённый аллерген или производный компонент'}
        for warning in traces:
            if any(_has_alias(warning,word) for word in words):
                return {'status':'excluded','reason':'Указано предупреждение о возможных следах аллергена'}
    if incomplete_restrictions:
        return {'status':'needs_review','reason':'Не все пищевые ограничения распознаны справочником'}
    if not isinstance(ingredient_list,list) or not isinstance(trace_list,list):
        return {'status':'needs_review','reason':'Состав или предупреждения изготовителя неполные'}
    if not items or any(not isinstance(i,str) or not i.strip() for i in items+traces):
        return {'status':'needs_review','reason':'Некоторые ингредиенты или предупреждения неизвестны'}
    if not evidence.get('complete'):
        return {'status':'needs_review','reason':'Состав или предупреждения изготовителя неполные'}
    # Placeholder, unclear or omitted ingredient origins are not independent
    # evidence of absence. A provider claim of complete=True cannot override it.
    incomplete_markers=('неизвестно','неизвестный','не указан','неизвестного',
        'прочие компоненты','компоненты неизвестны','?','unknown',
        'not specified','unspecified','other ingredients')
    if any(_has_alias(ingredient,marker) for ingredient in items
           for marker in incomplete_markers):
        return {'status':'needs_review','reason':'Состав содержит неопределённые компоненты'}
    if not trusted_server_source or not _verified(evidence):
        return {'status':'needs_review','reason':'Состав не подтверждён проверенным актуальным источником'}
    # Unknown manufacturer cross-contact information is not a green state.
    if evidence.get('cross_contact_unknown',True) is not False:
        return {'status':'needs_review','reason':'Нельзя исключить перекрёстный контакт'}
    # Compound ingredients without unfolded recipe, and origin-ambiguous
    # additives, cannot be cleared on a simplistic word match.
    uncertain=('майонез','соус','выпечка','булочка','хлеб','макароны',
               'паста','панировка','начинка','крем','лецитин','эмульгатор',
               'mayonnaise','sauce','noodle','bread','lecithin','emulsifier',
               'альбумин','albumin','protein isolate','лизоцим','lysozyme',
               'растительное масло','растительный белок','растительные жиры',
               'vegetable oil','vegetable protein','ароматизатор','ароматизаторы',
               'natural flavouring','natural flavor','специи','смесь специй',
               'seasoning mix','food additive')
    if any(_has_alias(ingredient,alias) for ingredient in items for alias in uncertain):
        return {'status':'needs_review','reason':'Не раскрыт полный состав составного или неоднозначного компонента'}
    return {'status':'no_conflicts_detected',
            'reason':'В проверенном составе известных противоречий не обнаружено'}


def select_automatic_candidates(candidates, restrictions, *, trusted_server_source=False):
    """Recheck EACH ingredient and composite recipe; only green results survive."""
    accepted=[]
    for candidate in candidates:
        result=evaluate_composition(candidate,restrictions,
                                    trusted_server_source=trusted_server_source)
        if result['status']=='no_conflicts_detected':
            accepted.append(candidate)
    return accepted
