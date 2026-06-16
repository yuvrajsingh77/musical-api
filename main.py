from flask import Flask, request, jsonify, Response
import requests
import threading

app = Flask(__name__)

SAAVN_API = "https://jiosaavn-api.vercel.app"
RAILWAY_URL = "https://web-production-7318d.up.railway.app"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.jiosaavn.com/"
}

CDN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36",
    "Referer": "https://www.jiosaavn.com/",
    "Origin": "https://www.jiosaavn.com"
}

stream_cache = {}
cache_lock = threading.Lock()

def get_fresh_stream_url(song_id):
    resp = requests.get(
        f"{SAAVN_API}/song",
        params={"id": song_id},
        headers=HEADERS,
        timeout=20
    )
    data = resp.json()
    media_urls = data.get("media_urls", {})
    return (
        media_urls.get("320_KBPS") or
        media_urls.get("160_KBPS") or
        media_urls.get("96_KBPS") or
        data.get("media_url")
    )

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        resp = requests.get(
            f"{SAAVN_API}/search",
            params={"query": query},
            headers=HEADERS,
            timeout=15
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/song")
def song():
    song_id = request.args.get("id", "").strip()
    if not song_id:
        return jsonify({"success": False, "error": "No song id"}), 400
    try:
        resp = requests.get(
            f"{SAAVN_API}/song",
            params={"id": song_id},
            headers=HEADERS,
            timeout=20
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stream")
def stream():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        search_resp = requests.get(
            f"{SAAVN_API}/search",
            params={"query": query},
            headers=HEADERS,
            timeout=15
        )
        results = search_resp.json().get("results", [])
        if not results:
            return jsonify({"success": False, "error": "No results"}), 404

        song_id = results[0].get("id")
        song_data_resp = requests.get(
            f"{SAAVN_API}/song",
            params={"id": song_id},
            headers=HEADERS,
            timeout=20
        )
        song_data = song_data_resp.json()

        duration_str = song_data.get("duration", "0:00")
        try:
            parts = duration_str.split(":")
            duration_secs = int(parts[0]) * 60 + int(parts[1])
        except:
            duration_secs = 0

        cdn_url = (
            song_data.get("media_urls", {}).get("320_KBPS") or
            song_data.get("media_urls", {}).get("160_KBPS") or
            song_data.get("media_url")
        )
        with cache_lock:
            stream_cache[song_id] = cdn_url

        proxy_url = f"{RAILWAY_URL}/audio/{song_id}"

        return jsonify({
            "success": True,
            "data": {
                "id": song_data.get("id", song_id),
                "title": song_data.get("song", query),
                "artist": song_data.get("singers", "Unknown"),
                "album": song_data.get("album", ""),
                "artwork": song_data.get("image", ""),
                "duration": duration_secs,
                "url": proxy_url,
                "ext": "mp4"
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/audio/<song_id>")
def audio(song_id):
    try:
        # Always fetch fresh URL since CDN URLs expire
        cdn_url = get_fresh_stream_url(song_id)
        if not cdn_url:
            return jsonify({"error": "No stream URL"}), 404

        range_header = request.headers.get("Range", None)
        req_headers = dict(CDN_HEADERS)
        if range_header:
            req_headers["Range"] = range_header

        cdn_resp = requests.get(
            cdn_url,
            headers=req_headers,
            stream=True,
            timeout=60
        )

        excluded = {"transfer-encoding", "connection", "keep-alive"}
        response_headers = {
            k: v for k, v in cdn_resp.headers.items()
            if k.lower() not in excluded
        }
        response_headers["Accept-Ranges"] = "bytes"
        response_headers["Access-Control-Allow-Origin"] = "*"

        def generate():
            for chunk in cdn_resp.iter_content(chunk_size=32768):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            status=cdn_resp.status_code,
            headers=response_headers,
            direct_passthrough=True
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "musical-api"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "6.0.0"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
