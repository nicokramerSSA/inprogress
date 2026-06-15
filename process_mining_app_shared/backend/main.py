"""FastAPI entry point for FlowScope Miner.

This module deliberately stays thin: it owns HTTP concerns, uploaded-log
lifecycle, export packaging, and HTML report rendering. Process-mining
calculations live in ``backend.analytics`` so the UI can call small, focused
API endpoints without knowing about pandas or pm4py internals.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, Generator
from uuid import uuid4
import zipfile

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analytics import (
    FilterSpec,
    AnalyticsError,
    animation_payload,
    animation_views_payload,
    apply_filters,
    attribute_filter_options,
    available_activities,
    bpmn_xml_payload,
    conformance_payload,
    dashboard_payload,
    disco_csv_export_payload,
    informational_column_profile,
    load_csv_bytes,
    load_xes_bytes,
    mermaid_export_payload,
    suggest_csv_mapping,
)
from .database import create_tables, migrate_schema, engine, logs, projects
from sqlalchemy import select, insert, delete

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("flowscope")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_handler)


@contextmanager
def _log_timer(operation: str, **extra: Any) -> Generator[None, None, None]:
    """Context manager that logs elapsed time for an operation."""
    context = " ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
    logger.info("START %s %s", operation, context)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("END   %s — %.1f ms %s", operation, elapsed_ms, context)


@dataclass
class StoredLog:
    """One uploaded event log plus the UI metadata derived during import.

    Logs are intentionally kept in memory for this local desktop-style app.
    If the app later grows into a multi-user service, this dataclass is the
    natural seam to replace with durable storage.
    """

    log_id: str
    filename: str
    dataframe: pd.DataFrame
    uploaded_at: datetime
    column_mapping: dict[str, str | None]
    informational_columns: list[str]
    filter_only_columns: list[str]
    filter_only_values: dict[str, list[str]]
    mapping_warnings: list[str]
    owner: str = "flowteam"


class DashboardFilterRequest(BaseModel):
    """Wire-format filter object accepted by dashboard, animation, and exports.

    Keeping the request model here gives FastAPI validation and OpenAPI docs,
    while ``to_filter_spec`` converts the request into the analytics-layer
    dataclass used by pandas calculations.
    """

    start_time: datetime | None = None
    end_time: datetime | None = None
    include_activities: list[str] = Field(default_factory=list)
    exclude_activities: list[str] = Field(default_factory=list)
    case_include_activities: list[str] = Field(default_factory=list)
    case_exclude_activities: list[str] = Field(default_factory=list)
    start_activities: list[str] = Field(default_factory=list)
    end_activities: list[str] = Field(default_factory=list)
    direct_follow_include: list[dict[str, str]] = Field(default_factory=list)
    direct_follow_exclude: list[dict[str, str]] = Field(default_factory=list)
    attribute_filters: dict[str, list[str]] = Field(default_factory=dict)
    min_activity_frequency: int = 1
    min_edge_frequency: int = 1
    variant_top_k: int = 20
    retain_top_variants: int | None = None
    min_case_duration_hours: float | None = None
    max_case_duration_hours: float | None = None

    def to_filter_spec(self) -> FilterSpec:
        return FilterSpec(
            start_time=self.start_time,
            end_time=self.end_time,
            include_activities=self.include_activities,
            exclude_activities=self.exclude_activities,
            case_include_activities=self.case_include_activities,
            case_exclude_activities=self.case_exclude_activities,
            start_activities=self.start_activities,
            end_activities=self.end_activities,
            direct_follow_include=self.direct_follow_include,
            direct_follow_exclude=self.direct_follow_exclude,
            attribute_filters=self.attribute_filters,
            min_activity_frequency=self.min_activity_frequency,
            min_edge_frequency=self.min_edge_frequency,
            variant_top_k=self.variant_top_k,
            retain_top_variants=self.retain_top_variants,
            min_case_duration_hours=self.min_case_duration_hours,
            max_case_duration_hours=self.max_case_duration_hours,
        )


app = FastAPI(
    title="Disco-Style Process Mining with pm4py",
    description="Interactive process mining dashboard built on pm4py.",
    version="0.1.0",
)


_SESSION_COOKIE = "fs_session"
SESSION_STORE: Dict[str, str] = {}  # token → username


def _parse_users() -> Dict[str, str]:
    """Parse USERS env var (format: user1:pass1,user2:pass2) into a dict."""
    raw = os.getenv("USERS", "")
    users: Dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            username, _, password = pair.partition(":")
            username, password = username.strip(), password.strip()
            if username and password:
                users[username] = password
    return users


_USERS: Dict[str, str] = _parse_users()
_AUTH_ENABLED: bool = bool(_USERS)


def _owner(request: Request) -> str:
    """Return authenticated username, or 'flowteam' in local-dev (auth disabled) mode."""
    username = getattr(request.state, "username", None)
    return username or "flowteam"


@app.on_event("startup")
def on_startup() -> None:
    """Create DB tables and run schema migrations on first boot."""
    create_tables()
    migrate_schema()
    logger.info("Database tables verified/migrated on startup")

# Origins allowed to embed or call Flowscope cross-origin. Update here when adding environments.
# localhost:8080 is intentionally included for local dev (not a security risk — browsers enforce origin).
_POET_ORIGINS = {
    "https://processreengineering.onrender.com",
    "http://localhost:8080",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_POET_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_LOGIN_PUBLIC_PATHS = {"/login", "/logout"}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://processreengineering.onrender.com http://localhost:8080"
    )
    return response


# Flowscope's own origins added so direct (non-iframe) login form POSTs aren't blocked.
_ALLOWED_ORIGINS = _POET_ORIGINS | {
    "https://flowscope-miner-qo3x.onrender.com",
    "http://localhost:8000",
}


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and origin not in _ALLOWED_ORIGINS:
            return Response("Forbidden", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def session_auth_middleware(request: Request, call_next):
    """Redirect unauthenticated requests to /login when USERS env var is set.

    Skipped entirely in local dev if USERS is not configured.
    """
    if not _AUTH_ENABLED:
        request.state.username = None
        return await call_next(request)

    path = request.url.path
    if path in _LOGIN_PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)

    token = request.cookies.get(_SESSION_COOKIE)
    username = SESSION_STORE.get(token) if token else None

    if not username:
        return RedirectResponse(url="/login", status_code=302)

    request.state.username = username
    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request with method, path, status, and elapsed time."""
    request_id = uuid4().hex[:8]
    t0 = time.perf_counter()
    logger.info(
        "REQ %s %s %s (id=%s)",
        request.method,
        request.url.path,
        request.query_params or "",
        request_id,
    )
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "RES %s %s -> %d (%.1f ms, id=%s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        response.headers["X-Request-Id"] = request_id
        return response
    except Exception:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.exception(
            "ERR %s %s unhandled exception after %.1f ms (id=%s)",
            request.method,
            request.url.path,
            elapsed_ms,
            request_id,
        )
        raise


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")

LOG_STORE: Dict[str, StoredLog] = {}


# ---------------------------------------------------------------------------
# Shared request and export helpers
# ---------------------------------------------------------------------------

def _get_log_or_404(log_id: str, owner: str | None = None) -> StoredLog:
    """Fetch a stored log from the in-memory cache or reload it from the DB.

    On a fresh server start the cache is empty, but logs persisted to Postgres
    can be reconstructed on first access without requiring a re-upload.
    When owner is provided, access is denied if the log belongs to another user.
    """
    record = LOG_STORE.get(log_id)
    if record is not None:
        if owner and record.owner != owner:
            raise HTTPException(status_code=404, detail="Unknown log_id")
        return record

    with engine.connect() as conn:
        query = select(logs).where(logs.c.id == log_id)
        if owner:
            query = query.where(logs.c.owner == owner)
        row = conn.execute(query).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Unknown log_id")

    content = bytes(row["file_data"])
    file_format = row["file_format"]
    filename = row["filename"]

    try:
        if file_format == "csv":
            dataframe = load_csv_bytes(
                content,
                case_id_col=row["column_mapping"].get("case_id_col") or "",
                activity_col=row["column_mapping"].get("activity_col") or "",
                timestamp_col="",
                start_timestamp_col=row["column_mapping"].get("start_timestamp_col") or "",
                stop_timestamp_col=row["column_mapping"].get("stop_timestamp_col") or "",
                actor_col=row["column_mapping"].get("actor_col") or "",
            )
        else:
            dataframe = load_xes_bytes(content)
    except AnalyticsError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reload log from DB: {exc}") from exc

    restored = StoredLog(
        log_id=log_id,
        filename=filename,
        dataframe=dataframe,
        uploaded_at=row["uploaded_at"],
        column_mapping=dict(row["column_mapping"] or {}),
        informational_columns=list(row["informational_columns"] or []),
        filter_only_columns=list(row["filter_only_columns"] or []),
        filter_only_values=dict(row["filter_only_values"] or {}),
        mapping_warnings=list(row["mapping_warnings"] or []),
        owner=row.get("owner") or "flowteam",
    )
    LOG_STORE[log_id] = restored
    logger.info("Reloaded log %s (%s) from DB into cache", log_id, filename)
    return restored


