"""Garmin Connect business API payload normalization for FORMIQ.

This is an offline adapter for Garmin push/ping-pull records. NO unofficial
Garmin Connect login, scraped credentials, or implied user connection.
Production transport (OAuth2, callbacks, verification, subscriptions and
retries) requires an approved Garmin Developer Program account and its
API-specific documentation. This module intentionally performs no I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

SUPPORTED_COLLECTIONS = ("dailies", "sleeps", "activities")


def _number(value: Any, *, limit: int | float | None = None) -> float | None:
    if value in ("", None):
        return None
    try:
        val = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid Garmin numeric field") from exc
    if not val.is_finite() or val < 0 or (limit is not None and val > limit):
        raise ValueError("Unexpected Garmin metric")
    return float(val)


def _timestamp(value: Any) -> str | None:
    if value in ("", None):
        return None
    try:
        timestamp = int(value)
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid Garmin timestamp") from exc


def _safe_text(value: Any, max_length: int = 80) -> str:
    return str(value if value is not None else "")[:max_length]


def normalize_garmin_webhook(payload: dict, *, expected_user_id: str | None = None) -> list[dict]:
    """Map known provider collections to explicitly attributed records.

    API adapter never trusts the Garmin userId as an authenticated FORMIQ user.
    Production caller must first map an authorized Garmin identity to a FORMIQ
    account, then enforce this with expected_user_id.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid Garmin payload")
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for collection in SUPPORTED_COLLECTIONS:
        summaries = payload.get(collection, [])
        if summaries is None:
            continue
        if not isinstance(summaries, list):
            raise ValueError("Invalid Garmin collection")
        if len(summaries) > 1000:
            raise ValueError("Oversized Garmin batch")
        for record in summaries:
            if not isinstance(record, dict):
                raise ValueError("Invalid Garmin summary")
            user_id = _safe_text(record.get("userId"))
            if not user_id:
                raise ValueError("Missing Garmin identity")
            if expected_user_id is not None and user_id != expected_user_id:
                raise PermissionError("Garmin identity does not match authorization")
            summary_id = _safe_text(
                record.get("summaryId") or record.get("activityId")
                or record.get("calendarDate") or record.get("startTimeInSeconds")
            )
            if not summary_id:
                raise ValueError("Missing Garmin record identity")
            identity = (collection, user_id, summary_id)
            if identity in seen:
                continue
            seen.add(identity)
            item = {
                "source": "garmin",
                "source_user_id": user_id,
                "external_id": summary_id,
                "category": collection,
                "start_at_utc": _timestamp(record.get("startTimeInSeconds")),
                "calendar_date": _safe_text(record.get("calendarDate"), 10) or None,
            }
            if collection == "dailies":
                item["steps"] = _number(record.get("steps"), limit=200000)
                item["resting_heart_rate_bpm"] = _number(record.get("restingHeartRateInBeatsPerMinute"), limit=300)
                item["active_calories_kcal"] = _number(record.get("activeKilocalories"))
                item["average_stress_level"] = _number(record.get("averageStressLevel"), limit=100)
            elif collection == "sleeps":
                seconds = _number(record.get("durationInSeconds"))
                item["duration_seconds"] = seconds
                item["duration_minutes"] = round(seconds / 60, 1) if seconds is not None else None
                item["sleep_score"] = _number(record.get("overallSleepScore"), limit=100) if not isinstance(record.get("overallSleepScore"), dict) else None
            else:
                item["activity_type"] = _safe_text(record.get("activityType"))
                item["duration_seconds"] = _number(record.get("durationInSeconds"))
                item["distance_meters"] = _number(record.get("distanceInMeters"))
                item["average_heart_rate_bpm"] = _number(record.get("averageHeartRateInBeatsPerMinute"), limit=300)
                item["active_calories_kcal"] = _number(record.get("activeKilocalories"))
            out.append(item)
    return out


def stable_identity(record: dict) -> tuple[str, str, str, str]:
    """Unique record key for database UPSERT; never append the same event twice."""
    return (
        record["source"], record["category"],
        record["source_user_id"], record["external_id"],
    )
