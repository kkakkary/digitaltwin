"""garmin-sync: daily poll of Garmin baseline stats -> BigQuery garmin_daily.

Runs on a schedule (Cloud Scheduler). For each configured user it loads a
cached Garmin token from Secret Manager (no password/MFA needed — see README),
pulls the last DAYS_BACK days of daily wellness + sleep + HRV, and idempotently
upserts one row per (user, date) into garmin_daily.

Idempotent + Preview-friendly: deletes the (user, date) rows it's about to
write, then loads via a BigQuery load job (committed storage, not streaming).
"""

from __future__ import annotations

import datetime as dt
import json
import os

import functions_framework
from garminconnect import Garmin
from google.cloud import bigquery, secretmanager

PROJECT = os.environ["PROJECT"]
DATASET = os.environ.get("BQ_DATASET", "health_twin")
USERS = [u.strip() for u in os.environ.get("GARMIN_USERS", "").split(",") if u.strip()]
DAYS_BACK = int(os.environ.get("DAYS_BACK", "2"))
TABLE = f"{PROJECT}.{DATASET}.garmin_daily"

_bq = bigquery.Client(project=PROJECT)
_sm = secretmanager.SecretManagerServiceClient()


def _token(user: str) -> str:
    name = f"projects/{PROJECT}/secrets/garmin-token-{user}/versions/latest"
    return _sm.access_secret_version(name=name).payload.data.decode()


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _int(x):
    """Garmin returns some integer-ish metrics as floats (e.g. calories 1326.0);
    the garmin_daily schema is INTEGER, so coerce."""
    return int(round(x)) if isinstance(x, (int, float)) else None


def _row(user: str, date: str, g: Garmin) -> dict | None:
    us = _safe(lambda: g.get_user_summary(date)) or {}
    sleep = (_safe(lambda: g.get_sleep_data(date)) or {}).get("dailySleepDTO") or {}
    hrv = _safe(lambda: g.get_hrv_data(date)) or {}
    hrv_sum = (hrv or {}).get("hrvSummary") or {}
    row = {
        "user_id": user,
        "date": date,
        "total_steps": _int(us.get("totalSteps")),
        "resting_hr": _int(us.get("restingHeartRate")),
        "avg_stress": _int(us.get("averageStressLevel")),
        "body_battery_high": _int(us.get("bodyBatteryHighestValue")),
        "body_battery_low": _int(us.get("bodyBatteryLowestValue")),
        "sleep_seconds": _int(us.get("sleepingSeconds")),
        "deep_sleep_seconds": _int(sleep.get("deepSleepSeconds")),
        "rem_sleep_seconds": _int(sleep.get("remSleepSeconds")),
        "hrv_avg": _int(hrv_sum.get("lastNightAvg")),
        "total_kcal": _int(us.get("totalKilocalories")),
        "active_kcal": _int(us.get("activeKilocalories")),
        "raw": {"user_summary": us, "sleep": sleep, "hrv": hrv},
    }
    # Skip days with no meaningful data (watch not worn, not yet synced).
    if all(row[k] is None for k in
           ("total_steps", "resting_hr", "sleep_seconds", "hrv_avg")):
        return None
    return row


def _upsert(user: str, rows: list[dict]) -> None:
    """Delete the (user, date) rows, then load the fresh ones (idempotent)."""
    dates = [r["date"] for r in rows]
    _bq.query(
        f"DELETE FROM `{TABLE}` WHERE user_id=@u AND date IN UNNEST(@d)",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "STRING", user),
            bigquery.ArrayQueryParameter("d", "DATE", dates)]),
    ).result()
    _bq.load_table_from_json(
        rows, TABLE,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
    ).result()


@functions_framework.http
def garmin_sync(request):
    # ?days=N overrides the default window (handy for backfilling history).
    days = int(request.args.get("days", DAYS_BACK))
    dates = [(dt.date.today() - dt.timedelta(days=i)).isoformat() for i in range(days)]
    out: dict[str, object] = {}
    for user in USERS:
        try:
            g = Garmin()
            g.login(_token(user))
            rows = [r for d in dates if (r := _row(user, d, g)) is not None]
            if rows:
                _upsert(user, rows)
            out[user] = len(rows)
        except Exception as exc:  # one user's failure must not abort the rest
            out[user] = f"error: {type(exc).__name__}: {exc}"
    return (json.dumps({"status": "ok", "dates": dates, "rows_per_user": out}),
            200, {"Content-Type": "application/json"})
