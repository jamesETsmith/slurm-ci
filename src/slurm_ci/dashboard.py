import datetime
import json
import os
from pathlib import Path

import toml
from flask import Flask, Response, abort, render_template, request, send_file
from sqlalchemy.orm import joinedload

from .config import STATUS_DIR
from .database import Build, Job, SessionLocal


TREND_WINDOW = 20
TERMINAL_BUILD_STATUSES = ("completed", "failed")


# Get the directory where this file is located
current_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(current_dir, "templates")
static_dir = os.path.join(current_dir, "static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)


def format_json_filter(json_string: str) -> str:
    """Custom Jinja2 filter to format JSON with proper indentation."""
    if not json_string:
        return json_string
    try:
        # Parse the JSON string and format it with indentation
        parsed = json.loads(json_string)
        return json.dumps(parsed, indent=2, separators=(",", ": "))
    except (json.JSONDecodeError, TypeError):
        # If parsing fails, return the original string
        return json_string


def timestamp_to_datetime_filter(timestamp: float) -> str:
    """Convert Unix timestamp to a readable Eastern Time (NYC) datetime string."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        tz_et = ZoneInfo("America/New_York")
        dt = datetime.fromtimestamp(timestamp, tz=tz_et)
        suffix = "EDT" if dt.dst() else "EST"
        return dt.strftime(f"%Y-%m-%d %H:%M:%S {suffix}")
    except (ValueError, TypeError, OSError):
        return str(timestamp)


def to_eastern_filter(
    dt: datetime.datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S"
) -> str:
    """Convert a naive-UTC datetime to an Eastern Time string."""
    from zoneinfo import ZoneInfo

    if dt is None:
        return "—"
    try:
        tz_utc = ZoneInfo("UTC")
        tz_et = ZoneInfo("America/New_York")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_utc)
        dt_et = dt.astimezone(tz_et)
        suffix = "EDT" if dt_et.dst() else "EST"
        return dt_et.strftime(f"{fmt} {suffix}")
    except (ValueError, TypeError, OSError):
        return str(dt)


def basename_filter(path: str) -> str:
    """Get the basename of a path."""
    return os.path.basename(path)


def format_duration_filter(seconds: float | int | None) -> str:
    """Format a duration in seconds as a short human-readable string."""
    if seconds is None:
        return "\u2014"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "\u2014"
    if s < 0:
        return "\u2014"
    if s < 1:
        return f"{s * 1000:.0f} ms"
    if s < 60:
        return f"{s:.1f} s"
    minutes, sec = divmod(int(round(s)), 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_percent_filter(value: float | None) -> str:
    """Format a fractional or 0-100 percent value as ``XX.X %``."""
    if value is None:
        return "\u2014"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    return f"{v:.1f}%"


# Register custom filters with Jinja2
app.jinja_env.filters["format_json"] = format_json_filter
app.jinja_env.filters["timestamp_to_datetime"] = timestamp_to_datetime_filter
app.jinja_env.filters["basename"] = basename_filter
app.jinja_env.filters["format_duration"] = format_duration_filter
app.jinja_env.filters["format_percent"] = format_percent_filter
app.jinja_env.filters["to_eastern"] = to_eastern_filter


def _percentile(values: list[float], q: float) -> float | None:
    """Return the linear-interpolation percentile (q in [0, 1])."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _build_duration_seconds(build: object) -> float | None:
    """Wall-clock duration of a build's job set, or ``None`` if unknown."""
    starts = []
    ends = []
    for job in getattr(build, "jobs", []) or []:
        if job.start_time is not None:
            starts.append(job.start_time)
        if job.end_time is not None:
            ends.append(job.end_time)
    if not starts or not ends:
        return None
    try:
        delta = max(ends) - min(starts)
    except TypeError:
        return None
    seconds = delta.total_seconds() if hasattr(delta, "total_seconds") else None
    if seconds is None or seconds < 0:
        return None
    return seconds


def _build_status_from_entry(entry: dict) -> str:
    """Derive a coarse status for filesystem log entries."""
    if entry.get("end_time") is None:
        return "running" if entry.get("start_time") else "pending"
    return "completed" if entry.get("exit_code") == 0 else "failed"


def _load_builds_context() -> dict:
    """Load filtered builds, options, summary data, and chart points."""
    status = request.args.get("status", "").strip().lower()
    branch = request.args.get("branch", "").strip()
    workflow = request.args.get("workflow", "").strip()
    project = request.args.get("project", "").strip()

    db = SessionLocal()
    query = (
        db.query(Build)
        .options(joinedload(Build.jobs))
        .order_by(Build.updated_at.desc())
    )

    if status:
        query = query.filter(Build.status == status)
    if branch:
        query = query.filter(Build.branch == branch)
    if workflow:
        query = query.filter(Build.workflow_file.ilike(f"%{workflow}%"))
    if project:
        query = query.filter(Build.repo_full_name == project)

    builds = query.all()
    db.close()

    status_counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "incomplete": 0,
    }
    for build in builds:
        build_status = str(build.status)
        if build_status in status_counts:
            status_counts[build_status] += 1

    trend_points = []
    for build in reversed(builds[:TREND_WINDOW]):
        passed = 0
        failed = 0
        other = 0
        for job in build.jobs:
            job_status = str(job.status) if job.status is not None else ""
            if job_status == "completed":
                passed += 1
            elif job_status == "failed":
                failed += 1
            else:
                other += 1
        trend_points.append(
            {
                "label": f"#{build.id}",
                "build_id": build.id,
                "passed": passed,
                "failed": failed,
                "other": other,
            }
        )

    completed_n = sum(1 for b in builds if str(b.status) == "completed")
    failed_n = sum(1 for b in builds if str(b.status) == "failed")
    terminal_total = completed_n + failed_n
    success_rate = (
        (completed_n / terminal_total * 100.0) if terminal_total > 0 else None
    )

    durations: list[float] = []
    for build in builds:
        if str(build.status) not in TERMINAL_BUILD_STATUSES:
            continue
        d = _build_duration_seconds(build)
        if d is not None:
            durations.append(d)

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    runs_last_24h = 0
    for build in builds:
        created = getattr(build, "created_at", None)
        if isinstance(created, datetime.datetime):
            if (now - created).total_seconds() <= 86400:
                runs_last_24h += 1

    kpis = {
        "success_rate": success_rate,
        "p50_duration_s": _percentile(durations, 0.5),
        "p95_duration_s": _percentile(durations, 0.95),
        "runs_last_24h": runs_last_24h,
        "terminal_total": terminal_total,
        "duration_sample_size": len(durations),
    }

    # Build options should remain global so users can pivot quickly.
    db = SessionLocal()
    all_builds = db.query(Build).order_by(Build.updated_at.desc()).all()
    db.close()

    project_options = sorted(
        {str(b.repo_full_name) for b in all_builds if b.repo_full_name}
    )
    branch_options = sorted({b.branch for b in all_builds if b.branch})
    workflow_options = sorted(
        {
            os.path.basename(str(b.workflow_file))
            for b in all_builds
            if b.workflow_file and os.path.basename(str(b.workflow_file))
        }
    )
    status_options = ["pending", "running", "completed", "failed", "incomplete"]

    return {
        "builds": builds,
        "summary": {
            "total": len(builds),
            "status_counts": status_counts,
            "last_update": builds[0].updated_at if builds else None,
        },
        "trend_points": trend_points,
        "kpis": kpis,
        "filters": {
            "status": status,
            "branch": branch,
            "workflow": workflow,
            "project": project,
        },
        "filter_options": {
            "status": status_options,
            "project": project_options,
            "branch": branch_options,
            "workflow": workflow_options,
        },
        "data_source": "sqlite",
    }