def _safe_export_basename(filename: str) -> str:
    """Convert an uploaded filename into a safe download basename."""
    stem = Path(filename).stem or "event_log"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return safe or "event_log"


def _parse_column_list(value: str | None) -> list[str]:
    """Parse comma/newline/semicolon-separated column names from form fields."""
    if value is None:
        return []

    seen: set[str] = set()
    columns: list[str] = []
    for part in re.split(r"[,\n;]+", str(value)):
        column = part.strip()
        if not column or column in seen:
            continue
        seen.add(column)
        columns.append(column)
    return columns


def _resolve_existing_columns(
    dataframe: pd.DataFrame,
    requested_columns: list[str],
    *,
    blocked: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Split requested auxiliary columns into accepted and ignored lists.

    Core process columns are blocked so the same source column is not treated
    as both a semantic event-log field and an informational/filter-only field.
    """

    blocked = blocked or set()
    existing: list[str] = []
    missing: list[str] = []
    for column in requested_columns:
        if column in blocked:
            continue
        if column in dataframe.columns:
            existing.append(column)
        else:
            missing.append(column)
    return existing, missing


def _records_to_csv(records: list[dict]) -> str:
    """Serialize a list-of-dicts payload into a small CSV export file."""
    return pd.DataFrame.from_records(records).to_csv(index=False)


# ---------------------------------------------------------------------------
# HTML report formatting helpers
# ---------------------------------------------------------------------------

def _format_decimal(value: Any, precision: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except Exception:
        return escape(str(value))
    return f"{number:,.{precision}f}"


def _format_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except Exception:
        return escape(str(value))


def _format_seconds_human(value: Any) -> str:
    if value is None:
        return "-"
    try:
        seconds = float(value)
    except Exception:
        return escape(str(value))

    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


def _format_percent(value: Any, precision: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value) * 100
    except Exception:
        return "-"
    return f"{number:.{precision}f}%"


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a compact HTML table used by the self-contained report export."""
    if not rows:
        return '<p class="empty">No rows for current filters.</p>'

    head_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        "<div class=\"table-wrap\"><table>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table></div>"
    )


