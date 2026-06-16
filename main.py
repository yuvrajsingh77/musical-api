from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

SAAVN_API = "https://jiosaavn-api.vercel.app"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.jiosaavn.com/"
}

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
    """One-shot endpoint: search + get stream URL in one call"""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        # Step 1: Search
        search_resp = requests.get(
            f"{SAAVN_API}/search",
            params={"query": query},
            headers=HEADERS,
            timeout=15
        )
        search_data = search_resp.json()
        results = search_data.get("results", [])
        if not results:
            return jsonify({"success": False, "error": "No search results"}), 404

        # Step 2: Get first result's full song data
        song_id = results[0].get("id")
        if not song_id:
            return jsonify({"success": False, "error": "No song ID"}), 404

        song_resp = requests.get(
            f"{SAAVN_API}/song",
            params={"id": song_id},
            headers=HEADERS,
            timeout=20
        )
        song_data = song_resp.json()

        # Step 3: Extract best stream URL
        media_urls = song_data.get("media_urls", {})
        stream_url = (
            media_urls.get("320_KBPS") or
            media_urls.get("160_KBPS") or
            media_urls.get("96_KBPS") or
            song_data.get("media_url")
        )

        if not stream_url:
            return jsonify({"success": False, "error": "No stream URL found"}), 404

        duration_str = song_data.get("duration", "0:00")
        try:
            parts = duration_str.split(":")
            duration_secs = int(parts[0]) * 60 + int(parts[1])
        except:
            duration_secs = 0

        return jsonify({
            "success": True,
            "data": {
                "id": song_data.get("id", song_id),
                "title": song_data.get("song", query),
                "artist": song_data.get("singers", "Unknown"),
                "album": song_data.get("album", ""),
                "artwork": song_data.get("image", ""),
                "duration": duration_secs,
                "url": stream_url,
                "ext": "mp4"
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "musical-api"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "4.0.0",
        "endpoints": {
            "/search?q=query": "Search songs",
            "/song?id=songId": "Get song details + stream URL",
            "/stream?q=query": "One-shot: search + stream URL",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
