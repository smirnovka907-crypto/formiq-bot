"""FORMIQ / FatSecret: OAuth 1.0a access to an EXISTING user's diary.

No provider credentials are bundled. Importing this module cannot touch the network.
The calling application must persist OAuth tokens encrypted and associate them with
an authenticated FORMIQ user; this module deliberately does NOT store tokens.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, quote, urlencode
from urllib.request import Request, urlopen

REQUEST_TOKEN_URL = "https://authentication.fatsecret.com/oauth/request_token"
AUTHORIZE_URL = "https://authentication.fatsecret.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://authentication.fatsecret.com/oauth/access_token"
FOOD_ENTRIES_URL = "https://platform.fatsecret.com/rest/food-entries/v2"


def _pct(value: object) -> str:
    return quote(str(value), safe="~-._")


def signed_params(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    *,
    token: str = "",
    token_secret: str = "",
    extra: dict[str, str] | None = None,
    nonce: str | None = None,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Generate RFC 5849 OAuth 1.0a HMAC-SHA1 parameters (deterministic for tests)."""
    if method.upper() not in ("GET", "POST"):
        raise ValueError("Unsupported HTTP method")
    if not (url.startswith("https://") and consumer_key and consumer_secret):
        raise ValueError("Secure API URL and developer credentials required")
    params = {str(k): str(v) for k, v in (extra or {}).items()}
    if any(k.startswith("oauth_") for k in params):
        raise ValueError("OAuth parameters are not user-supplied")
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce if nonce is not None else secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_version": "1.0",
    }
    if token:
        oauth["oauth_token"] = token
    joined = {**params, **oauth}
    encoded = sorted((_pct(k), _pct(v)) for k, v in joined.items())
    normalized = "&".join(k + "=" + v for k, v in encoded)
    base = "&".join((_pct(method.upper()), _pct(url), _pct(normalized)))
    key = _pct(consumer_secret) + "&" + _pct(token_secret)
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode("ascii")
    return {**params, **oauth}


def _request(method: str, url: str, params: dict[str, str]) -> str:
    if method == "POST":
        req = Request(url, data=urlencode(params).encode("utf-8"), method="POST")
    elif method == "GET":
        req = Request(url + "?" + urlencode(params), method="GET")
    else:
        raise ValueError("Unsupported method")
    with urlopen(req, timeout=12) as response:
        raw = response.read(2_000_000)
    return raw.decode("utf-8")


@dataclass(frozen=True)
class FatSecretClient:
    consumer_key: str
    consumer_secret: str

    def request_token(self, callback_url: str) -> tuple[str, str]:
        if not callback_url.startswith("https://"):
            raise ValueError("HTTPS callback required")
        params = signed_params("POST", REQUEST_TOKEN_URL, self.consumer_key,
                               self.consumer_secret, extra={"oauth_callback": callback_url})
        result = dict(parse_qsl(_request("POST", REQUEST_TOKEN_URL, params)))
        if result.get("oauth_callback_confirmed") != "true":
            raise RuntimeError("FatSecret did not confirm OAuth callback")
        return result["oauth_token"], result["oauth_token_secret"]

    @staticmethod
    def authorize_url(request_token: str) -> str:
        return AUTHORIZE_URL + "?" + urlencode({"oauth_token": request_token})

    def access_token(self, request_token: str, request_secret: str,
                     verifier: str) -> tuple[str, str]:
        if not (request_token and request_secret and verifier):
            raise ValueError("Incomplete OAuth callback")
        params = signed_params(
            "GET", ACCESS_TOKEN_URL, self.consumer_key, self.consumer_secret,
            token=request_token, token_secret=request_secret,
            extra={"oauth_verifier": verifier},
        )
        result = dict(parse_qsl(_request("GET", ACCESS_TOKEN_URL, params)))
        return result["oauth_token"], result["oauth_token_secret"]

    def diary(self, access_token: str, access_secret: str, day: date) -> dict:
        """Read existing FatSecret profile, not generic nutrition catalog."""
        if not (access_token and access_secret):
            raise ValueError("User authorization is required")
        days_since_epoch = (day - date(1970, 1, 1)).days
        if days_since_epoch < 0:
            raise ValueError("Invalid date")
        params = signed_params(
            "GET", FOOD_ENTRIES_URL, self.consumer_key, self.consumer_secret,
            token=access_token, token_secret=access_secret,
            extra={"date": str(days_since_epoch), "format": "json"},
        )
        result = json.loads(_request("GET", FOOD_ENTRIES_URL, params))
        if not isinstance(result, dict):
            raise ValueError("Unexpected FatSecret payload")
        return result