def _report_map_svg(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    """Build a static SVG snapshot of the process map for HTML exports.

    The browser app renders richer interactive maps, but exported reports need
    to be self-contained. This function mirrors the staged process-map concept
    with start/end anchors, frequency-weighted edges, and readable activity
    boxes without requiring client-side JavaScript.
    """

    if not nodes or not edges:
        return "<p class=\"empty\">No process-map edges for current filters.</p>"

    # LTR layout: stages spread on X axis, nodes stack vertically within each stage.
    width = 1400
    height = 760
    left_pad = 240
    right_pad = 220
    top_pad = 60
    bottom_pad = 60
    sibling_gap = 62

    normalized_nodes = []
    for node in nodes:
        normalized_nodes.append(
            {
                "id": str(node.get("id", "")),
                "label": str(node.get("label", node.get("id", ""))),
                "frequency": int(node.get("frequency", 0) or 0),
                "start_count": int(node.get("start_count", 0) or 0),
                "end_count": int(node.get("end_count", 0) or 0),
                "median_position": float(node.get("median_position", 0) or 0),
            }
        )
    node_map = {node["id"]: node for node in normalized_nodes}
    normalized_edges = [
        {
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
            "frequency": int(edge.get("frequency", 0) or 0),
            "median_duration_seconds": float(edge.get("median_duration_seconds", 0) or 0),
        }
        for edge in edges
        if str(edge.get("source", "")) in node_map and str(edge.get("target", "")) in node_map
    ]
    if not normalized_edges:
        return "<p class=\"empty\">No process-map edges for current filters.</p>"

    def _truncate(label: str, max_chars: int = 20) -> str:
        return label if len(label) <= max_chars else f"{label[: max_chars - 3]}..."

    def _wrap_label(text: str, node_width: float, font_size: int) -> list[str]:
        avg_char_w = font_size * 0.58
        max_chars = max(int((node_width - 28) / avg_char_w), 4)
        if len(text) <= max_chars:
            return [text]
        words = text.split()
        lines: list[str] = []
        line = ""
        for word in words:
            if len(word) > max_chars:
                if line:
                    lines.append(line); line = ""
                rem = word
                while len(rem) > max_chars:
                    lines.append(rem[: max_chars - 1] + "-"); rem = rem[max_chars - 1:]
                line = rem
                continue
            test = line + " " + word if line else word
            if len(test) > max_chars and line:
                lines.append(line); line = word
            else:
                line = test
        if line:
            lines.append(line)
        return lines[:4]

    stage_map = {
        node["id"]: max(0, int(round(node.get("median_position", 0) or 0)))
        for node in normalized_nodes
    }
    if stage_map:
        min_stage = min(stage_map.values())
        if min_stage:
            stage_map = {key: value - min_stage for key, value in stage_map.items()}

    nodes_by_stage: dict[int, list[dict[str, Any]]] = {}
    for node in normalized_nodes:
        stage = stage_map.get(node["id"], 0)
        nodes_by_stage.setdefault(stage, []).append(node)
    for stage_nodes in nodes_by_stage.values():
        stage_nodes.sort(
            key=lambda item: (
                -int(item.get("start_count", 0)),
                -int(item.get("frequency", 0)),
                str(item.get("label", "")),
            )
        )

    max_stage = max(nodes_by_stage.keys(), default=0)
    node_max = max((int(node.get("frequency", 0)) for node in normalized_nodes), default=1)
    min_stage_gap = 280  # minimum center-to-center px; gives ~140 px edge-to-edge for typical nodes
    natural_gap = 0 if max_stage == 0 else (width - left_pad - right_pad) / max_stage
    stage_gap = max(natural_gap, float(min_stage_gap)) if max_stage > 0 else 0.0
    # Widen the canvas if the minimum stage gap requires more room than the preset width.
    if max_stage > 0:
        required_width = left_pad + right_pad + max_stage * stage_gap
        if required_width > width:
            width = int(required_width)

    node_pos: dict[str, dict[str, float | int | str]] = {}
    for stage, stage_nodes in sorted(nodes_by_stage.items()):
        x = width / 2 if max_stage == 0 else left_pad + stage * stage_gap
        count = max(len(stage_nodes), 1)
        total_h = count * 200 + max(count - 1, 0) * sibling_gap
        cursor_y = (height - total_h) / 2
        for index, node in enumerate(stage_nodes):
            scale = max(int(node.get("frequency", 0)) / max(node_max, 1), 0.08)
            width_by_frequency = 88 + scale * 56
            width_by_label = max(min(len(str(node.get("label", ""))) * 6.4 + 30, 96), 0)
            box_width = min(max(width_by_frequency + width_by_label, 112), 200)
            y = cursor_y + 100
            cursor_y += 200 + sibling_gap
            node_pos[node["id"]] = {
                "x": x,
                "y": y,
                "stage": stage,
                "order": index,
                "width": box_width,
                "height": 200,
            }

    # Compute anchor positions after node layout so pill clearance uses real widths.
    pill_w, pill_h, pill_r = 55, 20, 10
    max_node_half_w = max((float(pos["width"]) / 2 for pos in node_pos.values()), default=100.0)
    left_anchor_x = max(pill_w / 2 + 6, left_pad - max_node_half_w - 60)
    right_anchor_x = min(float(width) - pill_w / 2 - 6, float(width) - right_pad + max_node_half_w + 60)
    left_anchor = (left_anchor_x, height / 2)
    right_anchor = (right_anchor_x, height / 2)

    def _edge_geometry(source: dict[str, float | int | str], target: dict[str, float | int | str], edge: dict[str, Any]) -> tuple[str, tuple[float, float, float, float, float, float, float, float]]:
        """Return an LTR path: exit right of source, enter left of target."""
        if edge["source"] == edge["target"]:
            return (
                f"M {source['x'] + source['width'] / 2 - 6:.2f} {source['y'] - 8:.2f} "
                f"C {source['x'] + source['width'] / 2 + 54:.2f} {source['y'] - 70:.2f}, "
                f"{source['x'] + source['width'] / 2 + 54:.2f} {source['y'] + 18:.2f}, "
                f"{source['x'] + 4:.2f} {source['y'] + source['height'] / 2:.2f}",
                (
                    source["x"] + source["width"] / 2 - 6,
                    source["y"] - 8,
                    source["x"] + source["width"] / 2 + 54,
                    source["y"] - 70,
                    source["x"] + source["width"] / 2 + 54,
                    source["y"] + 18,
                    source["x"] + 4,
                    source["y"] + source["height"] / 2,
                ),
            )

        if int(source["stage"]) == int(target["stage"]):
            loop_w = 80 + abs(int(source["order"]) - int(target["order"])) * 18
            return (
                f"M {source['x'] - source['width'] / 2:.2f} {source['y']:.2f} "
                f"C {source['x'] - loop_w:.2f} {source['y']:.2f}, "
                f"{target['x'] - loop_w:.2f} {target['y']:.2f}, "
                f"{target['x'] - target['width'] / 2:.2f} {target['y']:.2f}",
                (
                    source["x"] - source["width"] / 2,
                    source["y"],
                    source["x"] - loop_w,
                    source["y"],
                    target["x"] - loop_w,
                    target["y"],
                    target["x"] - target["width"] / 2,
                    target["y"],
                ),
            )

        if int(source["stage"]) > int(target["stage"]):
            outer_y = 34.0 if (source["y"] + target["y"]) / 2 < height / 2 else float(height) - 34
            return (
                f"M {source['x'] - source['width'] / 2:.2f} {source['y']:.2f} "
                f"C {source['x'] - source['width'] / 2 - 44:.2f} {outer_y:.2f}, "
                f"{target['x'] + target['width'] / 2 + 44:.2f} {outer_y:.2f}, "
                f"{target['x'] + target['width'] / 2:.2f} {target['y']:.2f}",
                (
                    source["x"] - source["width"] / 2,
                    source["y"],
                    source["x"] - source["width"] / 2 - 44,
                    outer_y,
                    target["x"] + target["width"] / 2 + 44,
                    outer_y,
                    target["x"] + target["width"] / 2,
                    target["y"],
                ),
            )

        exit_x = float(source["x"]) + float(source["width"]) / 2
        entry_x = float(target["x"]) - float(target["width"]) / 2
        edge_span = max(entry_x - exit_x, 20.0)
        sway = max(min((float(target["y"]) - float(source["y"])) * 0.12, 56.0), -56.0)
        return (
            f"M {exit_x:.2f} {source['y']:.2f} "
            f"C {exit_x + edge_span * 0.45:.2f} {source['y'] + sway:.2f}, "
            f"{entry_x - edge_span * 0.45:.2f} {target['y'] - sway:.2f}, "
            f"{entry_x:.2f} {target['y']:.2f}",
            (
                exit_x,
                source["y"],
                exit_x + edge_span * 0.45,
                source["y"] + sway,
                entry_x - edge_span * 0.45,
                target["y"] - sway,
                entry_x,
                target["y"],
            ),
        )

    def _cubic_point(points: tuple[float, float, float, float, float, float, float, float], t: float) -> tuple[float, float]:
        x0, y0, cx1, cy1, cx2, cy2, x1, y1 = points
        mt = 1 - t
        x = (mt ** 3) * x0 + 3 * (mt ** 2) * t * cx1 + 3 * mt * (t ** 2) * cx2 + (t ** 3) * x1
        y = (mt ** 3) * y0 + 3 * (mt ** 2) * t * cy1 + 3 * mt * (t ** 2) * cy2 + (t ** 3) * y1
        return x, y

    edge_max = max((int(edge.get("frequency", 0)) for edge in normalized_edges), default=1)
    guide_lines = []
    for stage in range(max_stage + 1):
        x = width / 2 if max_stage == 0 else left_pad + stage * stage_gap
        guide_lines.append(
            f"<line x1=\"{x:.2f}\" y1=\"34\" x2=\"{x:.2f}\" y2=\"{height - 34}\" stroke=\"rgba(0,0,0,0.06)\" stroke-width=\"1\"/>"
        )

    anchor_marks = [
        f"<rect x=\"{left_anchor[0] - pill_w / 2:.2f}\" y=\"{left_anchor[1] - pill_h / 2:.2f}\" width=\"{pill_w}\" height=\"{pill_h}\" rx=\"{pill_r}\" fill=\"rgba(0,51,153,0.1)\" stroke=\"rgba(0,51,153,0.24)\"/>",
        f"<rect x=\"{right_anchor[0] - pill_w / 2:.2f}\" y=\"{right_anchor[1] - pill_h / 2:.2f}\" width=\"{pill_w}\" height=\"{pill_h}\" rx=\"{pill_r}\" fill=\"rgba(0,51,153,0.1)\" stroke=\"rgba(0,51,153,0.24)\"/>",
        f"<text x=\"{left_anchor[0]:.2f}\" y=\"{left_anchor[1]:.2f}\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\"13\" fill=\"#003399\" font-family=\"IBM Plex Mono, monospace\">START</text>",
        f"<text x=\"{right_anchor[0]:.2f}\" y=\"{right_anchor[1]:.2f}\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\"13\" fill=\"#003399\" font-family=\"IBM Plex Mono, monospace\">END</text>",
    ]

    top_start_count = max((int(node.get("start_count", 0)) for node in normalized_nodes), default=1)
    top_end_count = max((int(node.get("end_count", 0)) for node in normalized_nodes), default=1)
    start_end_lines: list[str] = []
    for node in normalized_nodes:
        pos = node_pos.get(node["id"])
        if not pos:
            continue
        pill_half = pill_w / 2
        if int(node.get("start_count", 0)) > 0:
            strength = max(int(node.get("start_count", 0)) / max(top_start_count, 1), 0.08)
            start_end_lines.append(
                f"<path d=\"M {left_anchor[0] + pill_half:.2f} {left_anchor[1]:.2f} "
                f"C {left_anchor[0] + pill_half * 2:.2f} {left_anchor[1]:.2f}, "
                f"{pos['x'] - pos['width'] / 2 - 52:.2f} {pos['y']:.2f}, "
                f"{pos['x'] - pos['width'] / 2:.2f} {pos['y']:.2f}\" "
                f"fill=\"none\" stroke=\"rgba(0,51,153,{0.18 + strength * 0.34:.2f})\" "
                f"stroke-width=\"{1 + strength * 5:.2f}\" opacity=\"0.7\"/>"
            )
        if int(node.get("end_count", 0)) > 0:
            strength = max(int(node.get("end_count", 0)) / max(top_end_count, 1), 0.08)
            start_end_lines.append(
                f"<path d=\"M {pos['x'] + pos['width'] / 2:.2f} {pos['y']:.2f} "
                f"C {pos['x'] + pos['width'] / 2 + 52:.2f} {pos['y']:.2f}, "
                f"{right_anchor[0] - pill_half * 2:.2f} {right_anchor[1]:.2f}, "
                f"{right_anchor[0] - pill_half:.2f} {right_anchor[1]:.2f}\" "
                f"fill=\"none\" stroke=\"rgba(0,51,153,{0.16 + strength * 0.30:.2f})\" "
                f"stroke-width=\"{1 + strength * 5:.2f}\" opacity=\"0.7\"/>"
            )

    edge_lines: list[str] = []
    edge_labels: list[str] = []
    for edge in normalized_edges[:220]:
        source_pos = node_pos.get(edge["source"])
        target_pos = node_pos.get(edge["target"])
        if not source_pos or not target_pos:
            continue
        path_d, curve_points = _edge_geometry(source_pos, target_pos, edge)
        frequency = int(edge.get("frequency", 0))
        strength = max(frequency / max(edge_max, 1), 0.05)
        stroke_width = 1.2 + strength * 10
        stroke = f"rgba(0, 0, 0, {0.24 + strength * 0.46:.2f})"
        edge_lines.append(
            f"<path d=\"{path_d}\" fill=\"none\" stroke=\"{stroke}\" "
            f"stroke-width=\"{stroke_width:.2f}\" opacity=\"0.82\" marker-end=\"url(#process-arrowhead-report)\"/>"
        )
        if len(edge_labels) < 26:
            lx, ly = _cubic_point(curve_points, 0.5)
            edge_labels.append(
                f"<text x=\"{lx:.2f}\" y=\"{ly - 4:.2f}\" text-anchor=\"middle\" "
                "font-size=\"25\" fill=\"#111111\" font-family=\"IBM Plex Mono, monospace\">"
                f"{_format_int(frequency)}</text>"
            )

    node_marks: list[str] = []
    for node in normalized_nodes:
        pos = node_pos.get(node["id"])
        if not pos:
            continue
        scale = max(int(node.get("frequency", 0)) / max(node_max, 1), 0.08)
        fill_opacity = 0.12 + scale * 0.86
        text_color = "#ffffff" if fill_opacity > 0.45 else "#001033"
        raw_label = str(node.get("label", ""))
        label_lines = _wrap_label(raw_label, float(pos["width"]), 30)
        marker = ""
        if int(node.get("start_count", 0)) > 0 and int(node.get("end_count", 0)) > 0:
            marker = " | S/E"
        elif int(node.get("start_count", 0)) > 0:
            marker = " | S"
        elif int(node.get("end_count", 0)) > 0:
            marker = " | E"
        node_marks.append(
            f"<rect x=\"{pos['x'] - pos['width'] / 2:.2f}\" y=\"{pos['y'] - pos['height'] / 2:.2f}\" "
            f"width=\"{pos['width']:.2f}\" height=\"{pos['height']:.2f}\" rx=\"12\" "
            f"fill=\"rgba(0,51,153,{fill_opacity:.2f})\" "
            f"stroke=\"{'#001a66' if int(node.get('start_count', 0)) > 0 or int(node.get('end_count', 0)) > 0 else 'rgba(0,51,153,0.34)'}\" "
            f"stroke-width=\"{'2.4' if int(node.get('start_count', 0)) > 0 or int(node.get('end_count', 0)) > 0 else '1.6'}\"/>"
        )
        line_h, stat_gap = 36, 32
        first_label_y = round(pos["y"] - ((len(label_lines) - 1) * line_h + stat_gap - 17) / 2)
        stat_y = first_label_y + (len(label_lines) - 1) * line_h + stat_gap
        tspans = "".join(
            f"<tspan x=\"{pos['x']:.2f}\" y=\"{first_label_y + i * line_h:.2f}\">{escape(ln)}</tspan>"
            for i, ln in enumerate(label_lines)
        )
        node_marks.append(
            f"<text text-anchor=\"middle\" font-size=\"30\" font-family=\"Space Grotesk, sans-serif\" "
            f"font-weight=\"700\" fill=\"{text_color}\">{tspans}</text>"
        )
        node_marks.append(
            f"<text x=\"{pos['x']:.2f}\" y=\"{stat_y:.2f}\" text-anchor=\"middle\" "
            f"font-size=\"25\" font-family=\"IBM Plex Mono, monospace\" fill=\"{text_color}\">{_format_int(node.get('frequency'))}{escape(marker)}</text>"
        )

    return (
        "<div class=\"map-wrap\">"
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Process map snapshot\">"
        "<defs>"
        "<marker id=\"process-arrowhead-report\" viewBox=\"0 0 10 10\" refX=\"10\" refY=\"5\" markerUnits=\"userSpaceOnUse\" markerWidth=\"27\" markerHeight=\"27\" orient=\"auto-start-reverse\">"
        "<path d=\"M 0 0 L 10 5 L 0 10 z\" fill=\"#111111\"/>"
        "</marker>"
        "</defs>"
        + "".join(guide_lines)
        + "".join(anchor_marks)
        + "".join(start_end_lines)
        + "".join(edge_lines)
        + "".join(edge_labels)
        + "".join(node_marks)
        + "</svg></div>"
    )


def _build_html_report(
    *,
    filename: str,
    log_id: str,
    exported_at: str,
    filters: dict[str, Any],
    dashboard: dict[str, Any],
    animation: dict[str, Any],
    conformance: dict[str, Any] | None,
    mermaid_exports: dict[str, str] | None = None,
    bpmn_model: dict[str, Any] | None = None,
) -> str:
    """Create the self-contained HTML export.

    The report intentionally embeds plain tables, Mermaid source blocks, BPMN
    XML, and a static SVG map so the downloaded file can be opened without the
    local server running.
    """

    summary = dashboard.get("summary", {})
    nodes = dashboard.get("nodes", [])
    edges = dashboard.get("edges", [])
    variants = dashboard.get("variants", [])
    bottlenecks = dashboard.get("bottlenecks", [])
    activity_stats = dashboard.get("activity_stats", [])
    handoff = dashboard.get("handoff", {})
    bpmn_flowchart = dashboard.get("swimlane", {})
    sankey = dashboard.get("sankey", {})
    rework = dashboard.get("rework", {})
    recommendations = dashboard.get("recommendations", [])

    summary_cards = [
        ("Cases", _format_int(summary.get("total_cases"))),
        ("Events", _format_int(summary.get("total_events"))),
        ("Activities", _format_int(summary.get("activities"))),
        ("Median Case Duration (h)", _format_decimal(summary.get("median_case_duration_hours"))),
        ("Average Case Duration (h)", _format_decimal(summary.get("avg_case_duration_hours"))),
        ("Median Events / Case", _format_decimal(summary.get("median_events_per_case"))),
        (
            "Rework Case Ratio",
            _format_percent(summary.get("rework_case_ratio"), 2),
        ),
        ("Start Time", escape(str(summary.get("start_time") or "-"))),
        ("End Time", escape(str(summary.get("end_time") or "-"))),
    ]
    summary_cards_html = "".join(
        "<article class=\"metric\">"
        f"<div class=\"metric-label\">{escape(label)}</div>"
        f"<div class=\"metric-value\">{value}</div>"
        "</article>"
        for label, value in summary_cards
    )

    top_edges_table = _html_table(
        ["Path", "Frequency", "Median Wait", "p90 Wait"],
        [
            [
                escape(f"{edge.get('source', '')} -> {edge.get('target', '')}"),
                _format_int(edge.get("frequency")),
                _format_seconds_human(edge.get("median_duration_seconds")),
                _format_seconds_human(edge.get("p90_duration_seconds")),
            ]
            for edge in edges[:160]
        ],
    )
    variants_table = _html_table(
        ["Rank", "Variant", "Cases", "Share", "Median Duration (h)"],
        [
            [
                _format_int(variant.get("rank")),
                escape(str(variant.get("variant", ""))),
                _format_int(variant.get("cases")),
                _format_percent(variant.get("share"), 2),
                _format_decimal(variant.get("median_duration_hours")),
            ]
            for variant in variants
        ],
    )
    bottlenecks_table = _html_table(
        ["Path", "Median Wait", "p90 Wait", "Frequency"],
        [
            [
                escape(f"{edge.get('source', '')} -> {edge.get('target', '')}"),
                _format_seconds_human(edge.get("median_duration_seconds")),
                _format_seconds_human(edge.get("p90_duration_seconds")),
                _format_int(edge.get("frequency")),
            ]
            for edge in bottlenecks
        ],
    )
    activity_table = _html_table(
        ["Activity", "Frequency", "Case Coverage"],
        [
            [
                escape(str(item.get("activity", ""))),
                _format_int(item.get("frequency")),
                _format_percent(item.get("case_coverage"), 2),
            ]
            for item in activity_stats
        ],
    )
    handoff_actor_table = _html_table(
        ["From Actor", "To Actor", "Frequency", "Median Wait"],
        [
            [
                escape(str(edge.get("source", ""))),
                escape(str(edge.get("target", ""))),
                _format_int(edge.get("frequency")),
                _format_seconds_human(edge.get("median_duration_seconds")),
            ]
            for edge in handoff.get("actor_view", {}).get("edges", [])
        ],
    )
    handoff_activity_table = _html_table(
        ["From Activity", "To Activity", "Frequency", "Median Wait"],
        [
            [
                escape(str(edge.get("source", ""))),
                escape(str(edge.get("target", ""))),
                _format_int(edge.get("frequency")),
                _format_seconds_human(edge.get("median_duration_seconds")),
            ]
            for edge in handoff.get("activity_view", {}).get("edges", [])
        ],
    )
    bpmn_flowchart_table = _html_table(
        ["Activity", "Events", "Cases", "Case Coverage", "Starts", "Ends"],
        [
            [
                escape(str(node.get("activity", node.get("label", "")))),
                _format_int(node.get("frequency")),
                _format_int(node.get("case_frequency")),
                _format_percent(node.get("case_coverage"), 2),
                _format_int(node.get("start_count")),
                _format_int(node.get("end_count")),
            ]
            for node in bpmn_flowchart.get("nodes", [])
        ],
    )
    sankey_table = _html_table(
        ["Source", "Target", "Flow", "Median Wait"],
        [
            [
                escape(str(link.get("source", ""))),
                escape(str(link.get("target", ""))),
                _format_int(link.get("value")),
                _format_seconds_human(link.get("median_duration_seconds")),
            ]
            for link in sankey.get("links", [])
        ],
    )
    rework_table = _html_table(
        ["Activity", "Cases With Rework", "Rework Events", "Rework Case Ratio"],
        [
            [
                escape(str(item.get("activity", ""))),
                _format_int(item.get("cases_with_rework")),
                _format_int(item.get("rework_events")),
                _format_percent(item.get("rework_case_ratio"), 2),
            ]
            for item in rework.get("activities", [])
        ],
    )

    conformance_html = "<p class=\"empty\">Conformance was not requested for this export.</p>"
    if conformance is not None:
        if conformance.get("supported"):
            conformance_html = (
                "<div class=\"conformance\">"
                f"<div><strong>Fitness:</strong> {_format_decimal(conformance.get('fitness'), 4)}</div>"
                f"<div><strong>Precision:</strong> {_format_decimal(conformance.get('precision'), 4)}</div>"
                f"<div><strong>Model:</strong> {_format_int(conformance.get('model', {}).get('places'))} places, "
                f"{_format_int(conformance.get('model', {}).get('transitions'))} transitions, "
                f"{_format_int(conformance.get('model', {}).get('arcs'))} arcs</div>"
                f"<div><strong>Cases:</strong> {_format_int(conformance.get('cases'))} | "
                f"<strong>Events:</strong> {_format_int(conformance.get('events'))}</div>"
                "</div>"
            )
        else:
            conformance_html = (
                "<p class=\"empty\">"
                + escape(str(conformance.get("message") or "Conformance metrics unavailable."))
                + "</p>"
            )

    animation_html = (
        "<div class=\"conformance\">"
        f"<div><strong>Frames:</strong> {_format_int(animation.get('frame_count'))}</div>"
        f"<div><strong>Frame interval:</strong> {_format_seconds_human(animation.get('frame_interval_seconds'))}</div>"
        f"<div><strong>Max transitions / frame:</strong> {_format_int(animation.get('max_total_transitions_per_frame'))}</div>"
        f"<div><strong>Animation range:</strong> {escape(str(animation.get('start_time') or '-'))} "
        f"to {escape(str(animation.get('end_time') or '-'))}</div>"
        "</div>"
    )
    recommendation_html = "".join(
        "<li>"
        f"<strong>{escape(str(item.get('title', '')))}:</strong> "
        f"{escape(str(item.get('why', '')))}"
        "</li>"
        for item in recommendations
    ) or "<li>No additional recommendations for this filter state.</li>"

    mermaid_section = "<p class=\"empty\">No Mermaid exports in this report.</p>"
    if mermaid_exports:
        mermaid_blocks = []
        for name, body in mermaid_exports.items():
            mermaid_blocks.append(
                f"<h3>{escape(name)}</h3><pre>{escape(body)}</pre>"
            )
        mermaid_section = "".join(mermaid_blocks)

    bpmn_section = "<p class=\"empty\">BPMN export not available.</p>"
    if bpmn_model:
        if bpmn_model.get("available") and bpmn_model.get("xml"):
            bpmn_section = f"<pre>{escape(str(bpmn_model.get('xml')))}</pre>"
        else:
            bpmn_section = (
                "<p class=\"empty\">"
                + escape(str(bpmn_model.get("message", "BPMN not available.")))
                + "</p>"
            )

    filters_json = escape(json.dumps(filters, indent=2, default=str))
    title = escape(Path(filename).name)

    # The CSS is inlined on purpose. A report downloaded from the app should
    # remain readable when emailed or opened from a different folder.
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>{title} - Process Analysis Report</title>"
        "<style>"
        ":root{--ink:#142027;--muted:#5b6d77;--line:#d1dde3;--panel:#f8fcff;--brand:#0b7a75;--bg:#eef4f7}"
        "*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}"
        ".page{max-width:1600px;margin:0 auto;padding:18px}.hero{background:linear-gradient(120deg,#0b7a75,#116087);color:#f7fffe;border-radius:16px;padding:16px 20px}"
        ".subtitle{opacity:.9}.meta{font-size:.9rem;opacity:.9}.grid{display:grid;gap:12px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-top:12px}"
        ".metric{background:#fff;border:1px solid #dce8ee;border-radius:12px;padding:10px}.metric-label{font-size:.72rem;text-transform:uppercase;color:#50707f;letter-spacing:.06em}.metric-value{margin-top:6px;font-weight:700;font-size:1.2rem}"
        ".card{background:var(--panel);border:1px solid #d7e3ea;border-radius:14px;padding:12px;margin-top:12px}"
        ".card h2{margin:0 0 8px 0;font-size:1rem}.map-wrap{border:1px solid #d7e5eb;border-radius:12px;background:#fff;overflow:hidden}.map-wrap svg{width:100%;height:auto;display:block}"
        ".table-wrap{overflow:auto;max-height:420px}table{width:100%;border-collapse:collapse;font-size:.84rem}th,td{text-align:left;padding:8px;border-bottom:1px solid #e0eaef;vertical-align:top}"
        "th{position:sticky;top:0;background:#f6fbfd;font-size:.72rem;text-transform:uppercase;color:#4d6674}.empty{color:var(--muted);font-size:.9rem}"
        ".split{display:grid;grid-template-columns:1fr 1fr;gap:12px}.conformance{display:grid;gap:6px;font-size:.9rem;background:#fff;border:1px solid #dce8ee;border-radius:10px;padding:10px}"
        "pre{margin:0;background:#0f1d24;color:#d7f4ff;border-radius:10px;padding:10px;overflow:auto;font-size:.76rem}"
        "@media(max-width:1200px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.split{grid-template-columns:1fr}}"
        "@media(max-width:760px){.metrics{grid-template-columns:1fr}}"
        "</style></head><body><main class=\"page\">"
        "<header class=\"hero\">"
        f"<h1 style=\"margin:0 0 8px 0;\">Process Analysis Report</h1>"
        f"<div class=\"subtitle\">{title}</div>"
        f"<div class=\"meta\">Exported at: {escape(exported_at)} | Log ID: {escape(log_id)}</div>"
        "</header>"
        "<section class=\"grid metrics\">"
        + summary_cards_html
        + "</section>"
        "<section class=\"card\"><h2>Process Map Snapshot</h2>"
        + _report_map_svg(nodes, edges)
        + "</section>"
        "<section class=\"split\">"
        "<section class=\"card\"><h2>Conformance</h2>"
        + conformance_html
        + "</section>"
        "<section class=\"card\"><h2>Animation Summary</h2>"
        + animation_html
        + "</section>"
        "</section>"
        "<section class=\"card\"><h2>Top Paths</h2>"
        + top_edges_table
        + "</section>"
        "<section class=\"card\"><h2>Variants</h2>"
        + variants_table
        + "</section>"
        "<section class=\"card\"><h2>Bottlenecks</h2>"
        + bottlenecks_table
        + "</section>"
        "<section class=\"card\"><h2>Activity Statistics</h2>"
        + activity_table
        + "</section>"
        "<section class=\"card\"><h2>Actor Handoff (Actor Focused)</h2>"
        + handoff_actor_table
        + "</section>"
        "<section class=\"card\"><h2>Actor Handoff (Activity Focused)</h2>"
        + handoff_activity_table
        + "</section>"
        "<section class=\"card\"><h2>BPMN-Style Flowchart Data</h2>"
        + bpmn_flowchart_table
        + "</section>"
        "<section class=\"card\"><h2>Sankey View Data</h2>"
        + sankey_table
        + "</section>"
        "<section class=\"card\"><h2>Rework View</h2>"
        + rework_table
        + "</section>"
        "<section class=\"card\"><h2>Recommended Additional Views</h2><ul>"
        + recommendation_html
        + "</ul></section>"
        "<section class=\"card\"><h2>Mermaid Diagrams</h2>"
        + mermaid_section
        + "</section>"
        "<section class=\"card\"><h2>BPMN XML</h2>"
        + bpmn_section
        + "</section>"
        "<section class=\"card\"><h2>Applied Filters (JSON)</h2>"
        f"<pre>{filters_json}</pre>"
        "</section>"
        "</main></body></html>"
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Project management endpoints
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str


@app.post("/api/projects")
def create_project(body: CreateProjectRequest, request: Request) -> dict:
    """Create a named project scoped to the current user."""
    owner = _owner(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")

    project_id = str(uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(insert(projects).values(id=project_id, name=name, owner=owner))
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"You already have a project named '{name}'") from exc
        raise

    logger.info("Created project %s (%s) for %s", project_id, name, owner)
    return {"project_id": project_id, "name": name}


@app.get("/api/projects")
def list_projects(request: Request) -> dict:
    """Return projects belonging to the current user, newest first."""
    owner = _owner(request)
    with engine.connect() as conn:
        rows = conn.execute(
            select(projects)
            .where(projects.c.owner == owner)
            .order_by(projects.c.created_at.desc())
        ).mappings().fetchall()

    return {
        "projects": [
            {
                "project_id": str(row["id"]),
                "name": row["name"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
    }


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, request: Request) -> dict:
    """Delete a project and all its logs. Owner-scoped."""
    owner = _owner(request)
    logger.info("DELETE project %s owner=%s", project_id, owner)
    with engine.begin() as conn:
        proj = conn.execute(
            select(projects.c.id)
            .where(projects.c.id == project_id)
            .where(projects.c.owner == owner)
        ).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        log_ids = [
            str(r.id) for r in conn.execute(
                select(logs.c.id)
                .where(logs.c.project_id == project_id)
                .where(logs.c.owner == owner)
            ).fetchall()
        ]

        conn.execute(
            delete(logs)
            .where(logs.c.project_id == project_id)
            .where(logs.c.owner == owner)
        )
        conn.execute(
            delete(projects)
            .where(projects.c.id == project_id)
            .where(projects.c.owner == owner)
        )

    for log_id in log_ids:
        LOG_STORE.pop(log_id, None)

    logger.info("Deleted project %s with %d log(s)", project_id, len(log_ids))
    return {"deleted": project_id, "logs_deleted": len(log_ids)}


@app.get("/api/projects/{project_id}/logs")
def list_project_logs(project_id: str, request: Request) -> dict:
    """Return all logs in a project owned by the current user, newest first."""
    owner = _owner(request)
    with engine.connect() as conn:
        proj = conn.execute(
            select(projects.c.id)
            .where(projects.c.id == project_id)
            .where(projects.c.owner == owner)
        ).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        rows = conn.execute(
            select(logs.c.id, logs.c.filename, logs.c.file_format, logs.c.uploaded_at)
            .where(logs.c.project_id == project_id)
            .where(logs.c.owner == owner)
            .order_by(logs.c.uploaded_at.desc())
        ).mappings().fetchall()

    return {
        "project_id": project_id,
        "logs": [
            {
                "log_id": str(row["id"]),
                "filename": row["filename"],
                "file_format": row["file_format"],
                "uploaded_at": row["uploaded_at"].isoformat(),
            }
            for row in rows
        ],
    }


@app.post("/api/projects/{project_id}/logs/{log_id}/assign")
def assign_log_to_project(project_id: str, log_id: str, request: Request) -> dict:
    """Assign an uploaded log to a project (both must belong to current user)."""
    from sqlalchemy import update as sql_update
    owner = _owner(request)
    with engine.connect() as conn:
        exists = conn.execute(
            select(projects.c.id)
            .where(projects.c.id == project_id)
            .where(projects.c.owner == owner)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Project not found")

    with engine.begin() as conn:
        result = conn.execute(
            sql_update(logs)
            .where(logs.c.id == log_id)
            .where(logs.c.owner == owner)
            .values(project_id=project_id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Log not found")

    logger.info("Assigned log %s to project %s", log_id, project_id)
    return {"log_id": log_id, "project_id": project_id}


@app.delete("/api/projects/{project_id}/logs/{log_id}")
def delete_project_log(project_id: str, log_id: str, request: Request) -> dict:
    """Permanently delete a log from a project. Owner-scoped; also evicts the in-memory cache."""
    owner = _owner(request)
    logger.info("DELETE log %s from project %s owner=%s", log_id, project_id, owner)
    with engine.begin() as conn:
        result = conn.execute(
            delete(logs)
            .where(logs.c.id == log_id)
            .where(logs.c.owner == owner)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Log not found")

    LOG_STORE.pop(log_id, None)
    logger.info("Deleted log %s from project %s", log_id, project_id)
    return {"deleted": log_id}


@app.get("/api/health")
def health() -> dict[str, Any]:
    log_count = len(LOG_STORE)
    logger.debug("Health check — %d log(s) in memory", log_count)
    return {"status": "ok", "logs_in_memory": log_count}


@app.post("/api/logs/upload")
async def upload_log(
    request: Request,
    file: UploadFile = File(...),
    case_id_col: str = Form(""),
    activity_col: str = Form(""),
    start_timestamp_col: str = Form(""),
    stop_timestamp_col: str = Form(""),
    actor_col: str = Form(""),
    informational_cols: str = Form(""),
    filter_only_cols: str = Form(""),
    timestamp_col: str = Form(""),
) -> dict:
    """Upload and normalize a CSV/XES event log.

    CSV uploads use either explicit column selections or the mapping heuristic
    from ``analytics.suggest_csv_mapping``. XES uploads are already semantic
    event logs, so the backend only normalizes them into the shared dataframe
    shape.
    """

    filename = file.filename or "event_log"
    content = await file.read()
    content_size_kb = len(content) / 1024

    logger.info(
        "Upload received: %s (%.1f KB, format=%s)",
        filename,
        content_size_kb,
        Path(filename).suffix.lower(),
    )

    if not content:
        logger.warning("Upload rejected — empty file: %s", filename)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    suffix = Path(filename).suffix.lower()
    mapping_preview: dict[str, Any] | None = None

    try:
        with _log_timer("parse_event_log", filename=filename, format=suffix):
            if suffix == ".csv":
                mapping_preview = suggest_csv_mapping(content)
                dataframe = load_csv_bytes(
                    content,
                    case_id_col=case_id_col,
                    activity_col=activity_col,
                    timestamp_col=timestamp_col,
                    start_timestamp_col=start_timestamp_col,
                    stop_timestamp_col=stop_timestamp_col,
                    actor_col=actor_col,
                )
            elif suffix == ".xes":
                dataframe = load_xes_bytes(content)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file format. Use .csv or .xes",
                )
    except AnalyticsError as exc:
        logger.error("Upload parse error for %s: %s", filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Parsed %s: %d rows, %d columns",
        filename,
        len(dataframe),
        len(dataframe.columns),
    )

    suggestions = (mapping_preview or {}).get("suggestions", {})
    available_columns = set((mapping_preview or {}).get("columns", []))

    def _effective_mapping(input_value: str, mapping_key: str) -> str | None:
        """Prefer an explicit UI choice, then fall back to CSV suggestions."""
        cleaned = input_value.strip()
        if cleaned and cleaned in available_columns:
            return cleaned
        suggested = suggestions.get(mapping_key)
        if suggested and suggested in available_columns:
            return suggested
        return cleaned or None

    column_mapping = {
        "case_id_col": _effective_mapping(case_id_col, "case_id_col"),
        "activity_col": _effective_mapping(activity_col, "activity_col"),
        "start_timestamp_col": _effective_mapping(
            start_timestamp_col or timestamp_col, "start_timestamp_col"
        ),
        "stop_timestamp_col": _effective_mapping(stop_timestamp_col, "stop_timestamp_col"),
        "actor_col": _effective_mapping(actor_col, "actor_col"),
    }
    if not column_mapping["start_timestamp_col"] and column_mapping["stop_timestamp_col"]:
        # The UI contract says a one-timestamp log should behave like a start
        # timestamp log. This fallback also handles stop-only source files.
        column_mapping["start_timestamp_col"] = column_mapping["stop_timestamp_col"]
        column_mapping["stop_timestamp_col"] = None

    # Informational columns are profiled but not treated as process semantics.
    # Filter-only columns additionally become dynamic filter controls in the UI.
    requested_info_columns = _parse_column_list(informational_cols)
    requested_filter_columns = _parse_column_list(filter_only_cols)
    if not requested_info_columns and mapping_preview:
        requested_info_columns = list(
            (mapping_preview.get("suggested_informational_columns") or [])
        )
    if not requested_filter_columns and mapping_preview:
        requested_filter_columns = list(
            (mapping_preview.get("suggested_filter_only_columns") or [])
        )

    blocked_columns = {
        (column_mapping.get("case_id_col") or "").strip(),
        (column_mapping.get("activity_col") or "").strip(),
        (column_mapping.get("start_timestamp_col") or "").strip(),
        (column_mapping.get("stop_timestamp_col") or "").strip(),
        (column_mapping.get("actor_col") or "").strip(),
    }
    informational_columns, missing_info = _resolve_existing_columns(
        dataframe, requested_info_columns, blocked=blocked_columns
    )
    filter_only_columns, missing_filter_only = _resolve_existing_columns(
        dataframe, requested_filter_columns, blocked=blocked_columns
    )

    mapping_warnings: list[str] = []
    if missing_info:
        mapping_warnings.append(
            "Ignored informational columns not found in log: " + ", ".join(missing_info)
        )
    if missing_filter_only:
        mapping_warnings.append(
            "Ignored filter-only columns not found in log: "
            + ", ".join(missing_filter_only)
        )
    if suffix == ".csv" and mapping_preview:
        for key in ("case_id_col", "activity_col", "start_timestamp_col"):
            if not (column_mapping.get(key) or "").strip():
                mapping_warnings.append(
                    f"Could not confidently detect {key.replace('_col', '').replace('_', ' ')}."
                )
    filter_only_values = attribute_filter_options(dataframe, filter_only_columns)

    log_id = str(uuid4())
    uploaded_at = datetime.now(timezone.utc)
    owner = _owner(request)

    with engine.begin() as conn:
        conn.execute(insert(logs).values(
            id=log_id,
            project_id=None,
            owner=owner,
            filename=filename,
            file_data=content,
            file_format=suffix.lstrip("."),
            column_mapping=column_mapping,
            informational_columns=informational_columns,
            filter_only_columns=filter_only_columns,
            filter_only_values=filter_only_values,
            mapping_warnings=mapping_warnings,
        ))

    LOG_STORE[log_id] = StoredLog(
        log_id=log_id,
        filename=filename,
        dataframe=dataframe,
        uploaded_at=uploaded_at,
        column_mapping=column_mapping,
        informational_columns=informational_columns,
        filter_only_columns=filter_only_columns,
        filter_only_values=filter_only_values,
        mapping_warnings=mapping_warnings,
        owner=owner,
    )
    logger.info(
        "Stored log %s (%s) — %d rows, info_cols=%d, filter_cols=%d, warnings=%d",
        log_id,
        filename,
        len(dataframe),
        len(informational_columns),
        len(filter_only_columns),
        len(mapping_warnings),
    )

    with _log_timer("initial_dashboard", log_id=log_id):
        payload = dashboard_payload(dataframe, FilterSpec())

    return {
        "log_id": log_id,
        "filename": filename,
        "uploaded_at": LOG_STORE[log_id].uploaded_at.isoformat(),
        "summary": payload["summary"],
        "activities": available_activities(dataframe),
        "column_mapping": column_mapping,
        "informational_columns": informational_columns,
        "filter_only_columns": filter_only_columns,
        "attribute_filter_options": filter_only_values,
        "informational_columns_profile": informational_column_profile(
            dataframe, informational_columns
        ),
        "mapping_warnings": mapping_warnings,
    }


@app.post("/api/logs/suggest-mapping")
async def suggest_log_mapping(file: UploadFile = File(...)) -> dict[str, Any]:
    """Return CSV column-mapping suggestions before the log is loaded."""
    filename = file.filename or "event_log"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    suffix = Path(filename).suffix.lower()
    if suffix != ".csv":
        return {
            "filename": filename,
            "supported": False,
            "message": "Auto-suggestion is available for CSV uploads.",
            "mapping": {
                "columns": [],
                "suggestions": {},
                "confidence": {},
                "candidates": {},
                "suggested_filter_only_columns": [],
                "suggested_informational_columns": [],
            },
        }

    try:
        mapping = suggest_csv_mapping(content)
    except AnalyticsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "filename": filename,
        "supported": True,
        "mapping": mapping,
    }


@app.get("/api/logs")
def list_logs(request: Request) -> dict:
    """Expose currently uploaded logs for lightweight debugging."""
    owner = _owner(request)
    return {
        "logs": [
            {
                "log_id": record.log_id,
                "filename": record.filename,
                "uploaded_at": record.uploaded_at.isoformat(),
            }
            for record in LOG_STORE.values()
            if record.owner == owner
        ]
    }


@app.get("/api/logs/{log_id}/overview")
def log_overview(log_id: str, request: Request) -> dict:
    """Return the unfiltered summary and import metadata for a stored log."""
    record = _get_log_or_404(log_id, _owner(request))
    payload = dashboard_payload(record.dataframe, FilterSpec())

    return {
        "log_id": log_id,
        "filename": record.filename,
        "summary": payload["summary"],
        "activities": available_activities(record.dataframe),
        "column_mapping": record.column_mapping,
        "informational_columns": record.informational_columns,
        "filter_only_columns": record.filter_only_columns,
        "attribute_filter_options": record.filter_only_values,
        "informational_columns_profile": informational_column_profile(
            record.dataframe, record.informational_columns
        ),
        "mapping_warnings": record.mapping_warnings,
    }


@app.post("/api/logs/{log_id}/dashboard")
def log_dashboard(log_id: str, filters: DashboardFilterRequest, request: Request) -> dict:
    """Build the filtered dashboard payload consumed by the frontend."""
    record = _get_log_or_404(log_id, _owner(request))

    try:
        filter_spec = filters.to_filter_spec()
        with _log_timer("dashboard_payload", log_id=log_id):
            dashboard = dashboard_payload(record.dataframe, filter_spec)

        # Reuse the already-filtered events from dashboard_payload instead of
        # calling apply_filters a second time.  We apply filters once more
        # only for the informational column profile (lightweight).
        with _log_timer("informational_profile", log_id=log_id):
            filtered = apply_filters(record.dataframe, filter_spec)
            info_profile = informational_column_profile(
                filtered, record.informational_columns
            )

        return {
            "log_id": log_id,
            "filename": record.filename,
            "filters": filters.model_dump(),
            "dashboard": dashboard,
            "column_mapping": record.column_mapping,
            "informational_columns": record.informational_columns,
            "filter_only_columns": record.filter_only_columns,
            "attribute_filter_options": record.filter_only_values,
            "informational_columns_profile": info_profile,
            "mapping_warnings": record.mapping_warnings,
        }
    except AnalyticsError as exc:
        logger.error("Dashboard error for %s: %s", log_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/logs/{log_id}/conformance")
def log_conformance(log_id: str, filters: DashboardFilterRequest, request: Request) -> dict:
    """Run optional pm4py conformance checks for the current filter state."""
    record = _get_log_or_404(log_id, _owner(request))

    try:
        with _log_timer("conformance", log_id=log_id):
            result = conformance_payload(record.dataframe, filters.to_filter_spec())
        logger.info(
            "Conformance result for %s: supported=%s",
            log_id,
            result.get("supported"),
        )
        return {
            "log_id": log_id,
            "filename": record.filename,
            "filters": filters.model_dump(),
            "conformance": result,
        }
    except AnalyticsError as exc:
        logger.error("Conformance error for %s: %s", log_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/logs/{log_id}/animation")
def log_animation(
    log_id: str, filters: DashboardFilterRequest, request: Request, frame_count: int = 80
) -> dict:
    """Return synchronized animation payloads for process and handoff maps."""
    record = _get_log_or_404(log_id, _owner(request))

    try:
        with _log_timer("animation", log_id=log_id, frame_count=frame_count):
            animations = animation_views_payload(
                record.dataframe, filters.to_filter_spec(), frame_count=frame_count
            )
            anim = animations.get("views", {}).get("process", {})
        logger.debug(
            "Animation for %s: %d frames generated",
            log_id,
            anim.get("frame_count", 0),
        )
        return {
            "log_id": log_id,
            "filename": record.filename,
            "filters": filters.model_dump(),
            "animation": anim,
            "animations": animations.get("views", {}),
            "timeline_mode": animations.get("timeline_mode"),
            "normalized_case_start": animations.get("normalized_case_start", False),
        }
    except AnalyticsError as exc:
        logger.error("Animation error for %s: %s", log_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _collect_export_data(
    *,
    record: StoredLog,
    filters: DashboardFilterRequest,
    include_conformance: bool,
) -> dict[str, Any]:
    """Collect every analysis artifact shared by ZIP and HTML exports."""
    filter_spec = filters.to_filter_spec()
    dashboard = dashboard_payload(record.dataframe, filter_spec)
    animation = animation_payload(record.dataframe, filter_spec, frame_count=80)
    filtered_events = apply_filters(record.dataframe, filter_spec)
    informational_profile = informational_column_profile(
        filtered_events, record.informational_columns
    )
    disco_csv_exports = disco_csv_export_payload(filtered_events)
    mermaid_diagrams = mermaid_export_payload(dashboard)
    bpmn_model = bpmn_xml_payload(record.dataframe, filter_spec)
    conformance = (
        conformance_payload(record.dataframe, filter_spec) if include_conformance else None
    )
    metadata = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filename": record.filename,
        "log_id": record.log_id,
        "filters": filters.model_dump(),
        "summary": dashboard["summary"],
        "conformance": conformance,
        "column_mapping": record.column_mapping,
        "informational_columns": record.informational_columns,
        "filter_only_columns": record.filter_only_columns,
        "mapping_warnings": record.mapping_warnings,
    }
    return {
        "dashboard": dashboard,
        "animation": animation,
        "filtered_events": filtered_events,
        "informational_columns_profile": informational_profile,
        "disco_csv_exports": disco_csv_exports,
        "mermaid_diagrams": mermaid_diagrams,
        "bpmn_model": bpmn_model,
        "metadata": metadata,
    }


@app.post("/api/logs/{log_id}/export")
def export_analysis(
    log_id: str, filters: DashboardFilterRequest, request: Request, include_conformance: bool = True
) -> StreamingResponse:
    """Package CSV/JSON/Mermaid/BPMN artifacts into a downloadable ZIP file."""
    record = _get_log_or_404(log_id, _owner(request))
    logger.info("Export ZIP requested for %s (conformance=%s)", log_id, include_conformance)

    try:
        with _log_timer("collect_export_data", log_id=log_id):
            export_data = _collect_export_data(
                record=record,
                filters=filters,
                include_conformance=include_conformance,
            )
    except AnalyticsError as exc:
        logger.error("Export error for %s: %s", log_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    events_for_export = export_data["filtered_events"].copy()
    for column in events_for_export.columns:
        if pd.api.types.is_datetime64_any_dtype(events_for_export[column]):
            events_for_export[column] = events_for_export[column].astype(str)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # Keep filenames stable so analysts can build repeatable downstream
        # workflows around the export package.
        archive.writestr(
            "summary.json", json.dumps(export_data["metadata"], indent=2, default=str)
        )
        archive.writestr("nodes.csv", _records_to_csv(export_data["dashboard"]["nodes"]))
        archive.writestr("edges.csv", _records_to_csv(export_data["dashboard"]["edges"]))
        archive.writestr("variants.csv", _records_to_csv(export_data["dashboard"]["variants"]))
        archive.writestr(
            "bottlenecks.csv",
            _records_to_csv(export_data["dashboard"]["bottlenecks"]),
        )
        archive.writestr(
            "activity_stats.csv",
            _records_to_csv(export_data["dashboard"]["activity_stats"]),
        )
        for filename, csv_body in export_data.get("disco_csv_exports", {}).items():
            # Disco-compatible tables are namespaced so they do not collide with
            # FlowScope's existing app-native CSV exports.
            archive.writestr(f"summary_metrics/{filename}", csv_body)
        archive.writestr(
            "animation_frames.json",
            json.dumps(export_data["animation"], indent=2, default=str),
        )
        archive.writestr(
            "informational_columns_profile.json",
            json.dumps(
                export_data.get("informational_columns_profile", []),
                indent=2,
                default=str,
            ),
        )
        archive.writestr(
            "handoff_actor_edges.csv",
            _records_to_csv(
                export_data["dashboard"]
                .get("handoff", {})
                .get("actor_view", {})
                .get("edges", [])
            ),
        )
        archive.writestr(
            "handoff_activity_edges.csv",
            _records_to_csv(
                export_data["dashboard"]
                .get("handoff", {})
                .get("activity_view", {})
                .get("edges", [])
            ),
        )
        archive.writestr(
            "bpmn_flowchart_nodes.csv",
            _records_to_csv(export_data["dashboard"].get("swimlane", {}).get("nodes", [])),
        )
        archive.writestr(
            "bpmn_flowchart_edges.csv",
            _records_to_csv(export_data["dashboard"].get("swimlane", {}).get("edges", [])),
        )
        archive.writestr(
            "sankey_links.csv",
            _records_to_csv(export_data["dashboard"].get("sankey", {}).get("links", [])),
        )
        archive.writestr(
            "rework_activity.csv",
            _records_to_csv(export_data["dashboard"].get("rework", {}).get("activities", [])),
        )
        archive.writestr(
            "rework_self_loops.csv",
            _records_to_csv(export_data["dashboard"].get("rework", {}).get("self_loops", [])),
        )
        for diagram_name, diagram_body in export_data.get("mermaid_diagrams", {}).items():
            archive.writestr(f"{diagram_name}.mmd", diagram_body)
        bpmn_model = export_data.get("bpmn_model", {})
        if bpmn_model.get("available") and bpmn_model.get("xml"):
            archive.writestr("process_model.bpmn", str(bpmn_model["xml"]))
        else:
            archive.writestr(
                "process_model_bpmn_unavailable.txt",
                str(bpmn_model.get("message", "BPMN export unavailable.")),
            )
        archive.writestr("filtered_events.csv", events_for_export.to_csv(index=False))

    zip_buffer.seek(0)
    safe_basename = _safe_export_basename(record.filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_basename}-analysis-export.zip"'
    }
    return StreamingResponse(zip_buffer, media_type="application/zip", headers=headers)


@app.post("/api/logs/{log_id}/export/html")
def export_analysis_html(
    log_id: str, filters: DashboardFilterRequest, request: Request, include_conformance: bool = True
) -> StreamingResponse:
    """Create a single-file HTML report for sharing the current analysis."""
    record = _get_log_or_404(log_id, _owner(request))
    logger.info("Export HTML requested for %s (conformance=%s)", log_id, include_conformance)

    try:
        with _log_timer("collect_export_html", log_id=log_id):
            export_data = _collect_export_data(
                record=record,
                filters=filters,
                include_conformance=include_conformance,
            )
    except AnalyticsError as exc:
        logger.error("HTML export error for %s: %s", log_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    report_html = _build_html_report(
        filename=record.filename,
        log_id=record.log_id,
        exported_at=export_data["metadata"]["exported_at"],
        filters=export_data["metadata"]["filters"],
        dashboard=export_data["dashboard"],
        animation=export_data["animation"],
        conformance=export_data["metadata"]["conformance"],
        mermaid_exports=export_data.get("mermaid_diagrams"),
        bpmn_model=export_data.get("bpmn_model"),
    )

    safe_basename = _safe_export_basename(record.filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_basename}-analysis-report.html"'
    }
    return StreamingResponse(
        BytesIO(report_html.encode("utf-8")),
        media_type="text/html; charset=utf-8",
        headers=headers,
    )


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@app.post("/login")
async def login_submit(
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    expected = _USERS.get(username, "")
    if expected and secrets.compare_digest(password, expected):
        token = secrets.token_urlsafe(32)
        SESSION_STORE[token] = username
        logger.info("Login success: %s", username)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="none", secure=True)
        return response
    logger.warning("Login failed for username: %s", username)
    return RedirectResponse(url="/login?error=1", status_code=302)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get(_SESSION_COOKIE)
    if token:
        SESSION_STORE.pop(token, None)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(_SESSION_COOKIE, httponly=True, samesite="none", secure=True)
    return response


@app.get("/")
def root() -> FileResponse:
    """Serve the UI when the app is launched through FastAPI."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_file)
