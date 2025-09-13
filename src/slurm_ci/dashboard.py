from flask import Flask, abort, render_template

from .database import Build, SessionLocal


app = Flask(__name__)


@app.route("/")
def index():
    db = SessionLocal()
    builds = db.query(Build).order_by(Build.created_at.desc()).all()
    db.close()
    return render_template("index.html", builds=builds)


@app.route("/build/<int:build_id>")
def build_detail(build_id):
    db = SessionLocal()
    build = db.query(Build).filter(Build.id == build_id).first()
    db.close()
    if not build:
        abort(404)
    return render_template("build_detail.html", build=build)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
