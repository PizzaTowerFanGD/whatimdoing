from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from google import genai
import hashlib
import os
import requests
import mimetypes

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

# --- NEW GITHUB PROXY ---
@app.route("/github/<user>/<repo>/<branch>/", defaults={'filepath': 'index.html'})
@app.route("/github/<user>/<repo>/<branch>/<path:filepath>")
def github_proxy(user, repo, branch, filepath):
    # Construct the raw GitHub URL
    raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{filepath}"
    
    try:
        resp = requests.get(raw_url)
        
        if resp.status_code != 200:
            return f"GitHub Error: {resp.status_code} - {resp.text}", resp.status_code

        # Determine the correct MIME type
        # GitHub serves raw files as text/plain, which breaks CSS/JS in browsers.
        # We must detect the type from the extension and force the header.
        content_type, encoding = mimetypes.guess_type(filepath)
        
        # Explicit fallbacks for common web types if mimetypes guesses wrong or returns None
        if not content_type:
            if filepath.endswith(".html"): content_type = "text/html"
            elif filepath.endswith(".css"): content_type = "text/css"
            elif filepath.endswith(".js"): content_type = "application/javascript"
            elif filepath.endswith(".json"): content_type = "application/json"
            else: content_type = "text/plain"

        return Response(resp.content, mimetype=content_type, status=200)

    except Exception as e:
        return f"Proxy Error: {str(e)}", 500
# ------------------------

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

import io
import gzip
import zlib

import brotli

# --- ROBUST GENERIC SUBPAGE PROXY ---
@app.route("/p/<host>/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
@app.route("/p/<host>/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
def subpage_proxy(host, path):
    target_url = f"https://{host}/{path}"

    # copy headers except ones that break things
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True  # follow redirects
        )

        excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]

        content_type = resp.headers.get("Content-Type", "")
        content = resp.content

        # handle compression
        ce = resp.headers.get("Content-Encoding", "").lower()
        if ce == "gzip":
            content = gzip.decompress(content)
        elif ce == "deflate":
            content = zlib.decompress(content)
        elif ce == "br":
            content = brotli.decompress(content)

        # return text for text-based content
        if "text" in content_type or "json" in content_type or "javascript" in content_type:
            try:
                content = content.decode(resp.encoding or "utf-8")
            except:
                pass  # fallback to bytes if decoding fails

        return Response(content, status=resp.status_code, headers=response_headers)

    except Exception as e:
        return f"proxy error: {str(e)}", 500
# ----------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
