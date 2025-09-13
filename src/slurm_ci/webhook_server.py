import hashlib
import hmac

from flask import Flask, jsonify, request

from . import config
from .unified_orchestrator import UnifiedOrchestrator


app = Flask(__name__)

orchestrator = UnifiedOrchestrator(config)


@app.route("/webhook", methods=["POST"])
def webhook():
    # Validate signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not validate_signature(request.data, signature):
        return "Invalid signature", 403

    event_type = request.headers.get("X-GitHub-Event")
    event = request.get_json()
    orchestrator.execute(mode="git", event_type=event_type, event_data=event)

    return jsonify({"status": "ok"}), 200


def validate_signature(payload, signature):
    secret = bytes(config.GITHUB_SECRET, "utf-8")
    mac = hmac.new(secret, msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(f"sha256={mac.hexdigest()}", signature)


if __name__ == "__main__":
    app.run(port=5000)
