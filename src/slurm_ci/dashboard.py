import json
import os

from flask import Flask, Response, abort, render_template, send_file
from sqlalchemy.orm import joinedload

from .database import Build, Job, SessionLocal


app = Flask(__name__)


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


# Register the custom filter with Jinja2
app.jinja_env.filters["format_json"] = format_json_filter


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

    log_file_path = job.log_file_path
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

    if not job.log_file_path or not os.path.exists(job.log_file_path):
        abort(404, description="Log file not found")

    try:
        return send_file(job.log_file_path, as_attachment=True)
    except Exception as e:
        abort(500, description=f"Error sending log file: {str(e)}")


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
            "file_exists": os.path.exists(job.log_file_path)
            if job.log_file_path
            else False,
            "file_size": os.path.getsize(job.log_file_path)
            if job.log_file_path and os.path.exists(job.log_file_path)
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
