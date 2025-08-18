from flask import Flask, request, jsonify
import hashlib
import os

app = Flask(__name__)

# pre-hash your chosen passcode with sha256 and drop the hex string here
KNOWN_HASH = "081390df21e1d49e0af02bf37ff289e7385450db0fadbf7dd937720027759d68"

state = {"last_app": None}

def authorized():
    supplied = request.headers.get("Authorization", "")
    hashed = hashlib.sha256(supplied.encode()).hexdigest()
    return hashed == KNOWN_HASH

@app.route("/update", methods=["POST"])
def update():
    if not authorized():
        return "lol no", 401

    app_name = request.args.get("app")
    if not app_name:
        return "missing app name", 400

    state["last_app"] = app_name
    return "updated", 200

@app.route("/get", methods=["GET"])
def get_last():
    if not authorized():
        return "lol no", 401
    return jsonify(state)

@app.route("/keepalive", methods=["GET"])
def keepalive():
    if not authorized():
        return "lol no", 401
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
