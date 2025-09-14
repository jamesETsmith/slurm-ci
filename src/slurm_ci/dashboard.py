from flask import Flask, abort, render_template
from sqlalchemy.orm import joinedload

from .database import Build, SessionLocal


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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
