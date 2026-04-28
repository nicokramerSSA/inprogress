"""Analytics engine for FlowScope Miner.

The functions in this module transform raw CSV/XES event logs into the
dashboard payload consumed by the frontend. The API layer stays deliberately
thin; this file owns column inference, timestamp normalization, filtering,
process-map metrics, alternate views, animation frames, and export formats.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    import pm4py
except Exception:  # pragma: no cover - handled at runtime
    pm4py = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("flowscope.analytics")


def _timed(label: str):
    """Simple timer decorator for analytics functions."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug("%s completed in %.1f ms", label, elapsed_ms)
            return result
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator


CASE_COLUMN = "case:concept:name"
ACTIVITY_COLUMN = "concept:name"
TIMESTAMP_COLUMN = "time:timestamp"
START_TIMESTAMP_COLUMN = "time:start_timestamp"
END_TIMESTAMP_COLUMN = "time:end_timestamp"
ACTOR_COLUMN = "org:resource"
ACTOR_COLUMN_CANDIDATES = [
    ACTOR_COLUMN,
    "resource",
    "actor",
    "user",
    "assignee",
    "performer",
    "org:role",
]


@dataclass
class FilterSpec:
    """Normalized filter settings used by every analytics calculation.

    Filters that operate on complete cases are kept separate from event-level
    filters. That distinction is important in process mining because removing
    individual events can create impossible paths, while case-level filters
    preserve each retained case sequence.
    """

    start_time: datetime | None = None
    end_time: datetime | None = None
    include_activities: list[str] | None = None
    exclude_activities: list[str] | None = None
    case_include_activities: list[str] | None = None
    case_exclude_activities: list[str] | None = None
    start_activities: list[str] | None = None
    end_activities: list[str] | None = None
    direct_follow_include: list[dict[str, str]] | None = None
    direct_follow_exclude: list[dict[str, str]] | None = None
    attribute_filters: dict[str, list[str]] | None = None
    min_activity_frequency: int = 1
    min_edge_frequency: int = 1
    variant_top_k: int = 20
    retain_top_variants: int | None = None
    min_case_duration_hours: float | None = None
    max_case_duration_hours: float | None = None


class AnalyticsError(RuntimeError):
    """User-facing analytics failure that API routes convert to HTTP 400."""

    pass


# ---------------------------------------------------------------------------
# Column detection and import normalization
# ---------------------------------------------------------------------------

def detect_actor_column(df: pd.DataFrame) -> str | None:
    """Find the actor/resource column if the log has one populated."""
    for column in ACTOR_COLUMN_CANDIDATES:
        if column in df.columns and df[column].notna().any():
            return column
    return None


def _normalize_column_input(value: str | None) -> str | None:
    """Treat blank form inputs as missing mapping values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _column_tokens(column: str) -> set[str]:
    """Tokenize a source column name for the mapping heuristic."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(column).lower()).strip()
    if not normalized:
        return set()
    return set(normalized.split())


