from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from google import genai
import hashlib
import os
import requests
import mimetypes
import asyncio
import threading
import json
import time
import websockets

app = Flask(__name__)
CORS(app)

# --- AUTH SETUP ---
KNOWN_HASH = "081390df21e1d49e0af02bf37ff289e7385450db0fadbf7dd937720027759d68"

# --- GENAI SETUP ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai_client = genai.Client(api_key=GEMINI_API_KEY)
DEFAULT_MODEL = "gemini-2.5-flash"

# --- STATE ---
state = {"last_app": None}
owot_clients = {} # Cache for OWOT WebSocket connections

def authorized():
    supplied = request.headers.get("Authorization", "")
    hashed = hashlib.sha256(supplied.encode()).hexdigest()
    return hashed == KNOWN_HASH

# --- OWOT ASYNC LOGIC ---
# This class handles the specific protocol found in the JS client code
class OWOTManager:
    def __init__(self, world):
        self.world = world
        self.url = f"wss://ourworldoftext.com/{world}/ws/"
        self.chat_buffer = []
        self.tiles = {}
        self.loop = asyncio.new_event_loop()
        self.edit_id = 1
        
    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._listen())

    async def _listen(self):
        async with websockets.connect(self.url) as ws:
            self.ws = ws
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                kind = data.get("kind")
                if kind == "chat":
                    self.chat_buffer.append(f"[{data.get('nickname')}]: {data.get('message')}")
                    if len(self.chat_buffer) > 30: self.chat_buffer.pop(0)
                elif kind == "fetch":
                    self.tiles.update(data.get("tiles", {}))

    def run_coro(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

def get_owot(world):
    if world not in owot_clients:
        mgr = OWOTManager(world)
        mgr.start()
        time.sleep(1) # Wait for handshake
        owot_clients[world] = mgr
    return owot_clients[world]

# --- NEW OWOT ENDPOINTS (MCP TOOLS) ---

@app.route("/owot/chat", methods=["GET"])
def get_owot_chat():
    if not authorized(): return "unauthorized", 401
    world = request.args.get("world", "")
    client = get_owot(world)
    return jsonify({"history": client.chat_buffer})

@app.route("/owot/write", methods=["POST"])
def write_owot():
    if not authorized(): return "unauthorized", 401
    data = request.json
    client = get_owot(data.get("world", ""))
    
    # OWOT Edit Format: [tileY, tileX, charY, charX, timestamp, char, editID]
    edit = [
        data.get("tileY", 0), data.get("tileX", 0),
        data.get("charY", 0), data.get("charX", 0),
        int(time.time() * 1000), data.get("text", " "), client.edit_id
    ]
    client.edit_id += 1
    client.run_coro(client.ws.send(json.dumps({"kind": "write", "edits": [edit]})))
    return "ok"

@app.route("/owot/read", methods=["GET"])
def read_owot():
    if not authorized(): return "unauthorized", 401
    world = request.args.get("world", "")
    tx = int(request.args.get("tileX", 0))
    ty = int(request.args.get("tileY", 0))
    client = get_owot(world)
    
    # Request tile fetch
    fetch_msg = {"kind": "fetch", "fetchRectangles": [{"minX": tx, "minY": ty, "maxX": tx, "maxY": ty}]}
    client.run_coro(client.ws.send(json.dumps(fetch_msg)))
    time.sleep(0.3) # Wait for tile to arrive in background listener
    
    tile_data = client.tiles.get(f"{ty},{tx}", {}).get("content", " " * 128)
    return jsonify({"content": tile_data})

# --- ORIGINAL GITHUB PROXY ---
@app.route("/github/<user>/<repo>/<branch>/", defaults={'filepath': 'index.html'})
@app.route("/github/<user>/<repo>/<branch>/<path:filepath>")
def github_proxy(user, repo, branch, filepath):
    raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{filepath}"
    try:
        resp = requests.get(raw_url)
        if resp.status_code != 200: return "Error", resp.status_code
        content_type, _ = mimetypes.guess_type(filepath)
        if not content_type:
            if filepath.endswith(".html"): content_type = "text/html"
            elif filepath.endswith(".js"): content_type = "application/javascript"
            else: content_type = "text/plain"
        return Response(resp.content, mimetype=content_type, status=200)
    except Exception as e: return str(e), 500

# --- GEMINI PROXY ---
@app.route("/gemini", methods=["POST"])
def gemini_proxy():
    if not authorized(): return "lol no", 401
    data = request.get_json()
    prompt = data.get("prompt")
    model = data.get("model", DEFAULT_MODEL)
    response = genai_client.models.generate_content(model=model, contents=prompt)
    return jsonify({"text": response.text})

# --- CORS PROXY & OTHER ENDPOINTS ---
@app.route('/proxy')
def get_cors_proxy():
    return requests.get(request.args.get("url")).content

@app.route("/update", methods=["POST"])
def update():
    if not authorized(): return "lol no", 401
    state["last_app"] = request.args.get("app")
    return "updated", 200

@app.route("/get", methods=["GET"])
def get_last():
    return jsonify(state)

@app.route("/keepalive", methods=["GET"])
def keepalive():
    return ("ok" if authorized() else "unauthorized (but still alive)"), 200

@app.route("/p/<host>/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
@app.route("/p/<host>/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
def subpage_proxy(host, path):
    url = f"https://{host}/{path}"
    try:
        resp = requests.request(
            method=request.method, url=url,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            params=request.args, data=request.get_data(), cookies=request.cookies, allow_redirects=True
        )
        excluded = {"content-length", "transfer-encoding", "connection"}
        response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
        return Response(resp.content, status=resp.status_code, headers=response_headers)
    except Exception as e: return f"proxy error: {str(e)}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
