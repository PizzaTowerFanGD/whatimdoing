from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
import hashlib
import os
import requests
app = Flask(__name__)
CORS(app)

# auth setup
KNOWN_HASH = "081390df21e1d49e0af02bf37ff289e7385450db0fadbf7dd937720027759d68"

# gemini client
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
DEFAULT_MODEL = "gemini-2.5-flash"

# state for your other endpoints
state = {"last_app": None}

def authorized():
    supplied = request.headers.get("Authorization", "")
    hashed = hashlib.sha256(supplied.encode()).hexdigest()
    return hashed == KNOWN_HASH

# GEMINI PROXY
@app.route("/gemini", methods=["POST"])
def gemini_proxy():
    if not authorized():
        return "lol no", 401

    data = request.get_json()
    if not data or "prompt" not in data:
        return "missing prompt", 400

    prompt = data["prompt"]
    model = data.get("model", DEFAULT_MODEL)

    response = client.models.generate_content(
        model=model,
        contents=prompt
    )

    return jsonify({"text": response.text})

# ORIGINAL ENDPOINTS
@app.route("/update", methods=["POST"])
def update():
    if not authorized():
        return "lol no", 401
    app_name = request.args.get("app")
    if not app_name:
        return "missing app name", 400
    state["last_app"] = app_name
    return "updated", 200
    
@app.route('/proxy')
def get_cors_proxy():
    return requests.get(request.args.get("url")).content
    
@app.route("/get", methods=["GET"])
def get_last():
    return jsonify(state)

@app.route("/keepalive", methods=["GET"])
def keepalive():
    if authorized():
        return "ok", 200
    else:
        return "unauthorized (but still alive)", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