def _column_scores_for_suggestion(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Score each CSV column for likely event-log roles.

    The heuristic intentionally combines column-name hints with sample-value
    behavior. For example, case IDs often have many repeated values, activities
    have a moderate number of repeated labels, and timestamps parse cleanly as
    datetimes.
    """

    rows = max(int(len(df)), 1)
    scores: dict[str, dict[str, float]] = {}

    for column in df.columns:
        name = str(column)
        tokens = _column_tokens(name)
        lower_name = name.lower()

        values = df[column].dropna().astype(str).str.strip()
        values = values[~values.isin(["", "nan", "None", "NaT"])]
        non_empty = int(values.shape[0])
        unique_count = int(values.nunique()) if non_empty else 0
        unique_ratio = float(unique_count / non_empty) if non_empty else 0.0

        timestamp_ratio = 0.0
        if non_empty:
            parsed_dt = pd.to_datetime(values, errors="coerce", utc=True)
            timestamp_ratio = float(parsed_dt.notna().mean())

        case_score = 0.0
        if lower_name in {"case:concept:name", "case_id", "caseid", "trace_id"}:
            case_score += 4.0
        if "case" in tokens:
            case_score += 2.5
        if "trace" in tokens:
            case_score += 1.5
        if "id" in tokens or lower_name.endswith("_id"):
            case_score += 1.0
        if non_empty:
            if 0.01 <= unique_ratio <= 0.99:
                case_score += 2.0
            if unique_count >= 2:
                case_score += 0.5
            if unique_ratio < 0.95:
                case_score += 0.8

        activity_score = 0.0
        if lower_name in {"concept:name", "activity", "task", "event"}:
            activity_score += 4.0
        if {"activity", "task", "event", "action", "step", "state"}.intersection(tokens):
            activity_score += 2.5
        if {"concept", "name"}.issubset(tokens):
            activity_score += 1.2
        if non_empty:
            if 2 <= unique_count <= max(8, int(rows * 0.7)):
                activity_score += 2.0
            if unique_ratio <= 0.9:
                activity_score += 0.8
            if timestamp_ratio <= 0.25:
                activity_score += 0.4

        timestamp_base = 0.0
        if {
            "timestamp",
            "time",
            "date",
            "datetime",
            "created",
            "start",
            "end",
            "finish",
            "complete",
        }.intersection(tokens):
            timestamp_base += 2.0
        timestamp_base += timestamp_ratio * 5.0
        if timestamp_ratio >= 0.8:
            timestamp_base += 1.0

        start_score = timestamp_base
        if {"start", "begin", "open", "created", "arrival"}.intersection(tokens):
            start_score += 1.5
        if "time:start_timestamp" in lower_name:
            start_score += 2.0

        stop_score = timestamp_base
        if {"stop", "end", "complete", "completed", "finish", "closed"}.intersection(tokens):
            stop_score += 1.8
        if "time:end_timestamp" in lower_name:
            stop_score += 2.0

        actor_score = 0.0
        if lower_name in {"org:resource", "resource", "actor", "user", "assignee"}:
            actor_score += 4.0
        if {"resource", "actor", "user", "assignee", "owner", "performer", "role"}.intersection(
            tokens
        ):
            actor_score += 2.2
        if non_empty:
            if 2 <= unique_count <= max(20, int(rows * 0.8)):
                actor_score += 1.2
            if unique_ratio <= 0.9:
                actor_score += 0.6
            if timestamp_ratio <= 0.2:
                actor_score += 0.3

        filter_only_score = 0.0
        if non_empty:
            if 2 <= unique_count <= 40:
                filter_only_score += 2.2
            if unique_ratio <= 0.35:
                filter_only_score += 1.0
            if timestamp_ratio <= 0.15:
                filter_only_score += 0.5
        if {"status", "priority", "team", "queue", "channel", "region"}.intersection(tokens):
            filter_only_score += 1.0

        informational_score = 0.0
        if non_empty:
            if unique_count >= 2:
                informational_score += 1.2
            if unique_ratio <= 0.95:
                informational_score += 0.6
            if timestamp_ratio <= 0.35:
                informational_score += 0.4
        if {"description", "note", "category", "product", "region", "channel"}.intersection(
            tokens
        ):
            informational_score += 0.9

        scores[name] = {
            "case": case_score,
            "activity": activity_score,
            "start": start_score,
            "stop": stop_score,
            "actor": actor_score,
            "filter_only": filter_only_score,
            "informational": informational_score,
            "timestamp_ratio": timestamp_ratio,
            "unique_count": float(unique_count),
            "unique_ratio": unique_ratio,
        }

    return scores


def _pick_best_column(
    ranked: list[tuple[str, float]],
    *,
    used: set[str],
    min_score: float,
) -> str | None:
    """Choose the highest-scoring unused column above a confidence floor."""
    for column, score in ranked:
        if column in used:
            continue
        if score < min_score:
            continue
        return column
    return None


def _confidence_for_choice(
    ranked: list[tuple[str, float]], choice: str | None, fallback: float = 0.0
) -> float:
    """Convert heuristic score and margin over runner-up into a 0-1 confidence."""
    if not choice:
        return 0.0
    score_map = {column: score for column, score in ranked}
    chosen_score = score_map.get(choice, 0.0)
    sorted_scores = sorted(score_map.values(), reverse=True)
    runner_up = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    margin = max(chosen_score - runner_up, 0.0)
    confidence = 0.25 + min(chosen_score / 8.5, 0.6) + min(margin / 6.0, 0.15)
    if fallback > 0:
        confidence = max(confidence, fallback)
    return round(float(min(confidence, 0.99)), 3)


def _suggest_mapping_from_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Infer semantic CSV mapping plus auxiliary column recommendations."""
    columns = [str(column) for column in df.columns]
    if not columns:
        return {
            "columns": [],
            "suggestions": {
                "case_id_col": None,
                "activity_col": None,
                "start_timestamp_col": None,
                "stop_timestamp_col": None,
                "actor_col": None,
            },
            "confidence": {},
            "candidates": {},
            "suggested_filter_only_columns": [],
            "suggested_informational_columns": [],
        }

    scores = _column_scores_for_suggestion(df)
    case_ranked = sorted(
        ((column, stats["case"]) for column, stats in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    activity_ranked = sorted(
        ((column, stats["activity"]) for column, stats in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    start_ranked = sorted(
        ((column, stats["start"]) for column, stats in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    stop_ranked = sorted(
        ((column, stats["stop"]) for column, stats in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    actor_ranked = sorted(
        ((column, stats["actor"]) for column, stats in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )

    used: set[str] = set()
    case_col = _pick_best_column(case_ranked, used=used, min_score=1.4)
    if case_col:
        used.add(case_col)

    activity_col = _pick_best_column(activity_ranked, used=used, min_score=1.4)
    if activity_col:
        used.add(activity_col)

    start_col = _pick_best_column(start_ranked, used=set(), min_score=1.5)
    if not start_col and stop_ranked:
        start_col = _pick_best_column(stop_ranked, used=set(), min_score=1.5)

    stop_col = _pick_best_column(stop_ranked, used={start_col} if start_col else set(), min_score=2.2)
    if stop_col == start_col:
        stop_col = None

    actor_col = _pick_best_column(actor_ranked, used=set(), min_score=1.2)

    if not start_col and stop_col:
        start_col = stop_col
        stop_col = None

    suggestions = {
        "case_id_col": case_col,
        "activity_col": activity_col,
        "start_timestamp_col": start_col,
        "stop_timestamp_col": stop_col,
        "actor_col": actor_col,
    }

    core_columns = {value for value in suggestions.values() if value}
    filter_ranked = sorted(
        ((column, stats["filter_only"]) for column, stats in scores.items() if column not in core_columns),
        key=lambda item: item[1],
        reverse=True,
    )
    info_ranked = sorted(
        (
            (column, stats["informational"])
            for column, stats in scores.items()
            if column not in core_columns
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    suggested_filter_only = [
        column for column, score in filter_ranked[:6] if score >= 1.8
    ]
    suggested_info = [
        column
        for column, score in info_ranked[:8]
        if score >= 1.1 and column not in suggested_filter_only
    ][:6]

    confidence = {
        "case_id_col": _confidence_for_choice(case_ranked, case_col),
        "activity_col": _confidence_for_choice(activity_ranked, activity_col),
        "start_timestamp_col": _confidence_for_choice(start_ranked, start_col),
        "stop_timestamp_col": _confidence_for_choice(stop_ranked, stop_col),
        "actor_col": _confidence_for_choice(actor_ranked, actor_col),
    }

    return {
        "columns": columns,
        "suggestions": suggestions,
        "confidence": confidence,
        "candidates": {
            "case_id_col": [
                {"column": column, "score": round(float(score), 3)}
                for column, score in case_ranked[:6]
            ],
            "activity_col": [
                {"column": column, "score": round(float(score), 3)}
                for column, score in activity_ranked[:6]
            ],
            "start_timestamp_col": [
                {"column": column, "score": round(float(score), 3)}
                for column, score in start_ranked[:6]
            ],
            "stop_timestamp_col": [
                {"column": column, "score": round(float(score), 3)}
                for column, score in stop_ranked[:6]
            ],
            "actor_col": [
                {"column": column, "score": round(float(score), 3)}
                for column, score in actor_ranked[:6]
            ],
        },
        "suggested_filter_only_columns": suggested_filter_only,
        "suggested_informational_columns": suggested_info,
    }


def suggest_csv_mapping(content: bytes, sample_size: int = 4000) -> dict[str, Any]:
    """Inspect a CSV byte stream and return mapping suggestions for the UI."""
    if not content:
        raise AnalyticsError("Uploaded file is empty")

    parse_errors: list[str] = []
    df: pd.DataFrame | None = None
    for read_kwargs in (
        {"nrows": sample_size},
        {"nrows": sample_size, "sep": None, "engine": "python"},
        {"nrows": sample_size, "sep": ";"},
    ):
        try:
            df = pd.read_csv(BytesIO(content), **read_kwargs)
            break
        except Exception as exc:
            parse_errors.append(str(exc))

    if df is None:
        raise AnalyticsError(
            "Could not inspect CSV columns for suggestions: "
            + (parse_errors[-1] if parse_errors else "unknown parsing error")
        )

    return _suggest_mapping_from_dataframe(df)


def _ensure_pm4py() -> None:
    """Fail early with a readable message when dependencies are missing."""
    if pm4py is None:
        raise AnalyticsError(
            "pm4py is not installed. Install dependencies from requirements.txt first."
        )


def _normalize_base_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dataframe types and ordering after semantic columns are known."""
    expected = {CASE_COLUMN, ACTIVITY_COLUMN, TIMESTAMP_COLUMN}
    missing = expected.difference(df.columns)
    if missing:
        raise AnalyticsError(f"Missing required columns: {', '.join(sorted(missing))}")

    normalized = df.copy()
    # pm4py expects one canonical timestamp column. The app still preserves
    # start/stop timestamps separately so performance metrics can measure from
    # a source event's completion to the next event's start when both exist.
    normalized[TIMESTAMP_COLUMN] = pd.to_datetime(
        normalized[TIMESTAMP_COLUMN], errors="coerce", utc=True
    )
    if START_TIMESTAMP_COLUMN in normalized.columns:
        normalized[START_TIMESTAMP_COLUMN] = pd.to_datetime(
            normalized[START_TIMESTAMP_COLUMN], errors="coerce", utc=True
        )
    if END_TIMESTAMP_COLUMN in normalized.columns:
        normalized[END_TIMESTAMP_COLUMN] = pd.to_datetime(
            normalized[END_TIMESTAMP_COLUMN], errors="coerce", utc=True
        )
        normalized[TIMESTAMP_COLUMN] = normalized[END_TIMESTAMP_COLUMN].where(
            normalized[END_TIMESTAMP_COLUMN].notna(),
            normalized[TIMESTAMP_COLUMN],
        )
    if START_TIMESTAMP_COLUMN in normalized.columns:
        normalized[TIMESTAMP_COLUMN] = normalized[TIMESTAMP_COLUMN].where(
            normalized[TIMESTAMP_COLUMN].notna(),
            normalized[START_TIMESTAMP_COLUMN],
        )

    normalized = normalized.dropna(subset=[CASE_COLUMN, ACTIVITY_COLUMN, TIMESTAMP_COLUMN])
    normalized[CASE_COLUMN] = normalized[CASE_COLUMN].astype(str)
    normalized[ACTIVITY_COLUMN] = normalized[ACTIVITY_COLUMN].astype(str)
    actor_column = detect_actor_column(normalized)
    if actor_column:
        # Normalize actor blanks to NA so handoff views are only enabled when
        # resource data is genuinely present.
        actor_series = normalized[actor_column].astype(str).str.strip()
        actor_series = actor_series.replace(
            {"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaT": pd.NA}
        )
        normalized[actor_column] = actor_series
    normalized = normalized.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).reset_index(drop=True)
    return normalized


@_timed("load_csv_bytes")
def load_csv_bytes(
    content: bytes,
    case_id_col: str | None,
    activity_col: str | None,
    timestamp_col: str | None = None,
    start_timestamp_col: str | None = None,
    stop_timestamp_col: str | None = None,
    actor_col: str | None = None,
) -> pd.DataFrame:
    """Load a CSV event log and format it for pm4py.

    Explicit UI selections win, but missing selections are filled from the
    column-suggestion heuristic. A single timestamp source becomes the start
    timestamp by convention, matching the upload UI guidance.
    """

    _ensure_pm4py()

    logger.debug("Parsing CSV (%d bytes)", len(content))
    df: pd.DataFrame | None = None
    parse_errors: list[str] = []
    for read_kwargs in (
        {},
        {"sep": None, "engine": "python"},
        {"sep": ";"},
    ):
        try:
            candidate = pd.read_csv(BytesIO(content), **read_kwargs)
            if candidate.shape[1] > 1 or read_kwargs == {"sep": ";"}:
                df = candidate
                break
            df = candidate
        except Exception as exc:
            parse_errors.append(str(exc))

    if df is None:
        raise AnalyticsError(
            "Could not parse CSV: "
            + (parse_errors[-1] if parse_errors else "unknown parsing error")
        )

    logger.debug("CSV parsed: %d rows, %d columns", len(df), len(df.columns))

    suggested = _suggest_mapping_from_dataframe(df).get("suggestions", {})
    case_name = _normalize_column_input(case_id_col)
    activity_name = _normalize_column_input(activity_col)
    start_name = _normalize_column_input(start_timestamp_col)
    stop_name = _normalize_column_input(stop_timestamp_col)
    legacy_timestamp_name = _normalize_column_input(timestamp_col)
    actor_name = _normalize_column_input(actor_col)

    if not case_name or case_name not in df.columns:
        case_name = suggested.get("case_id_col")
    if not activity_name or activity_name not in df.columns:
        activity_name = suggested.get("activity_col")

    if not start_name or start_name not in df.columns:
        start_name = suggested.get("start_timestamp_col")
    if not stop_name or stop_name not in df.columns:
        stop_name = suggested.get("stop_timestamp_col")
    if not actor_name or actor_name not in df.columns:
        actor_name = suggested.get("actor_col")

    if not start_name and not stop_name and legacy_timestamp_name in set(df.columns):
        # ``timestamp_col`` is the older one-timestamp API field. Keep it as a
        # compatibility alias for start timestamps.
        start_name = legacy_timestamp_name

    if start_name and start_name not in df.columns:
        start_name = None
    if stop_name and stop_name not in df.columns:
        stop_name = None
    if actor_name and actor_name not in df.columns:
        actor_name = None

    missing_core: list[str] = []
    if not case_name:
        missing_core.append("case id")
    if not activity_name:
        missing_core.append("activity")
    if missing_core:
        raise AnalyticsError(
            "CSV mapping could not determine required columns: " + ", ".join(missing_core)
        )

    if not start_name:
        for candidate in (
            "start_timestamp",
            "time:start_timestamp",
            "start_time",
            "time:timestamp",
            "timestamp",
        ):
            if candidate in df.columns:
                start_name = candidate
                break
    if not stop_name:
        for candidate in (
            "stop_timestamp",
            "end_timestamp",
            "time:end_timestamp",
            "complete_timestamp",
            "completion_time",
        ):
            if candidate in df.columns:
                stop_name = candidate
                break

    if not start_name and not stop_name:
        raise AnalyticsError(
            "CSV must include at least one timestamp column "
            "(start or stop/complete timestamp)."
        )

    renamed = df.copy()
    renamed[CASE_COLUMN] = df[case_name]
    renamed[ACTIVITY_COLUMN] = df[activity_name]
    if start_name:
        renamed[START_TIMESTAMP_COLUMN] = df[start_name]
    if stop_name:
        renamed[END_TIMESTAMP_COLUMN] = df[stop_name]
    if actor_name:
        renamed[ACTOR_COLUMN] = df[actor_name]

    if END_TIMESTAMP_COLUMN in renamed.columns:
        # Canonical timestamp sorts by completion where available, while
        # transition waits still use start/stop columns directly.
        renamed[TIMESTAMP_COLUMN] = renamed[END_TIMESTAMP_COLUMN]
    elif START_TIMESTAMP_COLUMN in renamed.columns:
        renamed[TIMESTAMP_COLUMN] = renamed[START_TIMESTAMP_COLUMN]
    else:
        raise AnalyticsError(
            "Could not derive a canonical timestamp column from provided mapping."
        )

    if START_TIMESTAMP_COLUMN in renamed.columns:
        renamed[TIMESTAMP_COLUMN] = renamed[TIMESTAMP_COLUMN].where(
            renamed[TIMESTAMP_COLUMN].notna(), renamed[START_TIMESTAMP_COLUMN]
        )

    normalized = _normalize_base_dataframe(renamed)
    return pm4py.format_dataframe(
        normalized,
        case_id=CASE_COLUMN,
        activity_key=ACTIVITY_COLUMN,
        timestamp_key=TIMESTAMP_COLUMN,
    )


def load_xes_bytes(content: bytes) -> pd.DataFrame:
    """Load an XES event log using pm4py and normalize it into dataframe form."""
    _ensure_pm4py()

    with tempfile.NamedTemporaryFile(suffix=".xes", delete=False) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    try:
        event_log = pm4py.read_xes(str(temp_path))
        df = pm4py.convert_to_dataframe(event_log)
    except Exception as exc:  # pragma: no cover - depends on parser/runtime
        raise AnalyticsError(f"Could not parse XES file: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    normalized = _normalize_base_dataframe(df)
    return pm4py.format_dataframe(
        normalized,
        case_id=CASE_COLUMN,
        activity_key=ACTIVITY_COLUMN,
        timestamp_key=TIMESTAMP_COLUMN,
    )


# ---------------------------------------------------------------------------
# Shared dataframe helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def _format_datetime(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return value.isoformat()


def _event_start_series(df: pd.DataFrame) -> pd.Series:
    if START_TIMESTAMP_COLUMN in df.columns:
        return df[START_TIMESTAMP_COLUMN]
    return df[TIMESTAMP_COLUMN]


def _event_end_series(df: pd.DataFrame) -> pd.Series:
    if END_TIMESTAMP_COLUMN in df.columns:
        return df[END_TIMESTAMP_COLUMN]
    return df[TIMESTAMP_COLUMN]


def _case_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-case timing and event-count metrics."""
    time_df = pd.DataFrame(
        {
            CASE_COLUMN: df[CASE_COLUMN],
            "_event_start": _event_start_series(df),
            "_event_end": _event_end_series(df),
        }
    )
    grouped = time_df.groupby(CASE_COLUMN, observed=True)
    starts = grouped["_event_start"].min()
    ends = grouped["_event_end"].max()
    durations = (ends - starts).dt.total_seconds() / 3600
    counts = df.groupby(CASE_COLUMN, observed=True).size()
    return pd.DataFrame(
        {
            CASE_COLUMN: starts.index,
            "start_time": starts.values,
            "end_time": ends.values,
            "duration_hours": durations.values,
            "events": counts.values,
        }
    )


def _build_case_variants(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse each case into an ordered activity sequence label."""
    sequences = (
        df.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN])
        .groupby(CASE_COLUMN, observed=True)[ACTIVITY_COLUMN]
        .apply(tuple)
    )
    variant_labels = sequences.apply(lambda sequence: " -> ".join(sequence))
    result = pd.DataFrame(
        {
            CASE_COLUMN: sequences.index,
            "variant_tuple": sequences.values,
            "variant": variant_labels.values,
        }
    )
    return result


def _normalized_string_set(values: Iterable[Any] | None) -> set[str]:
    result: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in {"nan", "None", "NaT"}:
            result.add(text)
    return result


def _normalized_direct_follow_pairs(pairs: Iterable[dict[str, Any]] | None) -> set[tuple[str, str]]:
    """Normalize source/target filter pairs from frontend quick filters."""
    normalized: set[tuple[str, str]] = set()
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        source = str(pair.get("source") or "").strip()
        target = str(pair.get("target") or "").strip()
        if source and target:
            normalized.add((source, target))
    return normalized


def apply_filters(df: pd.DataFrame, filters: FilterSpec) -> pd.DataFrame:
    """Apply event-level and case-preserving filters in a stable order."""
    filtered = df.copy()
    initial_count = len(filtered)

    if filters.start_time is not None:
        start_ts = pd.Timestamp(filters.start_time)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        filtered = filtered[filtered[TIMESTAMP_COLUMN] >= start_ts]

    if filters.end_time is not None:
        end_ts = pd.Timestamp(filters.end_time)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        filtered = filtered[filtered[TIMESTAMP_COLUMN] <= end_ts]

    include_activities = _normalized_string_set(filters.include_activities)
    if include_activities:
        filtered = filtered[filtered[ACTIVITY_COLUMN].isin(include_activities)]

    exclude_activities = _normalized_string_set(filters.exclude_activities)
    if exclude_activities:
        filtered = filtered[~filtered[ACTIVITY_COLUMN].isin(exclude_activities)]

    for column, values in (filters.attribute_filters or {}).items():
        if column not in filtered.columns:
            continue
        include_values = {
            str(value).strip()
            for value in (values or [])
            if value is not None and str(value).strip() not in {"", "nan", "None"}
        }
        if not include_values:
            continue
        column_values = filtered[column].astype(str).str.strip()
        filtered = filtered[column_values.isin(include_values)]

    if filtered.empty:
        return filtered.reset_index(drop=True)

    keep_case_ids: set[str] | None = None

    # Case-level filters are evaluated on the ordered event sequence and then
    # intersected. This preserves complete cases instead of deleting isolated
    # rows and accidentally fabricating new direct-follow paths.
    ordered = filtered.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).copy()

    case_include_activities = _normalized_string_set(filters.case_include_activities)
    if case_include_activities:
        case_activity_sets = (
            ordered.groupby(CASE_COLUMN, observed=True)[ACTIVITY_COLUMN]
            .agg(lambda series: set(series.astype(str)))
        )
        matching_case_ids = set(
            case_activity_sets[
                case_activity_sets.apply(lambda activities: case_include_activities.issubset(activities))
            ].index
        )
        keep_case_ids = matching_case_ids if keep_case_ids is None else keep_case_ids & matching_case_ids

    case_exclude_activities = _normalized_string_set(filters.case_exclude_activities)
    if case_exclude_activities:
        case_activity_sets = (
            ordered.groupby(CASE_COLUMN, observed=True)[ACTIVITY_COLUMN]
            .agg(lambda series: set(series.astype(str)))
        )
        blocked_case_ids = set(
            case_activity_sets[
                case_activity_sets.apply(lambda activities: bool(case_exclude_activities & activities))
            ].index
        )
        allowed_case_ids = set(ordered[CASE_COLUMN].unique()) - blocked_case_ids
        keep_case_ids = allowed_case_ids if keep_case_ids is None else keep_case_ids & allowed_case_ids

    start_activities = _normalized_string_set(filters.start_activities)
    if start_activities:
        start_series = ordered.groupby(CASE_COLUMN, observed=True).first()[ACTIVITY_COLUMN]
        matching_case_ids = set(start_series[start_series.isin(start_activities)].index)
        keep_case_ids = matching_case_ids if keep_case_ids is None else keep_case_ids & matching_case_ids

    end_activities = _normalized_string_set(filters.end_activities)
    if end_activities:
        end_series = ordered.groupby(CASE_COLUMN, observed=True).last()[ACTIVITY_COLUMN]
        matching_case_ids = set(end_series[end_series.isin(end_activities)].index)
        keep_case_ids = matching_case_ids if keep_case_ids is None else keep_case_ids & matching_case_ids

    direct_follow_include = _normalized_direct_follow_pairs(filters.direct_follow_include)
    direct_follow_exclude = _normalized_direct_follow_pairs(filters.direct_follow_exclude)
    if direct_follow_include or direct_follow_exclude:
        transitions = _transition_dataframe(ordered)
        case_pair_sets = (
            transitions.groupby(CASE_COLUMN, observed=True)[["source", "target"]]
            .apply(lambda pair_df: set(zip(pair_df["source"], pair_df["target"])))
        )
        all_case_ids = set(ordered[CASE_COLUMN].unique())

        if direct_follow_include:
            matching_case_ids = set(
                case_pair_sets[
                    case_pair_sets.apply(lambda pairs: direct_follow_include.issubset(pairs))
                ].index
            )
            keep_case_ids = (
                matching_case_ids if keep_case_ids is None else keep_case_ids & matching_case_ids
            )

        if direct_follow_exclude:
            blocked_case_ids = set(
                case_pair_sets[
                    case_pair_sets.apply(lambda pairs: bool(direct_follow_exclude & pairs))
                ].index
            )
            allowed_case_ids = all_case_ids - blocked_case_ids
            keep_case_ids = (
                allowed_case_ids if keep_case_ids is None else keep_case_ids & allowed_case_ids
            )

    if keep_case_ids is not None:
        filtered = filtered[filtered[CASE_COLUMN].isin(keep_case_ids)]

    min_activity_frequency = max(int(filters.min_activity_frequency), 1)
    if min_activity_frequency > 1 and not filtered.empty:
        activity_counts = filtered[ACTIVITY_COLUMN].value_counts()
        keep = set(activity_counts[activity_counts >= min_activity_frequency].index)
        filtered = filtered[filtered[ACTIVITY_COLUMN].isin(keep)]

    if filtered.empty:
        return filtered.reset_index(drop=True)

    case_metrics = _case_metrics(filtered)

    if filters.min_case_duration_hours is not None:
        case_metrics = case_metrics[
            case_metrics["duration_hours"] >= float(filters.min_case_duration_hours)
        ]

    if filters.max_case_duration_hours is not None:
        case_metrics = case_metrics[
            case_metrics["duration_hours"] <= float(filters.max_case_duration_hours)
        ]

    if len(case_metrics) == 0:
        return filtered.iloc[0:0].copy()

    keep_case_ids = set(case_metrics[CASE_COLUMN])
    filtered = filtered[filtered[CASE_COLUMN].isin(keep_case_ids)]

    if filters.retain_top_variants and filters.retain_top_variants > 0 and not filtered.empty:
        variant_df = _build_case_variants(filtered)
        top_variants = (
            variant_df["variant"].value_counts().head(filters.retain_top_variants).index
        )
        keep_cases = set(
            variant_df[variant_df["variant"].isin(top_variants)][CASE_COLUMN].tolist()
        )
        filtered = filtered[filtered[CASE_COLUMN].isin(keep_cases)]

    result = filtered.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).reset_index(drop=True)
    logger.debug(
        "apply_filters: %d -> %d rows (%d removed)",
        initial_count,
        len(result),
        initial_count - len(result),
    )
    return result


def _calculate_edges(
    df: pd.DataFrame,
    transitions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate direct-follow transitions into frequency/performance edges."""
    if transitions is None:
        transitions = _transition_dataframe(df)

    edges = (
        transitions.groupby(["source", "target"], observed=True)["duration_seconds"]
        .agg(
            frequency="count",
            mean_duration_seconds="mean",
            median_duration_seconds="median",
            p90_duration_seconds=lambda series: float(series.quantile(0.9)),
        )
        .reset_index()
        .sort_values("frequency", ascending=False)
    )

    return edges


def _transition_dataframe(df: pd.DataFrame, actor_column: str | None = None) -> pd.DataFrame:
    """Build one row per direct-follow transition within each case.

    When both timestamps exist, wait time is measured from the source event's
    stop/completion to the target event's start. With one timestamp, the same
    canonical timestamp is used for both sides.
    """

    actor_column = actor_column or detect_actor_column(df)
    sorted_df = df.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).copy()
    source_time_column = END_TIMESTAMP_COLUMN if END_TIMESTAMP_COLUMN in sorted_df.columns else TIMESTAMP_COLUMN
    target_time_column = (
        START_TIMESTAMP_COLUMN
        if START_TIMESTAMP_COLUMN in sorted_df.columns
        else TIMESTAMP_COLUMN
    )
    sorted_df["position"] = sorted_df.groupby(CASE_COLUMN, observed=True).cumcount()
    sorted_df["next_activity"] = sorted_df.groupby(CASE_COLUMN, observed=True)[
        ACTIVITY_COLUMN
    ].shift(-1)
    sorted_df["source_event_time"] = sorted_df[source_time_column]
    sorted_df["next_event_time"] = sorted_df.groupby(CASE_COLUMN, observed=True)[
        target_time_column
    ].shift(-1)
    sorted_df["next_position"] = sorted_df.groupby(CASE_COLUMN, observed=True)[
        "position"
    ].shift(-1)

    if actor_column and actor_column in sorted_df.columns:
        # Actor columns are shifted alongside activity names so handoff views
        # can distinguish same-actor loops from work moving between resources.
        sorted_df["source_actor"] = sorted_df[actor_column]
        sorted_df["target_actor"] = sorted_df.groupby(CASE_COLUMN, observed=True)[
            actor_column
        ].shift(-1)
    else:
        sorted_df["source_actor"] = pd.NA
        sorted_df["target_actor"] = pd.NA

    transitions = sorted_df.dropna(subset=["next_activity", "next_event_time"]).copy()
    transitions["duration_seconds"] = (
        transitions["next_event_time"] - transitions["source_event_time"]
    ).dt.total_seconds()
    transitions["duration_seconds"] = transitions["duration_seconds"].clip(lower=0)

    return transitions.rename(
        columns={
            ACTIVITY_COLUMN: "source",
            "next_activity": "target",
            "source_event_time": "source_timestamp",
            "next_event_time": "transition_time",
            "position": "source_position",
            "next_position": "target_position",
        }
    )[
        [
            CASE_COLUMN,
            "source",
            "target",
            "source_timestamp",
            "transition_time",
            "duration_seconds",
            "source_position",
            "target_position",
            "source_actor",
            "target_actor",
        ]
    ]


def _build_nodes(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Build activity nodes used by the primary process-map view."""
    activity_counts = df[ACTIVITY_COLUMN].value_counts()
    ordered = df.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).copy()
    ordered["position"] = ordered.groupby(CASE_COLUMN, observed=True).cumcount()
    starts = ordered.groupby(CASE_COLUMN, observed=True).first()[ACTIVITY_COLUMN].value_counts()
    ends = ordered.groupby(CASE_COLUMN, observed=True).last()[ACTIVITY_COLUMN].value_counts()
    median_positions = (
        ordered.groupby(ACTIVITY_COLUMN, observed=True)["position"].median().round(2)
    )

    nodes: list[dict[str, Any]] = []
    for activity, count in activity_counts.items():
        nodes.append(
            {
                "id": activity,
                "label": activity,
                "frequency": int(count),
                "start_count": int(starts.get(activity, 0)),
                "end_count": int(ends.get(activity, 0)),
                "median_position": _safe_float(median_positions.get(activity, 0)),
            }
        )

    return nodes


def _build_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Compute top-line metrics shown in the dashboard cards."""
    if df.empty:
        return {
            "total_cases": 0,
            "total_events": 0,
            "activities": 0,
            "start_time": None,
            "end_time": None,
            "median_case_duration_hours": 0,
            "avg_case_duration_hours": 0,
            "median_events_per_case": 0,
            "rework_case_ratio": 0,
        }

    case_metrics = _case_metrics(df)

    case_activity_counts = (
        df.groupby([CASE_COLUMN, ACTIVITY_COLUMN], observed=True)
        .size()
        .reset_index(name="count")
    )
    rework_cases = case_activity_counts[case_activity_counts["count"] > 1][
        CASE_COLUMN
    ].nunique()

    return {
        "total_cases": int(df[CASE_COLUMN].nunique()),
        "total_events": int(len(df)),
        "activities": int(df[ACTIVITY_COLUMN].nunique()),
        "start_time": _format_datetime(_event_start_series(df).min()),
        "end_time": _format_datetime(_event_end_series(df).max()),
        "median_case_duration_hours": round(
            _safe_float(case_metrics["duration_hours"].median()), 2
        ),
        "avg_case_duration_hours": round(
            _safe_float(case_metrics["duration_hours"].mean()), 2
        ),
        "median_events_per_case": round(_safe_float(case_metrics["events"].median()), 2),
        "rework_case_ratio": round(
            float(rework_cases / max(case_metrics.shape[0], 1)), 4
        ),
    }


def _build_variants(
    df: pd.DataFrame, case_metrics: pd.DataFrame, variant_top_k: int
) -> list[dict[str, Any]]:
    """Return ranked process variants with volume and duration statistics."""
    if df.empty:
        return []

    variant_df = _build_case_variants(df)
    merged = variant_df.merge(case_metrics[[CASE_COLUMN, "duration_hours"]], on=CASE_COLUMN)
    variant_counts = merged["variant"].value_counts().head(max(variant_top_k, 1))
    total_cases = max(df[CASE_COLUMN].nunique(), 1)

    variants: list[dict[str, Any]] = []
    for rank, (variant, count) in enumerate(variant_counts.items(), start=1):
        subset = merged[merged["variant"] == variant]
        variants.append(
            {
                "rank": rank,
                "variant": variant,
                "cases": int(count),
                "share": round(float(count / total_cases), 4),
                "avg_duration_hours": round(
                    _safe_float(subset["duration_hours"].mean()), 2
                ),
                "median_duration_hours": round(
                    _safe_float(subset["duration_hours"].median()), 2
                ),
            }
        )

    return variants


def _build_activity_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return per-activity frequency and case-coverage metrics."""
    if df.empty:
        return []

    activity_counts = df[ACTIVITY_COLUMN].value_counts()
    case_count = max(df[CASE_COLUMN].nunique(), 1)

    # Vectorized: compute cases-per-activity in one groupby instead of N filters
    cases_per_activity = (
        df.groupby(ACTIVITY_COLUMN, observed=True)[CASE_COLUMN]
        .nunique()
    )

    stats: list[dict[str, Any]] = []
    for activity, frequency in activity_counts.items():
        stats.append(
            {
                "activity": activity,
                "frequency": int(frequency),
                "case_coverage": round(
                    float(cases_per_activity.get(activity, 0) / case_count), 4
                ),
            }
        )

    return stats


def _build_edges_payload(edges_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert edge aggregates into JSON-safe dashboard records."""
    if edges_df.empty:
        return []
    # Vectorized: avoid slow iterrows() by rounding columns in bulk and using to_dict
    result = edges_df[["source", "target", "frequency", "mean_duration_seconds",
                        "median_duration_seconds", "p90_duration_seconds"]].copy()
    result["frequency"] = result["frequency"].astype(int)
    for col in ("mean_duration_seconds", "median_duration_seconds", "p90_duration_seconds"):
        result[col] = result[col].fillna(0.0).round(2)
    return result.to_dict("records")


def _build_bottlenecks(edges_payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank paths by median wait, then by volume."""
    bottlenecks = sorted(
        list(edges_payload),
        key=lambda edge: (edge["median_duration_seconds"], edge["frequency"]),
        reverse=True,
    )
    return bottlenecks[:15]


def _clean_actor_value(value: Any) -> str | None:
    """Normalize actor/resource values before building handoff diagrams."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text in {"", "nan", "None", "NaT"}:
        return None
    return text


def _build_actor_views(
    df: pd.DataFrame,
    filters: FilterSpec,
    transitions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build actor-focused and activity-focused handoff graphs.

    The actor view shows resource-to-resource transfer. The activity view shows
    the activities at which a resource handoff happened, filtering out
    same-actor transitions so the map stays focused on handoffs.
    """

    actor_column = detect_actor_column(df)
    if not actor_column:
        return {
            "enabled": False,
            "actor_column": None,
            "actor_view": {"nodes": [], "edges": [], "total_handoffs": 0},
            "activity_view": {"nodes": [], "edges": [], "total_handoffs": 0},
        }

    actor_events = df.copy()
    actor_events["actor_clean"] = actor_events[actor_column].map(_clean_actor_value)
    actor_events = actor_events.dropna(subset=["actor_clean"])

    if transitions is None:
        transitions = _transition_dataframe(df, actor_column=actor_column)
    transitions = transitions.copy()
    transitions["source_actor_clean"] = transitions["source_actor"].map(_clean_actor_value)
    transitions["target_actor_clean"] = transitions["target_actor"].map(_clean_actor_value)
    transitions = transitions.dropna(subset=["source_actor_clean", "target_actor_clean"])
    transitions = transitions[
        transitions["source_actor_clean"] != transitions["target_actor_clean"]
    ]

    if transitions.empty:
        return {
            "enabled": True,
            "actor_column": actor_column,
            "actor_view": {"nodes": [], "edges": [], "total_handoffs": 0},
            "activity_view": {"nodes": [], "edges": [], "total_handoffs": 0},
        }

    actor_node_counts = actor_events["actor_clean"].value_counts()
    actor_nodes = [
        {
            "id": actor,
            "label": actor,
            "frequency": int(count),
        }
        for actor, count in actor_node_counts.items()
    ]

    actor_edges_df = (
        transitions.groupby(["source_actor_clean", "target_actor_clean"], observed=True)[
            "duration_seconds"
        ]
        .agg(
            frequency="count",
            median_duration_seconds="median",
            mean_duration_seconds="mean",
        )
        .reset_index()
        .rename(
            columns={
                "source_actor_clean": "source",
                "target_actor_clean": "target",
            }
        )
        .sort_values("frequency", ascending=False)
    )
    min_edge_frequency = max(int(filters.min_edge_frequency), 1)
    actor_edges_df = actor_edges_df[actor_edges_df["frequency"] >= min_edge_frequency]
    actor_edges = [
        {
            "source": row["source"],
            "target": row["target"],
            "frequency": int(row["frequency"]),
            "median_duration_seconds": round(_safe_float(row["median_duration_seconds"]), 2),
            "mean_duration_seconds": round(_safe_float(row["mean_duration_seconds"]), 2),
        }
        for _, row in actor_edges_df.iterrows()
    ]

    activity_handoff_df = (
        transitions.groupby(["source", "target"], observed=True)["duration_seconds"]
        .agg(
            frequency="count",
            median_duration_seconds="median",
            mean_duration_seconds="mean",
        )
        .reset_index()
        .sort_values("frequency", ascending=False)
    )
    activity_handoff_df = activity_handoff_df[
        activity_handoff_df["frequency"] >= min_edge_frequency
    ]
    activity_edges = [
        {
            "source": row["source"],
            "target": row["target"],
            "frequency": int(row["frequency"]),
            "median_duration_seconds": round(_safe_float(row["median_duration_seconds"]), 2),
            "mean_duration_seconds": round(_safe_float(row["mean_duration_seconds"]), 2),
        }
        for _, row in activity_handoff_df.iterrows()
    ]
    activity_nodes_lookup = pd.concat(
        [activity_handoff_df["source"], activity_handoff_df["target"]], ignore_index=True
    ).value_counts()
    activity_nodes = [
        {"id": activity, "label": activity, "frequency": int(count)}
        for activity, count in activity_nodes_lookup.items()
    ]

    total_handoffs = int(len(transitions))
    return {
        "enabled": True,
        "actor_column": actor_column,
        "actor_view": {
            "nodes": actor_nodes,
            "edges": actor_edges,
            "total_handoffs": total_handoffs,
        },
        "activity_view": {
            "nodes": activity_nodes,
            "edges": activity_edges,
            "total_handoffs": total_handoffs,
        },
    }


def _build_swimlane_view(
    df: pd.DataFrame,
    filters: FilterSpec,
    transitions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a Visio-like lane model grouped by actor/resource."""
    actor_column = detect_actor_column(df)
    if not actor_column:
        return {
            "available": False,
            "actor_column": None,
            "lanes": [],
            "nodes": [],
            "edges": [],
        }

    actor_counts = (
        df[actor_column].map(_clean_actor_value).dropna().value_counts().head(10)
    )
    top_actors = actor_counts.index.tolist()
    if not top_actors:
        return {
            "available": False,
            "actor_column": actor_column,
            "lanes": [],
            "nodes": [],
            "edges": [],
        }

    events = df.copy()
    events["actor_clean"] = events[actor_column].map(_clean_actor_value)
    events = events[events["actor_clean"].isin(top_actors)]

    node_df = (
        events.groupby(["actor_clean", ACTIVITY_COLUMN], observed=True)
        .size()
        .reset_index(name="frequency")
        .sort_values(["actor_clean", "frequency"], ascending=[True, False])
    )
    node_df = node_df.groupby("actor_clean", observed=True).head(8).copy()
    node_df["id"] = node_df["actor_clean"] + " || " + node_df[ACTIVITY_COLUMN].astype(str)
    node_ids = set(node_df["id"].tolist())
    lane_positions = {actor: idx for idx, actor in enumerate(top_actors)}

    swim_transitions = (
        _transition_dataframe(df, actor_column=actor_column)
        if transitions is None
        else transitions.copy()
    )
    swim_transitions["source_actor_clean"] = swim_transitions["source_actor"].map(_clean_actor_value)
    swim_transitions["target_actor_clean"] = swim_transitions["target_actor"].map(_clean_actor_value)
    swim_transitions = swim_transitions[
        swim_transitions["source_actor_clean"].isin(top_actors)
        & swim_transitions["target_actor_clean"].isin(top_actors)
    ]
    swim_transitions["source_id"] = (
        swim_transitions["source_actor_clean"] + " || " + swim_transitions["source"].astype(str)
    )
    swim_transitions["target_id"] = (
        swim_transitions["target_actor_clean"] + " || " + swim_transitions["target"].astype(str)
    )
    swim_transitions = swim_transitions[
        swim_transitions["source_id"].isin(node_ids) & swim_transitions["target_id"].isin(node_ids)
    ]

    edges_df = (
        swim_transitions.groupby(
            ["source_id", "target_id", "source_actor_clean", "target_actor_clean"],
            observed=True,
        )["duration_seconds"]
        .agg(frequency="count", median_duration_seconds="median")
        .reset_index()
        .sort_values("frequency", ascending=False)
    )
    min_edge_frequency = max(int(filters.min_edge_frequency), 1)
    edges_df = edges_df[edges_df["frequency"] >= min_edge_frequency]

    nodes = [
        {
            "id": row["id"],
            "label": row[ACTIVITY_COLUMN],
            "activity": row[ACTIVITY_COLUMN],
            "actor": row["actor_clean"],
            "lane": row["actor_clean"],
            "lane_index": lane_positions.get(row["actor_clean"], 0),
            "frequency": int(row["frequency"]),
        }
        for _, row in node_df.iterrows()
    ]
    edges = [
        {
            "source": row["source_id"],
            "target": row["target_id"],
            "source_actor": row["source_actor_clean"],
            "target_actor": row["target_actor_clean"],
            "frequency": int(row["frequency"]),
            "median_duration_seconds": round(
                _safe_float(row["median_duration_seconds"]), 2
            ),
        }
        for _, row in edges_df.head(220).iterrows()
    ]

    return {
        "available": True,
        "actor_column": actor_column,
        "lanes": top_actors,
        "nodes": nodes,
        "edges": edges,
    }


def _build_sankey_view(
    df: pd.DataFrame,
    filters: FilterSpec,
    transitions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a staged Sankey payload that emphasizes transition volume."""
    transitions = transitions if transitions is not None else _transition_dataframe(df)
    if transitions.empty:
        return {"available": False, "nodes": [], "links": []}

    edges_df = (
        transitions.groupby(["source", "target"], observed=True)["duration_seconds"]
        .agg(frequency="count", median_duration_seconds="median")
        .reset_index()
        .sort_values("frequency", ascending=False)
    )
    min_edge_frequency = max(int(filters.min_edge_frequency), 1)
    edges_df = edges_df[edges_df["frequency"] >= min_edge_frequency]
    if edges_df.empty:
        return {"available": False, "nodes": [], "links": []}

    positions_df = df.sort_values([CASE_COLUMN, TIMESTAMP_COLUMN]).copy()
    positions_df["position"] = positions_df.groupby(CASE_COLUMN, observed=True).cumcount()
    activity_positions = (
        positions_df.groupby(ACTIVITY_COLUMN, observed=True)["position"].median().sort_values()
    )
    ordered_activities = activity_positions.index.tolist()
    scale_denominator = max(len(ordered_activities) - 1, 1)
    stage_map = {
        activity: int(round((idx / scale_denominator) * min(8, scale_denominator)))
        for idx, activity in enumerate(ordered_activities)
    }

    activity_counts = df[ACTIVITY_COLUMN].value_counts()
    node_names = set(edges_df["source"]).union(set(edges_df["target"]))
    nodes = [
        {
            "id": activity,
            "label": activity,
            "stage": int(stage_map.get(activity, 0)),
            "frequency": int(activity_counts.get(activity, 0)),
        }
        for activity in sorted(
            node_names, key=lambda item: (stage_map.get(item, 0), -activity_counts.get(item, 0))
        )
    ]
    links = [
        {
            "source": row["source"],
            "target": row["target"],
            "value": int(row["frequency"]),
            "median_duration_seconds": round(
                _safe_float(row["median_duration_seconds"]), 2
            ),
        }
        for _, row in edges_df.head(260).iterrows()
    ]

    return {"available": True, "nodes": nodes, "links": links}


def _build_rework_view(
    df: pd.DataFrame,
    transitions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Detect repeated activity hotspots and direct self-loops."""
    if df.empty:
        return {"activities": [], "self_loops": []}

    activity_case_counts = (
        df.groupby([CASE_COLUMN, ACTIVITY_COLUMN], observed=True)
        .size()
        .reset_index(name="count")
    )
    rework_df = activity_case_counts[activity_case_counts["count"] > 1].copy()
    total_cases = max(int(df[CASE_COLUMN].nunique()), 1)

    activities = []
    if not rework_df.empty:
        grouped = (
            rework_df.groupby(ACTIVITY_COLUMN, observed=True)
            .agg(
                cases_with_rework=(CASE_COLUMN, "nunique"),
                rework_events=("count", lambda series: int((series - 1).sum())),
                max_repetitions=("count", "max"),
            )
            .reset_index()
            .sort_values("rework_events", ascending=False)
        )
        # Vectorized: use to_dict instead of iterrows
        grouped["rework_case_ratio"] = (grouped["cases_with_rework"] / total_cases).round(4)
        activities = [
            {
                "activity": row[ACTIVITY_COLUMN],
                "cases_with_rework": int(row["cases_with_rework"]),
                "rework_events": int(row["rework_events"]),
                "max_repetitions": int(row["max_repetitions"]),
                "rework_case_ratio": float(row["rework_case_ratio"]),
            }
            for _, row in grouped.iterrows()
        ]

    transitions = transitions if transitions is not None else _transition_dataframe(df)
    loops_df = (
        transitions[transitions["source"] == transitions["target"]]
        .groupby("source", observed=True)
        .size()
        .reset_index(name="frequency")
        .sort_values("frequency", ascending=False)
    )
    self_loops = [
        {"activity": row["source"], "frequency": int(row["frequency"])}
        for _, row in loops_df.iterrows()
    ]

    return {"activities": activities, "self_loops": self_loops}


def _build_queue_age_heatmap(transitions: pd.DataFrame) -> dict[str, Any]:
    """Build a heatmap of median wait by source activity and time bucket."""
    if transitions.empty:
        return {"available": False, "buckets": [], "rows": [], "cells": []}

    heatmap_df = transitions.dropna(subset=["source", "source_timestamp"]).copy()
    heatmap_df = heatmap_df[heatmap_df["duration_seconds"].notna()]
    if heatmap_df.empty:
        return {"available": False, "buckets": [], "rows": [], "cells": []}

    # Focus the heatmap on the worst queue-age activities so the SVG stays
    # legible on large logs.
    activity_rank = (
        heatmap_df.groupby("source", observed=True)["duration_seconds"]
        .agg(frequency="count", median_duration_seconds="median")
        .reset_index()
        .sort_values(["median_duration_seconds", "frequency"], ascending=False)
        .head(10)
    )
    top_activities = activity_rank["source"].astype(str).tolist()
    heatmap_df = heatmap_df[heatmap_df["source"].isin(top_activities)].copy()
    if heatmap_df.empty:
        return {"available": False, "buckets": [], "rows": [], "cells": []}

    start_time = heatmap_df["source_timestamp"].min()
    end_time = heatmap_df["source_timestamp"].max()
    if pd.isna(start_time) or pd.isna(end_time):
        return {"available": False, "buckets": [], "rows": [], "cells": []}

    bucket_count = 1
    if start_time != end_time:
        bucket_count = min(8, max(2, int(heatmap_df["source_timestamp"].dt.date.nunique())))

    if bucket_count == 1:
        heatmap_df["bucket_index"] = 0
        buckets = [
            {
                "index": 0,
                "label": _format_datetime(start_time),
                "start_time": _format_datetime(start_time),
                "end_time": _format_datetime(end_time),
            }
        ]
    else:
        bucket_edges = pd.date_range(
            start=start_time,
            end=end_time,
            periods=bucket_count + 1,
            inclusive="both",
        )
        heatmap_df["bucket_index"] = pd.cut(
            heatmap_df["source_timestamp"],
            bins=bucket_edges,
            labels=False,
            include_lowest=True,
            right=True,
        )
        heatmap_df["bucket_index"] = (
            heatmap_df["bucket_index"].fillna(bucket_count - 1).astype(int)
        )
        buckets = [
            {
                "index": idx,
                "label": bucket_edges[idx].strftime("%b %-d")
                if hasattr(bucket_edges[idx], "strftime")
                else str(bucket_edges[idx]),
                "start_time": _format_datetime(bucket_edges[idx]),
                "end_time": _format_datetime(bucket_edges[idx + 1]),
            }
            for idx in range(bucket_count)
        ]

    grouped = (
        heatmap_df.groupby(["source", "bucket_index"], observed=True)["duration_seconds"]
        .agg(frequency="count", median_duration_seconds="median", p90_duration_seconds=lambda series: float(series.quantile(0.9)))
        .reset_index()
    )
    row_order = {activity: idx for idx, activity in enumerate(top_activities)}
    cells = [
        {
            "activity": row["source"],
            "bucket_index": int(row["bucket_index"]),
            "frequency": int(row["frequency"]),
            "median_duration_seconds": round(_safe_float(row["median_duration_seconds"]), 2),
            "p90_duration_seconds": round(_safe_float(row["p90_duration_seconds"]), 2),
        }
        for _, row in grouped.iterrows()
    ]

    return {
        "available": True,
        "buckets": buckets,
        "rows": [
            {
                "activity": row["source"],
                "frequency": int(row["frequency"]),
                "median_duration_seconds": round(_safe_float(row["median_duration_seconds"]), 2),
            }
            for _, row in activity_rank.iterrows()
            if row["source"] in row_order
        ],
        "cells": cells,
    }


def _build_variant_duration_boxplot(
    df: pd.DataFrame,
    case_metrics: pd.DataFrame,
    variant_top_k: int,
) -> dict[str, Any]:
    """Build quartile statistics for the duration spread of top variants."""
    if df.empty or case_metrics.empty:
        return {"available": False, "variants": []}

    variant_df = _build_case_variants(df)
    merged = variant_df.merge(
        case_metrics[[CASE_COLUMN, "duration_hours"]],
        on=CASE_COLUMN,
        how="inner",
    )
    if merged.empty:
        return {"available": False, "variants": []}

    top_variants = merged["variant"].value_counts().head(max(variant_top_k, 1)).index
    rows: list[dict[str, Any]] = []
    for rank, variant in enumerate(top_variants, start=1):
        durations = merged[merged["variant"] == variant]["duration_hours"].dropna()
        if durations.empty:
            continue
        rows.append(
            {
                "rank": rank,
                "variant": variant,
                "cases": int(durations.shape[0]),
                "min_duration_hours": round(_safe_float(durations.min()), 2),
                "q1_duration_hours": round(_safe_float(durations.quantile(0.25)), 2),
                "median_duration_hours": round(_safe_float(durations.median()), 2),
                "q3_duration_hours": round(_safe_float(durations.quantile(0.75)), 2),
                "max_duration_hours": round(_safe_float(durations.max()), 2),
            }
        )

    return {"available": bool(rows), "variants": rows}


def _build_extra_views(
    df: pd.DataFrame,
    case_metrics: pd.DataFrame,
    transitions: pd.DataFrame,
    rework: dict[str, Any],
    filters: FilterSpec,
) -> dict[str, Any]:
    """Collect promoted bottleneck/rework views used by the frontend tabs."""
    return {
        "queue_age_heatmap": _build_queue_age_heatmap(transitions),
        "rework_treemap": {
            "available": bool(rework.get("activities")),
            "activities": rework.get("activities", []),
        },
        "variant_duration_boxplot": _build_variant_duration_boxplot(
            df,
            case_metrics,
            variant_top_k=max(filters.variant_top_k, 1),
        ),
    }


def _view_recommendations() -> list[dict[str, str]]:
    """Describe promoted views for report/backward compatibility.

    The live UI now renders these as full diagrams, but older report sections
    still use this text to explain why the views are useful.
    """

    return [
        {
            "id": "queue_age_heatmap",
            "title": "Queue Age Heatmap",
            "why": "Highlights queues with long waiting times over time slices.",
        },
        {
            "id": "rework_treemap",
            "title": "Rework Treemap",
            "why": "Shows which activities consume the most repeated work volume.",
        },
        {
            "id": "variant_duration_boxplot",
            "title": "Variant Duration Boxplot",
            "why": "Compares spread of cycle times across dominant process variants.",
        },
    ]


@_timed("dashboard_payload")
def dashboard_payload(df: pd.DataFrame, filters: FilterSpec) -> dict[str, Any]:
    """Build the complete filtered dashboard payload for one UI refresh."""
    t0 = time.perf_counter()
    filtered = apply_filters(df, filters)
    logger.debug(
        "Filtered %d -> %d rows (%.1f ms)",
        len(df),
        len(filtered),
        (time.perf_counter() - t0) * 1000,
    )

    summary = _build_summary(filtered)
    case_metrics = _case_metrics(filtered) if not filtered.empty else pd.DataFrame()
    actor_column = detect_actor_column(filtered) if not filtered.empty else None

    if filtered.empty:
        logger.info("Dashboard returning empty result — no events after filtering")
        return {
            "summary": summary,
            "nodes": [],
            "edges": [],
            "variants": [],
            "activity_stats": [],
            "bottlenecks": [],
            "actor_column": actor_column,
            "handoff": {
                "enabled": False,
                "actor_column": actor_column,
                "actor_view": {"nodes": [], "edges": [], "total_handoffs": 0},
                "activity_view": {"nodes": [], "edges": [], "total_handoffs": 0},
            },
            "swimlane": {
                "available": False,
                "actor_column": actor_column,
                "lanes": [],
                "nodes": [],
                "edges": [],
            },
            "sankey": {"available": False, "nodes": [], "links": []},
            "rework": {"activities": [], "self_loops": []},
            "extra_views": {
                "queue_age_heatmap": {"available": False, "buckets": [], "rows": [], "cells": []},
                "rework_treemap": {"available": False, "activities": []},
                "variant_duration_boxplot": {"available": False, "variants": []},
            },
            "recommendations": _view_recommendations(),
        }

    # Compute transitions once and share across all sub-computations. This is
    # the main performance lever for large logs because edges, handoffs,
    # Sankey, rework, queue heatmaps, and animations all start from transitions.
    t1 = time.perf_counter()
    transitions = _transition_dataframe(filtered)
    logger.debug(
        "Computed %d transitions in %.1f ms",
        len(transitions),
        (time.perf_counter() - t1) * 1000,
    )

    edges_df = _calculate_edges(filtered, transitions=transitions)
    min_edge_frequency = max(int(filters.min_edge_frequency), 1)
    edges_df = edges_df[edges_df["frequency"] >= min_edge_frequency]
    edges_payload = _build_edges_payload(edges_df)

    rework_view = _build_rework_view(filtered, transitions=transitions)

    result = {
        "summary": summary,
        "nodes": _build_nodes(filtered),
        "edges": edges_payload,
        "variants": _build_variants(
            filtered,
            case_metrics,
            variant_top_k=max(filters.variant_top_k, 1),
        ),
        "activity_stats": _build_activity_stats(filtered),
        "bottlenecks": _build_bottlenecks(edges_payload),
        "actor_column": actor_column,
        "handoff": _build_actor_views(filtered, filters, transitions=transitions),
        "swimlane": _build_swimlane_view(filtered, filters, transitions=transitions),
        "sankey": _build_sankey_view(filtered, filters, transitions=transitions),
        "rework": rework_view,
        "extra_views": _build_extra_views(
            filtered,
            case_metrics,
            transitions,
            rework_view,
            filters,
        ),
        "recommendations": _view_recommendations(),
    }

    logger.info(
        "Dashboard built: %d nodes, %d edges, %d variants",
        len(result["nodes"]),
        len(result["edges"]),
        len(result["variants"]),
    )
    return result


def _empty_relative_animation_payload() -> dict[str, Any]:
    """Return the empty animation shape expected by the frontend."""
    return {
        "timeline_mode": "relative_case_start",
        "normalized_case_start": True,
        "start_offset_seconds": 0.0,
        "end_offset_seconds": 0.0,
        "frame_count": 0,
        "frame_interval_seconds": 0,
        "max_edge_count_per_frame": 0,
        "max_total_transitions_per_frame": 0,
        "frames": [],
    }


def _prepare_relative_animation_timeline(
    df: pd.DataFrame,
    filters: FilterSpec,
    frame_count: int,
) -> tuple[pd.DataFrame, int, list[float], float]:
    """Normalize every case to T+0 for Disco-style animation playback.

    This is why the animation shows all cases starting at the same relative
    time: each transition is positioned by its offset from that case's own
    start timestamp, then all offsets are binned into shared frames.
    """

    filtered = apply_filters(df, filters)
    if filtered.empty:
        return pd.DataFrame(), 0, [0.0, 0.0], 0.0

    actor_column = detect_actor_column(filtered)
    transitions = _transition_dataframe(filtered, actor_column=actor_column)
    if transitions.empty:
        return transitions, 0, [0.0, 0.0], 0.0

    case_start_lookup = (
        pd.DataFrame(
            {
                CASE_COLUMN: filtered[CASE_COLUMN],
                "case_start_time": _event_start_series(filtered),
            }
        )
        .groupby(CASE_COLUMN, observed=True)["case_start_time"]
        .min()
    )
    transitions = transitions.merge(
        case_start_lookup.rename("case_start_time"),
        left_on=CASE_COLUMN,
        right_index=True,
        how="left",
    )
    transitions["timeline_seconds"] = (
        transitions["transition_time"] - transitions["case_start_time"]
    ).dt.total_seconds()
    transitions["timeline_seconds"] = transitions["timeline_seconds"].clip(lower=0)

    transitions["source_actor_clean"] = transitions["source_actor"].map(_clean_actor_value)
    transitions["target_actor_clean"] = transitions["target_actor"].map(_clean_actor_value)

    safe_frame_count = max(1, min(int(frame_count), 240))
    max_offset_seconds = _safe_float(transitions["timeline_seconds"].max())

    if max_offset_seconds <= 0:
        transitions["frame_idx"] = 0
        return transitions, 1, [0.0, 0.0], 0.0

    bin_edges = [
        float((max_offset_seconds * idx) / safe_frame_count)
        for idx in range(safe_frame_count + 1)
    ]
    transitions["frame_idx"] = pd.cut(
        transitions["timeline_seconds"],
        bins=bin_edges,
        labels=False,
        include_lowest=True,
        right=True,
    )
    transitions["frame_idx"] = (
        transitions["frame_idx"].fillna(safe_frame_count - 1).astype(int)
    )
    return transitions, safe_frame_count, bin_edges, float(max_offset_seconds)


def _view_animation_payload_from_transitions(
    transitions: pd.DataFrame,
    *,
    source_column: str,
    target_column: str,
    min_edge_frequency: int,
    frame_count: int,
    bin_edges: list[float],
    max_offset_seconds: float,
) -> dict[str, Any]:
    """Build animation frames for one source/target view of the transition set."""
    empty_payload = _empty_relative_animation_payload()
    if transitions.empty or frame_count <= 0:
        return empty_payload

    view_transitions = transitions.dropna(subset=[source_column, target_column]).copy()
    if view_transitions.empty:
        return empty_payload

    view_transitions[source_column] = view_transitions[source_column].map(str).str.strip()
    view_transitions[target_column] = view_transitions[target_column].map(str).str.strip()
    view_transitions = view_transitions[
        (view_transitions[source_column] != "") & (view_transitions[target_column] != "")
    ]
    if view_transitions.empty:
        return empty_payload

    edge_counts = (
        view_transitions.groupby([source_column, target_column], observed=True)
        .size()
        .reset_index(name="frequency")
    )
    keep_edges = edge_counts[edge_counts["frequency"] >= min_edge_frequency][
        [source_column, target_column]
    ]
    if keep_edges.empty:
        return empty_payload

    view_transitions = view_transitions.merge(
        keep_edges, on=[source_column, target_column], how="inner"
    )
    if view_transitions.empty:
        return empty_payload

    grouped = (
        view_transitions.groupby(["frame_idx", source_column, target_column], observed=True)
        .size()
        .reset_index(name="count")
    )
    grouped_by_frame = {
        int(frame_idx): frame_df.sort_values("count", ascending=False)
        for frame_idx, frame_df in grouped.groupby("frame_idx", observed=True)
    }

    frames: list[dict[str, Any]] = []
    max_edge_count_per_frame = 0
    max_total_transitions_per_frame = 0

    for frame_idx in range(frame_count):
        frame_df = grouped_by_frame.get(frame_idx)
        if frame_df is None:
            edges: list[dict[str, Any]] = []
            total_transitions = 0
        else:
            total_transitions = int(frame_df["count"].sum())
            max_total_transitions_per_frame = max(
                max_total_transitions_per_frame, total_transitions
            )
            frame_max = int(frame_df["count"].max())
            max_edge_count_per_frame = max(max_edge_count_per_frame, frame_max)
            edges = [
                {
                    "source": row[source_column],
                    "target": row[target_column],
                    "count": int(row["count"]),
                }
                for _, row in frame_df.head(180).iterrows()
            ]

        frames.append(
            {
                "index": frame_idx,
                "start_offset_seconds": round(float(bin_edges[frame_idx]), 2),
                "end_offset_seconds": round(float(bin_edges[frame_idx + 1]), 2),
                "total_transitions": total_transitions,
                "edges": edges,
            }
        )

    interval_seconds = (
        float(max_offset_seconds / frame_count) if frame_count > 0 else 0.0
    )

    return {
        "timeline_mode": "relative_case_start",
        "normalized_case_start": True,
        "start_offset_seconds": 0.0,
        "end_offset_seconds": round(float(max_offset_seconds), 2),
        "frame_count": frame_count,
        "frame_interval_seconds": round(interval_seconds, 2),
        "max_edge_count_per_frame": int(max_edge_count_per_frame),
        "max_total_transitions_per_frame": int(max_total_transitions_per_frame),
        "frames": frames,
    }


@_timed("animation_views_payload")
def animation_views_payload(
    df: pd.DataFrame,
    filters: FilterSpec,
    frame_count: int = 80,
) -> dict[str, Any]:
    """Return synchronized animation payloads for process and handoff diagrams."""
    transitions, safe_frame_count, bin_edges, max_offset_seconds = (
        _prepare_relative_animation_timeline(df, filters, frame_count)
    )
    min_edge_frequency = max(int(filters.min_edge_frequency), 1)

    if transitions.empty or safe_frame_count <= 0:
        empty_payload = _empty_relative_animation_payload()
        return {
            "timeline_mode": "relative_case_start",
            "normalized_case_start": True,
            "views": {
                "process": empty_payload,
                "handoff_actor": empty_payload,
                "handoff_activity": empty_payload,
            },
        }

    handoff_transitions = transitions.dropna(
        subset=["source_actor_clean", "target_actor_clean"]
    ).copy()
    handoff_transitions = handoff_transitions[
        handoff_transitions["source_actor_clean"]
        != handoff_transitions["target_actor_clean"]
    ]

    return {
        "timeline_mode": "relative_case_start",
        "normalized_case_start": True,
        "views": {
            "process": _view_animation_payload_from_transitions(
                transitions,
                source_column="source",
                target_column="target",
                min_edge_frequency=min_edge_frequency,
                frame_count=safe_frame_count,
                bin_edges=bin_edges,
                max_offset_seconds=max_offset_seconds,
            ),
            "handoff_actor": _view_animation_payload_from_transitions(
                handoff_transitions,
                source_column="source_actor_clean",
                target_column="target_actor_clean",
                min_edge_frequency=min_edge_frequency,
                frame_count=safe_frame_count,
                bin_edges=bin_edges,
                max_offset_seconds=max_offset_seconds,
            ),
            "handoff_activity": _view_animation_payload_from_transitions(
                handoff_transitions,
                source_column="source",
                target_column="target",
                min_edge_frequency=min_edge_frequency,
                frame_count=safe_frame_count,
                bin_edges=bin_edges,
                max_offset_seconds=max_offset_seconds,
            ),
        },
    }


@_timed("animation_payload")
def animation_payload(
    df: pd.DataFrame, filters: FilterSpec, frame_count: int = 80
) -> dict[str, Any]:
    """Legacy absolute-time animation payload.

    The UI primarily uses ``animation_views_payload`` because the user-facing
    animation should align all cases to a common relative start. This function
    remains for older exports and compatibility with existing report logic.
    """

    filtered = apply_filters(df, filters)
    logger.debug("Animation: %d filtered events, %d requested frames", len(filtered), frame_count)
    if filtered.empty:
        return {
            "start_time": None,
            "end_time": None,
            "frame_count": 0,
            "frame_interval_seconds": 0,
            "max_edge_count_per_frame": 0,
            "max_total_transitions_per_frame": 0,
            "frames": [],
        }

    transitions = _transition_dataframe(filtered)
    if transitions.empty:
        return {
            "start_time": None,
            "end_time": None,
            "frame_count": 0,
            "frame_interval_seconds": 0,
            "max_edge_count_per_frame": 0,
            "max_total_transitions_per_frame": 0,
            "frames": [],
        }

    min_edge_frequency = max(int(filters.min_edge_frequency), 1)
    edge_counts = (
        transitions.groupby(["source", "target"], observed=True)
        .size()
        .reset_index(name="frequency")
    )
    keep_edges = edge_counts[edge_counts["frequency"] >= min_edge_frequency][
        ["source", "target"]
    ]
    if keep_edges.empty:
        return {
            "start_time": None,
            "end_time": None,
            "frame_count": 0,
            "frame_interval_seconds": 0,
            "max_edge_count_per_frame": 0,
            "max_total_transitions_per_frame": 0,
            "frames": [],
        }

    transitions = transitions.merge(keep_edges, on=["source", "target"], how="inner")
    transitions = transitions.sort_values("transition_time")
    if transitions.empty:
        return {
            "start_time": None,
            "end_time": None,
            "frame_count": 0,
            "frame_interval_seconds": 0,
            "max_edge_count_per_frame": 0,
            "max_total_transitions_per_frame": 0,
            "frames": [],
        }

    start_time = transitions["transition_time"].min()
    end_time = transitions["transition_time"].max()

    safe_frame_count = max(1, min(int(frame_count), 240))
    if start_time == end_time:
        grouped = (
            transitions.groupby(["source", "target"], observed=True)
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        edges = [
            {
                "source": row["source"],
                "target": row["target"],
                "count": int(row["count"]),
            }
            for _, row in grouped.iterrows()
        ]
        return {
            "start_time": _format_datetime(start_time),
            "end_time": _format_datetime(end_time),
            "frame_count": 1,
            "frame_interval_seconds": 0,
            "max_edge_count_per_frame": int(grouped["count"].max()) if not grouped.empty else 0,
            "max_total_transitions_per_frame": int(len(transitions)),
            "frames": [
                {
                    "index": 0,
                    "start_time": _format_datetime(start_time),
                    "end_time": _format_datetime(end_time),
                    "total_transitions": int(len(transitions)),
                    "edges": edges,
                }
            ],
        }

    bin_edges = pd.date_range(
        start=start_time,
        end=end_time,
        periods=safe_frame_count + 1,
        inclusive="both",
    )
    transitions["frame_idx"] = pd.cut(
        transitions["transition_time"],
        bins=bin_edges,
        labels=False,
        include_lowest=True,
        right=True,
    )
    transitions["frame_idx"] = (
        transitions["frame_idx"].fillna(safe_frame_count - 1).astype(int)
    )

    grouped = (
        transitions.groupby(["frame_idx", "source", "target"], observed=True)
        .size()
        .reset_index(name="count")
    )

    grouped_by_frame = {
        int(frame_idx): frame_df.sort_values("count", ascending=False)
        for frame_idx, frame_df in grouped.groupby("frame_idx", observed=True)
    }

    frames: list[dict[str, Any]] = []
    max_edge_count_per_frame = 0
    max_total_transitions_per_frame = 0

    for frame_idx in range(safe_frame_count):
        frame_df = grouped_by_frame.get(frame_idx)
        if frame_df is None:
            edges: list[dict[str, Any]] = []
            total_transitions = 0
        else:
            total_transitions = int(frame_df["count"].sum())
            max_total_transitions_per_frame = max(
                max_total_transitions_per_frame, total_transitions
            )
            frame_max = int(frame_df["count"].max())
            max_edge_count_per_frame = max(max_edge_count_per_frame, frame_max)
            edges = [
                {
                    "source": row["source"],
                    "target": row["target"],
                    "count": int(row["count"]),
                }
                for _, row in frame_df.head(180).iterrows()
            ]

        frames.append(
            {
                "index": frame_idx,
                "start_time": _format_datetime(bin_edges[frame_idx]),
                "end_time": _format_datetime(bin_edges[frame_idx + 1]),
                "total_transitions": total_transitions,
                "edges": edges,
            }
        )

    interval_seconds = float((end_time - start_time).total_seconds() / safe_frame_count)

    return {
        "start_time": _format_datetime(start_time),
        "end_time": _format_datetime(end_time),
        "frame_count": safe_frame_count,
        "frame_interval_seconds": round(interval_seconds, 2),
        "max_edge_count_per_frame": int(max_edge_count_per_frame),
        "max_total_transitions_per_frame": int(max_total_transitions_per_frame),
        "frames": frames,
    }


def _sanitize_mermaid_label(text: Any) -> str:
    """Escape labels enough for Mermaid diagram source."""
    return str(text).replace('"', "'").replace("\n", " ").strip()


def _mermaid_flowchart_from_nodes_edges(
    *,
    direction: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_key: str = "source",
    target_key: str = "target",
    edge_value_key: str = "frequency",
) -> str:
    """Serialize a node/edge payload as a Mermaid flowchart."""
    lines = [f"flowchart {direction}"]
    alias_by_id: dict[str, str] = {}
    for index, node in enumerate(nodes[:220]):
        node_id = str(node.get("id", f"node_{index}"))
        alias = f"N{index}"
        alias_by_id[node_id] = alias
        label = _sanitize_mermaid_label(node.get("label", node_id))
        lines.append(f'{alias}["{label}"]')

    for edge in edges[:300]:
        source_raw = str(edge.get(source_key, ""))
        target_raw = str(edge.get(target_key, ""))
        source_alias = alias_by_id.get(source_raw)
        target_alias = alias_by_id.get(target_raw)
        if not source_alias or not target_alias:
            continue
        value = edge.get(edge_value_key, edge.get("count", ""))
        lines.append(f"{source_alias} -->|{value}| {target_alias}")

    return "\n".join(lines)


def _mermaid_swimlane(swimlane: dict[str, Any]) -> str | None:
    """Serialize the actor swimlane model as Mermaid subgraphs."""
    if not swimlane.get("available"):
        return None

    lines = ["flowchart LR"]
    nodes = swimlane.get("nodes", [])
    edges = swimlane.get("edges", [])
    lanes = swimlane.get("lanes", [])
    lane_nodes = {lane: [] for lane in lanes}

    alias_by_id: dict[str, str] = {}
    for index, node in enumerate(nodes[:220]):
        node_id = str(node.get("id", f"node_{index}"))
        alias = f"S{index}"
        alias_by_id[node_id] = alias
        lane = str(node.get("lane", "Unassigned"))
        lane_nodes.setdefault(lane, []).append((alias, node))

    for lane, entries in lane_nodes.items():
        lane_safe = _sanitize_mermaid_label(lane)
        lines.append(f'subgraph "{lane_safe}"')
        for alias, node in entries:
            label = _sanitize_mermaid_label(node.get("label", node.get("id", "")))
            lines.append(f'{alias}["{label}"]')
        lines.append("end")

    for edge in edges[:320]:
        source_alias = alias_by_id.get(str(edge.get("source", "")))
        target_alias = alias_by_id.get(str(edge.get("target", "")))
        if not source_alias or not target_alias:
            continue
        value = edge.get("frequency", "")
        lines.append(f"{source_alias} -->|{value}| {target_alias}")

    return "\n".join(lines)


def _mermaid_sankey(sankey: dict[str, Any]) -> str | None:
    """Serialize Sankey links using Mermaid's sankey-beta syntax."""
    if not sankey.get("available"):
        return None

    lines = ["sankey-beta"]
    for link in sankey.get("links", [])[:400]:
        source = str(link.get("source", "")).replace(",", " ")
        target = str(link.get("target", "")).replace(",", " ")
        value = int(link.get("value", 0))
        lines.append(f"{source},{target},{value}")
    return "\n".join(lines)


def _mermaid_rework(rework: dict[str, Any]) -> str | None:
    """Serialize rework hotspots as self-loop flowchart nodes."""
    activities = rework.get("activities", [])
    if not activities:
        return None

    lines = ["flowchart LR"]
    for index, row in enumerate(activities[:80]):
        alias = f"R{index}"
        label = _sanitize_mermaid_label(row.get("activity", f"Activity {index + 1}"))
        lines.append(f'{alias}["{label}"]')

        rework_events = int(row.get("rework_events", 0))
        ratio = row.get("rework_case_ratio")
        ratio_text = ""
        try:
            if ratio is not None:
                ratio_text = f" | {float(ratio) * 100:.1f}% cases"
        except Exception:
            ratio_text = ""

        lines.append(f"{alias} -->|{rework_events}{ratio_text}| {alias}")

    return "\n".join(lines)


def mermaid_export_payload(dashboard: dict[str, Any]) -> dict[str, str]:
    """Collect Mermaid exports for every diagram type that has data."""
    mermaid: dict[str, str] = {}
    mermaid["process_map"] = _mermaid_flowchart_from_nodes_edges(
        direction="LR",
        nodes=dashboard.get("nodes", []),
        edges=dashboard.get("edges", []),
    )

    handoff = dashboard.get("handoff", {})
    if handoff.get("enabled"):
        mermaid["handoff_actor"] = _mermaid_flowchart_from_nodes_edges(
            direction="LR",
            nodes=handoff.get("actor_view", {}).get("nodes", []),
            edges=handoff.get("actor_view", {}).get("edges", []),
        )
        mermaid["handoff_activity"] = _mermaid_flowchart_from_nodes_edges(
            direction="LR",
            nodes=handoff.get("activity_view", {}).get("nodes", []),
            edges=handoff.get("activity_view", {}).get("edges", []),
        )

    swimlane_mermaid = _mermaid_swimlane(dashboard.get("swimlane", {}))
    if swimlane_mermaid:
        mermaid["swimlane"] = swimlane_mermaid

    sankey_mermaid = _mermaid_sankey(dashboard.get("sankey", {}))
    if sankey_mermaid:
        mermaid["sankey"] = sankey_mermaid

    rework_mermaid = _mermaid_rework(dashboard.get("rework", {}))
    if rework_mermaid:
        mermaid["rework"] = rework_mermaid

    return mermaid


def bpmn_xml_payload(df: pd.DataFrame, filters: FilterSpec) -> dict[str, Any]:
    """Discover and export a BPMN model for the filtered log when pm4py allows."""
    _ensure_pm4py()
    filtered = apply_filters(df, filters)
    if filtered.empty:
        return {"available": False, "message": "No events remain after filtering."}

    event_log = _to_event_log(filtered)
    bpmn_graph = None
    try:
        discover_bpmn_inductive = getattr(pm4py, "discover_bpmn_inductive", None)
        discover_bpmn = getattr(pm4py, "discover_bpmn", None)
        if callable(discover_bpmn_inductive):
            bpmn_graph = discover_bpmn_inductive(event_log)
        elif callable(discover_bpmn):
            bpmn_graph = discover_bpmn(event_log)
    except Exception as exc:  # pragma: no cover - runtime/version dependent
        return {"available": False, "message": f"BPMN discovery failed: {exc}"}

    if bpmn_graph is None:
        return {
            "available": False,
            "message": "BPMN discovery API is not available in this pm4py version.",
        }

    with tempfile.NamedTemporaryFile(suffix=".bpmn", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        write_bpmn = getattr(pm4py, "write_bpmn", None)
        if callable(write_bpmn):
            write_bpmn(bpmn_graph, str(temp_path))
        else:
            from pm4py.objects.bpmn.exporter import exporter as bpmn_exporter

            bpmn_exporter.apply(bpmn_graph, str(temp_path))
        xml = temp_path.read_text(encoding="utf-8", errors="replace")
        return {"available": True, "xml": xml}
    except Exception as exc:  # pragma: no cover - runtime/version dependent
        return {"available": False, "message": f"BPMN export failed: {exc}"}
    finally:
        temp_path.unlink(missing_ok=True)


def _to_event_log(df: pd.DataFrame):
    """Convert the normalized dataframe back into a pm4py EventLog object."""
    _ensure_pm4py()
    formatted_df = pm4py.format_dataframe(
        df,
        case_id=CASE_COLUMN,
        activity_key=ACTIVITY_COLUMN,
        timestamp_key=TIMESTAMP_COLUMN,
    )
    return pm4py.convert_to_event_log(formatted_df)


@_timed("conformance_payload")
def conformance_payload(df: pd.DataFrame, filters: FilterSpec) -> dict[str, Any]:
    """Run inductive discovery plus replay/precision metrics when supported."""
    _ensure_pm4py()

    filtered = apply_filters(df, filters)
    logger.debug("Conformance analysis on %d filtered events", len(filtered))
    if filtered.empty:
        return {
            "supported": False,
            "message": "No events remain after filtering.",
        }

    event_log = _to_event_log(filtered)

    try:
        net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(event_log)
    except Exception as exc:  # pragma: no cover - version/runtime dependent
        return {
            "supported": False,
            "message": f"Could not discover process model: {exc}",
        }

    fitness_score = None
    fitness_details: dict[str, Any] | None = None
    precision_score = None

    try:
        fitness_fn = getattr(pm4py, "fitness_token_based_replay", None)
        if callable(fitness_fn):
            fitness_result = fitness_fn(event_log, net, initial_marking, final_marking)
            if isinstance(fitness_result, dict):
                fitness_details = fitness_result
                fitness_score = (
                    fitness_result.get("log_fitness")
                    or fitness_result.get("average_trace_fitness")
                    or fitness_result.get("percentage_of_fitting_traces")
                )
            elif isinstance(fitness_result, (int, float)):
                fitness_score = float(fitness_result)
    except Exception:
        fitness_score = None

    try:
        precision_fn = getattr(pm4py, "precision_token_based_replay", None)
        if callable(precision_fn):
            precision_result = precision_fn(event_log, net, initial_marking, final_marking)
            if isinstance(precision_result, (int, float)):
                precision_score = float(precision_result)
            elif isinstance(precision_result, dict):
                precision_score = _safe_float(
                    precision_result.get("precision")
                    or precision_result.get("averagePrecision")
                )
    except Exception:
        precision_score = None

    return {
        "supported": True,
        "fitness": None if fitness_score is None else round(float(fitness_score), 4),
        "precision": None if precision_score is None else round(float(precision_score), 4),
        "model": {
            "places": len(net.places),
            "transitions": len(net.transitions),
            "arcs": len(net.arcs),
        },
        "fitness_details": fitness_details,
        "cases": int(filtered[CASE_COLUMN].nunique()),
        "events": int(len(filtered)),
    }


def available_activities(df: pd.DataFrame) -> list[str]:
    """Return activity labels for UI filter controls."""
    return sorted(df[ACTIVITY_COLUMN].astype(str).unique().tolist())


def attribute_filter_options(
    df: pd.DataFrame, columns: list[str], max_values_per_column: int = 200
) -> dict[str, list[str]]:
    """Return top values for configured filter-only columns."""
    options: dict[str, list[str]] = {}
    for column in columns:
        if column not in df.columns:
            continue
        values = (
            df[column]
            .dropna()
            .astype(str)
            .str.strip()
        )
        values = values[~values.isin(["", "nan", "None", "NaT"])]
        if values.empty:
            options[column] = []
            continue

        top_values = (
            values.value_counts()
            .head(max(max_values_per_column, 1))
            .index.astype(str)
            .tolist()
        )
        options[column] = top_values

    return options


def informational_column_profile(
    df: pd.DataFrame, columns: list[str], top_values_per_column: int = 6
) -> list[dict[str, Any]]:
    """Profile informational columns for the bottom dashboard card and exports."""
    profile: list[dict[str, Any]] = []
    for column in columns:
        if column not in df.columns:
            continue
        values = df[column].dropna().astype(str).str.strip()
        values = values[~values.isin(["", "nan", "None", "NaT"])]
        if values.empty:
            profile.append(
                {"column": column, "non_null": 0, "unique_values": 0, "top_values": []}
            )
            continue

        value_counts = values.value_counts()
        top_values = [
            {"value": str(value), "count": int(count)}
            for value, count in value_counts.head(max(top_values_per_column, 1)).items()
        ]
        profile.append(
            {
                "column": column,
                "non_null": int(values.shape[0]),
                "unique_values": int(values.nunique()),
                "top_values": top_values,
            }
        )

    return profile