def _number(value: object) -> Decimal | None:
    # Missing provider nutrition is unknown, NOT zero.
    if value is None or value == "":
        return None
    try:
        num = Decimal(str(value))
        if not num.is_finite() or num < 0:
            raise ValueError("Invalid nutrition number")
        return num
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid nutrition number") from exc


def normalize_diary(payload: dict) -> dict:
    """Normalized daily summary with stable entry IDs, zero entries supported."""
    if not isinstance(payload, dict) or payload.get("error") is not None:
        raise ValueError("FatSecret diary request failed")
    root = payload.get("food_entries") or {}
    if not isinstance(root, dict) or root.get("error") is not None:
        raise ValueError("Invalid FatSecret diary payload")
    entries = root.get("food_entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise ValueError("Invalid FatSecret entries")
    unique: dict[str, dict] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Invalid diary entry")
        key = str(item.get("food_entry_id", ""))
        if not key:
            raise ValueError("Missing entry id")
        unique[key] = {
            "source": "fatsecret", "external_id": key,
            "meal": str(item.get("meal", "")),
            "name": str(item.get("food_entry_name", ""))[:240],
            "calories_kcal": _number(item.get("calories")),
            "protein_g": _number(item.get("protein")),
            "fat_g": _number(item.get("fat")),
            "carbs_g": _number(item.get("carbohydrate")),
        }
    records = list(unique.values())
    # A missing nutrient prevents a fabricated complete total. An actually
    # empty diary day has no nutrient measurement, not an observed 0 kcal.
    fields = ("calories_kcal", "protein_g", "fat_g", "carbs_g")
    complete = bool(records) and all(
        record[field] is not None for record in records for field in fields)
    result = {"source": "fatsecret", "entries": records, "complete": complete}
    for field in fields:
        result[field] = (sum((record[field] for record in records), Decimal("0"))
                         if complete else None)
    return result


# Food database access is a DIFFERENT authorization from a user's diary:
# OAuth2 client-credentials are for server-to-server catalogue reads; the
# 3-legged OAuth1 flow above is solely for an account owner's private diary.
# The v5 search endpoint needs a suitable FatSecret PREMIER entitlement.
CATALOG_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
CATALOG_SEARCH_V5_URL = "https://platform.fatsecret.com/rest/foods/search/v5"


def _catalog_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def scale_verified_serving(serving: dict, grams: object) -> dict | None:
    """Only calculate gram-based nutrition from an explicit provider serving.

    Never interpret millilitres, household 'portions', cooked/raw conversions
    or unspecified quantities as equivalent to gram weights. When any required
    provider value is missing, return None instead of fabricating macros.
    Returned numeric values are temporary presentation values; keep only
    provider IDs in persistent records unless the provider agreement permits.
    """
    if not isinstance(serving, dict) or serving.get("metric_serving_unit") != "g":
        return None
    weight = _catalog_decimal(grams)
    unit_weight = _catalog_decimal(serving.get("metric_serving_amount"))
    if weight is None or weight <= 0 or unit_weight is None or unit_weight <= 0:
        return None
    keys={"kcal":"calories","protein_g":"protein","fat_g":"fat","carbs_g":"carbohydrate"}
    parsed={key:_catalog_decimal(serving.get(field)) for key,field in keys.items()}
    if any(value is None for value in parsed.values()):
        return None
    ratio=weight/unit_weight
    return {key:(value*ratio).quantize(Decimal("0.01")) for key,value in parsed.items()}


def normalize_catalog_search(payload: dict) -> list[dict]:
    """Strictly annotate food candidates; never auto-attach an ambiguous hit."""
    if not isinstance(payload, dict) or payload.get("error") is not None:
        raise ValueError("Invalid FatSecret catalog reply")
    root=payload.get("foods_search") or {}
    if not isinstance(root,dict):
        raise ValueError("Invalid FatSecret catalog results")
    nested=root.get("results",root)
    if not isinstance(nested,dict):
        raise ValueError("Invalid FatSecret search results container")
    items=nested.get("food",[])
    if isinstance(items,dict):
        items=[items]
    if not isinstance(items,list) or len(items)>50:
        raise ValueError("Invalid FatSecret food results")
    results=[]
    for item in items:
        if not isinstance(item,dict):
            raise ValueError("Invalid FatSecret food")
        food_id=str(item.get("food_id","")).strip()
        name=str(item.get("food_name","")).strip()
        if not food_id.isdecimal() or not name:
            raise ValueError("Missing catalog food identity")
        servings=item.get("servings") or {}
        if not isinstance(servings,dict):
            raise ValueError("Invalid servings")
        serving_rows=servings.get("serving",[])
        if isinstance(serving_rows,dict):
            serving_rows=[serving_rows]
        if not isinstance(serving_rows,list) or len(serving_rows)>100:
            raise ValueError("Invalid serving list")
        portions=[]
        for serving in serving_rows:
            if not isinstance(serving,dict):
                raise ValueError("Invalid serving")
            sid=str(serving.get("serving_id","")).strip()
            if not sid.isdecimal():
                continue
            # Only whitelist and normalise units/values approved by provider.
            mass=_catalog_decimal(serving.get("metric_serving_amount"))
            unit=serving.get("metric_serving_unit")
            sample=scale_verified_serving(serving,mass) if unit=="g" and mass else None
            portions.append({
                "serving_id":sid,
                "description":str(serving.get("serving_description",""))[:120],
                "grams":float(mass) if mass is not None and unit=="g" else None,
                "per_serving":({k:float(v) for k,v in sample.items()} if sample else None)
            })
        results.append({"food_id":food_id,"name":name[:180],
            "brand":str(item.get("brand_name",""))[:120] or None,
            "food_type":str(item.get("food_type",""))[:30],
            "servings":portions,"source":"fatsecret"})
    return results


@dataclass(frozen=True)
class FatSecretCatalogClient:
    """Official OAuth2 Food Search; no user password or local secret storage."""

    client_id: str
    client_secret: str

    def get_token(self, scope: str = "premier") -> str:
        if not (self.client_id and self.client_secret):
            raise ValueError("FatSecret food catalogue credentials not configured")
        if scope not in ("basic","premier"):
            raise ValueError("Unrecognised FatSecret OAuth2 scope")
        basic=base64.b64encode((self.client_id+":"+self.client_secret).encode()).decode("ascii")
        req=Request(CATALOG_TOKEN_URL,
            data=urlencode({"grant_type":"client_credentials","scope":scope}).encode(),
            headers={"Authorization":"Basic "+basic,
                     "Content-Type":"application/x-www-form-urlencoded"},
            method="POST")
        with urlopen(req,timeout=12) as response:
            data=json.loads(response.read(64_000))
        if not isinstance(data,dict) or not isinstance(data.get("access_token"),str) or not data["access_token"]:
            raise ValueError("FatSecret OAuth2 token unavailable")
        return data["access_token"]

    def food_by_id(self, food_id: str, bearer_token: str) -> dict:
        """Resolve one food ID from FatSecret, never trust a client-sent serving."""
        if not isinstance(food_id,str) or not food_id.isdecimal() or len(food_id)>20:
            raise ValueError("Invalid FatSecret food identifier")
        if not isinstance(bearer_token,str) or not bearer_token:
            raise ValueError("FatSecret catalogue access not configured")
        query=urlencode({"food_id":food_id,"format":"json"})
        req=Request("https://platform.fatsecret.com/rest/food/v5?"+query,
                    headers={"Authorization":"Bearer "+bearer_token,
                             "Accept":"application/json"},method="GET")
        with urlopen(req,timeout=12) as response:
            payload=json.loads(response.read(200_000))
        if not isinstance(payload,dict) or not isinstance(payload.get("food"),dict):
            raise ValueError("Invalid FatSecret food details")
        row=payload["food"]
        if str(row.get("food_id"))!=food_id:
            raise ValueError("FatSecret food identifier mismatch")
        results=normalize_catalog_search({"foods_search":{"results":{"food":[row]}}})
        if len(results)!=1:
            raise ValueError("FatSecret food detail unavailable")
        return results[0]

    def search(self, text: str, bearer_token: str, *, region: str = "RU", language: str = "ru") -> list[dict]:
        if not isinstance(text,str) or not 2<=len(text.strip())<=120:
            raise ValueError("Enter a food name from 2 to 120 characters")
        if not isinstance(bearer_token,str) or not bearer_token:
            raise ValueError("FatSecret catalogue access not configured")
        if not isinstance(region,str) or not len(region)==2 or not region.isalpha():
            raise ValueError("Invalid food region")
        if not isinstance(language,str) or not 2<=len(language)<=5 or not language.isalpha():
            raise ValueError("Invalid food language")
        query=urlencode({"search_expression":text.strip(),"max_results":"10",
                         "page_number":"0","region":region.upper(),
                         "language":language.lower(),"format":"json"})
        req=Request(CATALOG_SEARCH_V5_URL+"?"+query,
                    headers={"Authorization":"Bearer "+bearer_token,"Accept":"application/json"},
                    method="GET")
        with urlopen(req,timeout=12) as response:
            data=json.loads(response.read(300_000))
        return normalize_catalog_search(data)
