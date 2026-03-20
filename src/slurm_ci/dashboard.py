import json
import os
from pathlib import Path

import toml
from flask import Flask, Response, abort, render_template, send_file
from sqlalchemy.orm import joinedload

from .config import STATUS_DIR
from .database import Build, Job, SessionLocal


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
    """Convert Unix timestamp to readable datetime string."""
    from datetime import datetime

    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return str(timestamp)


def basename_filter(path: str) -> str:
    """Get the basename of a path."""
    return os.path.basename(path)


# Register custom filters with Jinja2
app.jinja_env.filters["format_json"] = format_json_filter
app.jinja_env.filters["timestamp_to_datetime"] = timestamp_to_datetime_filter
app.jinja_env.filters["basename"] = basename_filter


@app.route("/")
def index() -> str:
    db = SessionLocal()
    # Use eager loading to fetch jobs along with builds
    # (in case template needs job info)
    builds = (
        db.query(Build)
        .options(joinedload(Build.jobs))
        .order_by(Build.created_at.desc())
        .all()
    )
    db.close()
    return render_template("index.html", builds=builds)


@app.route("/logs")
def all_logs() -> str:
    """Display all logs from .slurm-ci/job_status directory."""
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
            log_entries.append(entry)
        except Exception as e:
            # If we can't parse a file, skip it
            print(f"Error parsing {toml_file}: {e}")
            continue

    return render_template("logs.html", log_entries=log_entries)


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

    # sort the keys to have a consistent order
    sorted_matrix_arg_keys = sorted(list(matrix_arg_keys))

    # attach the parsed matrix args to each job object
    # to avoid parsing it again in the template
    for job in build.jobs:
        if job.matrix_args:
            job.matrix_args_parsed = json.loads(job.matrix_args)
        else:
            job.matrix_args_parsed = {}

    return render_template(
        "build_detail.html",
        build=build,
        matrix_arg_keys=sorted_matrix_arg_keys,
    )


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