@app.route("/")
def index() -> str:
    context = _load_builds_context()
    return render_template("index.html", **context)


@app.route("/partials/index_summary")
def index_summary_partial() -> str:
    context = _load_builds_context()
    return render_template("partials/index_summary.html", **context)


@app.route("/partials/index_table")
def index_table_partial() -> str:
    context = _load_builds_context()
    return render_template("partials/index_table.html", **context)


@app.route("/logs")
def all_logs() -> str:
    """Display all logs from .slurm-ci/job_status directory."""
    status_filter = request.args.get("status", "").strip().lower()
    branch_filter = request.args.get("branch", "").strip()
    workflow_filter = request.args.get("workflow", "").strip()
    project_filter = request.args.get("project", "").strip()
    status_dir = Path(STATUS_DIR)
    log_entries = []

    # Scan all .toml files in the status directory
    for toml_file in sorted(
        status_dir.glob("*.toml"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            with open(toml_file, "r") as f:
                data = toml.load(f)

            # Get the corresponding log file path
            log_file = toml_file.with_suffix(".log")

            # Extract relevant information from the status file
            entry = {
                "status_file": str(toml_file),
                "log_file": str(log_file) if log_file.exists() else None,
                "project_name": data.get("project", {}).get("name", "Unknown"),
                "workflow_file": data.get("project", {}).get(
                    "workflow_file", "Unknown"
                ),
                "git_commit": data.get("git", {}).get("commit", "Unknown")[:8]
                if data.get("git", {}).get("commit")
                else "Unknown",
                "git_branch": data.get("git", {}).get("branch", "Unknown"),
                "matrix_args": data.get("matrix", {}),
                "start_time": data.get("runtime", {}).get("start_time"),
                "end_time": data.get("runtime", {}).get("end", {}).get("time")
                if isinstance(data.get("runtime", {}).get("end"), dict)
                else None,
                "exit_code": data.get("runtime", {}).get("end", {}).get("exit_code")
                if isinstance(data.get("runtime", {}).get("end"), dict)
                else None,
                "slurm_job_id": data.get("slurm", {}).get("job_id"),
            }
            entry["status"] = _build_status_from_entry(entry)
            if status_filter and entry["status"] != status_filter:
                continue
            if branch_filter and entry["git_branch"] != branch_filter:
                continue
            if (
                workflow_filter
                and workflow_filter.lower() not in entry["workflow_file"].lower()
            ):
                continue
            if project_filter and entry["project_name"] != project_filter:
                continue
            log_entries.append(entry)
        except Exception as e:
            # If we can't parse a file, skip it
            print(f"Error parsing {toml_file}: {e}")
            continue

    project_options = sorted(
        {entry["project_name"] for entry in log_entries if entry["project_name"]}
    )
    branch_options = sorted(
        {entry["git_branch"] for entry in log_entries if entry["git_branch"]}
    )
    workflow_options = sorted(
        {
            os.path.basename(entry["workflow_file"])
            for entry in log_entries
            if entry["workflow_file"]
        }
    )

    return render_template(
        "logs.html",
        log_entries=log_entries,
        filters={
            "status": status_filter,
            "branch": branch_filter,
            "workflow": workflow_filter,
            "project": project_filter,
        },
        filter_options={
            "status": ["pending", "running", "completed", "failed", "incomplete"],
            "project": project_options,
            "branch": branch_options,
            "workflow": workflow_options,
        },
        data_source="filesystem",
    )


@app.route("/raw_log/<path:filename>")
def raw_log(filename: str) -> Response:
    """Serve a raw log file from the status directory."""
    status_dir = Path(STATUS_DIR)
    log_file_path = status_dir / filename

    # Security check: ensure the file is within the status directory
    try:
        log_file_path = log_file_path.resolve()
        status_dir = status_dir.resolve()
        if not str(log_file_path).startswith(str(status_dir)):
            abort(403, description="Access denied")
    except Exception:
        abort(403, description="Invalid path")

    if not log_file_path.exists():
        abort(404, description="Log file not found")

    try:
        # Read the log file and wrap it with minimal HTML for auto-scroll
        with open(log_file_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Create simple HTML wrapper with auto-scroll
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Log - {filename}</title>
    <style>
        body {{
            font-family: monospace;
            white-space: pre-wrap;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
        }}
    </style>
</head>
<body>{log_content}
<script>
    window.addEventListener('load', function() {{
        window.scrollTo(0, document.body.scrollHeight);
    }});
</script>
</body>
</html>"""

        return Response(html_content, mimetype="text/html")
    except Exception as e:
        abort(500, description=f"Error reading log file: {str(e)}")


@app.route("/raw_status/<path:filename>")
def raw_status(filename: str) -> Response:
    """Serve a raw status file from the status directory."""
    status_dir = Path(STATUS_DIR)
    status_file_path = status_dir / filename

    # Security check: ensure the file is within the status directory
    try:
        status_file_path = status_file_path.resolve()
        status_dir = status_dir.resolve()
        if not str(status_file_path).startswith(str(status_dir)):
            abort(403, description="Access denied")
    except Exception:
        abort(403, description="Invalid path")

    if not status_file_path.exists():
        abort(404, description="Status file not found")

    try:
        # Read the status file and wrap it with HTML for better display
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_content = f.read()

        # Create HTML wrapper with syntax highlighting for TOML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Status File - {filename}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
            line-height: 1.6;
        }}
        .header {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .content {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        pre {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            overflow-x: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
            margin: 0;
        }}
        .btn {{
            display: inline-block;
            padding: 8px 16px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-right: 10px;
        }}
        .btn:hover {{
            background-color: #0056b3;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Status File: {filename}</h1>
        <p><strong>File Path:</strong> <code>{status_file_path}</code></p>
        <a href="javascript:history.back()" class="btn">Back</a>
    </div>
    <div class="content">
        <pre><code>{status_content}</code></pre>
    </div>
</body>
</html>"""

        return Response(html_content, mimetype="text/html")
    except Exception as e:
        abort(500, description=f"Error reading status file: {str(e)}")


@app.route("/build/<int:build_id>")
def build_detail(build_id: int) -> str:
    db = SessionLocal()
    # Use eager loading to fetch jobs along with the build
    build = (
        db.query(Build)
        .options(joinedload(Build.jobs))
        .filter(Build.id == build_id)
        .first()
    )
    db.close()
    if not build:
        abort(404)

    matrix_arg_keys = set()
    if build.jobs:
        for job in build.jobs:
            if job.matrix_args:
                matrix_args = json.loads(job.matrix_args)
                matrix_arg_keys.update(matrix_args.keys())

    sorted_matrix_arg_keys = sorted(list(matrix_arg_keys))

    for job in build.jobs:
        if job.matrix_args:
            job.matrix_args_parsed = json.loads(job.matrix_args)
        else:
            job.matrix_args_parsed = {}

    build.jobs.sort(
        key=lambda j: (j.start_time is not None, j.start_time),
        reverse=True,
    )

    return render_template(
        "build_detail.html",
        build=build,
        matrix_arg_keys=sorted_matrix_arg_keys,
        data_source="sqlite",
    )


@app.route("/build/<int:build_id>/workflow")
def build_workflow(build_id: int) -> Response:
    """Serve the workflow YAML that was used for a build.

    Tries, in order:
      1. ``project.workflow_content`` captured in a job's status TOML
      2. The workflow file on disk (``build.workflow_file``)
    """
    db = SessionLocal()
    build = (
        db.query(Build)
        .options(joinedload(Build.jobs))
        .filter(Build.id == build_id)
        .first()
    )
    db.close()

    if not build:
        abort(404)

    workflow_content = None
    workflow_label = os.path.basename(str(build.workflow_file or "workflow.yml"))

    for job in build.jobs or []:
        if not job.status_file_path or not os.path.exists(str(job.status_file_path)):
            continue
        try:
            with open(str(job.status_file_path), "r") as f:
                data = toml.load(f)
            wc = data.get("project", {}).get("workflow_content")
            if wc:
                workflow_content = wc
                break
        except Exception:
            continue

    if workflow_content is None and build.workflow_file:
        try:
            workflow_content = Path(str(build.workflow_file)).read_text()
        except OSError:
            pass

    if workflow_content is None:
        abort(
            404,
            description="Workflow content not available — the file may have "
            "been moved and no captured copy exists in the status files.",
        )

    import html as html_mod

    escaped = html_mod.escape(workflow_content)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Workflow - {html_mod.escape(workflow_label)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f6f8fa;
            color: #24292f;
        }}
        .header {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .content {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        pre {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            overflow-x: auto;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono',
                         Menlo, monospace;
            font-size: 14px;
            margin: 0;
        }}
        .btn {{
            display: inline-block;
            padding: 8px 16px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-right: 10px;
        }}
        .btn:hover {{
            background-color: #0056b3;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Workflow: {html_mod.escape(workflow_label)}</h1>
        <p><strong>Build:</strong> #{build_id}
           &mdash; {html_mod.escape(str(build.repo_full_name))}</p>
        <a href="javascript:history.back()" class="btn">Back</a>
    </div>
    <div class="content">
        <pre><code>{escaped}</code></pre>
    </div>
</body>
</html>"""

    return Response(html_content, mimetype="text/html")


@app.route("/job/<int:job_id>/log")
def job_log(job_id: int) -> Response:
    """Serve the raw log file for a specific job with auto-scroll."""
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()

    if not job:
        abort(404)

    if not job.log_file_path:
        abort(404, description="No log file available for this job")

    log_file_path = str(job.log_file_path)
    if not os.path.exists(log_file_path):
        # Check if file exists and provide more detailed error
        from pathlib import Path

        log_dir = Path(log_file_path).parent
        if not log_dir.exists():
            abort(404, description=f"Log directory does not exist: {log_dir}")
        else:
            abort(404, description=f"Log file not found: {log_file_path}")

    try:
        # Read the log file and wrap it with minimal HTML for auto-scroll
        with open(log_file_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Create simple HTML wrapper with auto-scroll
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Job Log - {job.name}</title>
    <style>
        body {{
            font-family: monospace;
            white-space: pre-wrap;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
        }}
    </style>
</head>
<body>{log_content}
<script>
    window.addEventListener('load', function() {{
        window.scrollTo(0, document.body.scrollHeight);
    }});
</script>
</body>
</html>"""

        return Response(html_content, mimetype="text/html")
    except Exception as e:
        abort(500, description=f"Error reading log file: {str(e)}")


@app.route("/job/<int:job_id>/log/download")
def download_log(job_id: int) -> Response:
    """Serve the raw log file for a specific job as a download."""
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()

    if not job:
        abort(404)

    job_log_file_path = str(job.log_file_path) if job.log_file_path else ""
    if not job_log_file_path or not os.path.exists(job_log_file_path):
        abort(404, description="Log file not found")

    try:
        return send_file(job_log_file_path, as_attachment=True)
    except Exception as e:
        abort(500, description=f"Error sending log file: {str(e)}")


@app.route("/job/<int:job_id>/status")
def job_status(job_id: int) -> Response:
    """Serve the status file for a specific job."""
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()

    if not job:
        abort(404)

    if not job.status_file_path:
        abort(404, description="No status file available for this job")

    status_file_path = str(job.status_file_path)
    if not os.path.exists(status_file_path):
        # Check if file exists and provide more detailed error
        from pathlib import Path

        status_dir = Path(status_file_path).parent
        if not status_dir.exists():
            abort(404, description=f"Status directory does not exist: {status_dir}")
        else:
            abort(404, description=f"Status file not found: {status_file_path}")

    try:
        # Read the status file and wrap it with HTML for better display
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_content = f.read()

        # Create HTML wrapper with syntax highlighting for TOML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Status File - {job.name}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
            line-height: 1.6;
        }}
        .header {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .content {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        pre {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            overflow-x: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
            margin: 0;
        }}
        .btn {{
            display: inline-block;
            padding: 8px 16px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-right: 10px;
        }}
        .btn:hover {{
            background-color: #0056b3;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Status File: {job.name}</h1>
        <p><strong>Job ID:</strong> {job.id}</p>
        <p><strong>File Path:</strong> <code>{status_file_path}</code></p>
        <a href="/job/{job.id}/status/download" class="btn">Download</a>
        <a href="javascript:history.back()" class="btn">Back</a>
    </div>
    <div class="content">
        <pre><code>{status_content}</code></pre>
    </div>
</body>
</html>"""

        return Response(html_content, mimetype="text/html")
    except Exception as e:
        abort(500, description=f"Error reading status file: {str(e)}")


@app.route("/job/<int:job_id>/status/download")
def download_status(job_id: int) -> Response:
    """Serve the status file for a specific job as a download."""
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()

    if not job:
        abort(404)

    job_status_file_path = str(job.status_file_path) if job.status_file_path else ""
    if not job_status_file_path or not os.path.exists(job_status_file_path):
        abort(404, description="Status file not found")

    try:
        return send_file(job_status_file_path, as_attachment=True)
    except Exception as e:
        abort(500, description=f"Error sending status file: {str(e)}")


@app.route("/debug/logs")
def debug_logs() -> str:
    """Debug route to check log file status."""
    if os.getenv("SLURM_CI_ENABLE_DEBUG_ROUTES", "0") != "1":
        abort(404)

    db = SessionLocal()
    jobs = db.query(Job).all()
    db.close()

    log_info = []
    for job in jobs:
        info = {
            "job_id": job.id,
            "job_name": job.name,
            "log_file_path": job.log_file_path,
            "file_exists": os.path.exists(str(job.log_file_path))
            if job.log_file_path
            else False,
            "file_size": os.path.getsize(str(job.log_file_path))
            if job.log_file_path and os.path.exists(str(job.log_file_path))
            else 0,
        }
        log_info.append(info)

    html = "<h2>Debug: Log Files Status</h2><table border='1'>"
    html += (
        "<tr><th>Job ID</th><th>Job Name</th><th>Log Path</th>"
        "<th>Exists</th><th>Size</th></tr>"
    )
    for info in log_info:
        html += (
            f"<tr><td>{info['job_id']}</td><td>{info['job_name']}</td>"
            f"<td>{info['log_file_path']}</td><td>{info['file_exists']}</td>"
            f"<td>{info['file_size']}</td></tr>"
        )
    html += "</table>"
    return html


if __name__ == "__main__":
    app.run(debug=True, port=5001)
