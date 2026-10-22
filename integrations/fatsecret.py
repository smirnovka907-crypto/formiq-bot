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


def _number(value: object) -> Decimal:
    try:
        num = Decimal(str(value if value is not None else "0"))
        if not num.is_finite() or num < 0:
            raise ValueError("Invalid nutrition number")
        return num
    except InvalidOperation as exc:
        raise ValueError("Invalid nutrition number") from exc


def normalize_diary(payload: dict) -> dict:
    """Normalized daily summary with stable entry IDs, zero entries supported."""
    root = payload.get("food_entries") or {}
    entries = root.get("food_entry", []) if isinstance(root, dict) else []
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
    return {
        "source": "fatsecret", "entries": records,
        "calories_kcal": sum((x["calories_kcal"] for x in records), Decimal("0")),
        "protein_g": sum((x["protein_g"] for x in records), Decimal("0")),
        "fat_g": sum((x["fat_g"] for x in records), Decimal("0")),
        "carbs_g": sum((x["carbs_g"] for x in records), Decimal("0")),
    }
