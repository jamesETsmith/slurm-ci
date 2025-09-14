import os
from flask import Flask, abort, render_template, send_file
from sqlalchemy.orm import joinedload

from .database import Build, Job, SessionLocal


app = Flask(__name__)


@app.route("/")
def index():
    db = SessionLocal()
    # Use eager loading to fetch jobs along with builds (in case template needs job info)
    builds = (
        db.query(Build)
        .options(joinedload(Build.jobs))
        .order_by(Build.created_at.desc())
        .all()
    )
    db.close()
    return render_template("index.html", builds=builds)


@app.route("/build/<int:build_id>")
def build_detail(build_id):
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
    return render_template("build_detail.html", build=build)


@app.route("/job/<int:job_id>/log")
def job_log(job_id):
    """Serve the log file for a specific job."""
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
        return send_file(log_file_path, mimetype="text/plain", as_attachment=False)
    except Exception as e:
        abort(500, description=f"Error reading log file: {str(e)}")


@app.route("/debug/logs")
def debug_logs():
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
    html += "<tr><th>Job ID</th><th>Job Name</th><th>Log Path</th><th>Exists</th><th>Size</th></tr>"
    for info in log_info:
        html += f"<tr><td>{info['job_id']}</td><td>{info['job_name']}</td><td>{info['log_file_path']}</td><td>{info['file_exists']}</td><td>{info['file_size']}</td></tr>"
    html += "</table>"
    return html


if __name__ == "__main__":
    app.run(debug=True, port=5001)
