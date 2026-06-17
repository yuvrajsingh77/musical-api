from flask import Flask, request, jsonify, redirect
import requests

app = Flask(__name__)

CLIENT_ID = "9RxIC6NwiaJEj6SsGAJgmHYOYauqhn9E"
SC_BASE = "https://api-v2.soundcloud.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://soundcloud.com",
    "Referer": "https://soundcloud.com/"
}

def get_stream_url(transcoding_url):
    """Resolve transcoding URL to actual stream URL"""
    resp = requests.get(
        transcoding_url,
        params={"client_id": CLIENT_ID},
        headers=HEADERS,
        timeout=10
    )
    if resp.status_code == 200:
        return resp.json().get("url")
    return None

def search_track(query):
    """Search SoundCloud and return best matching track with stream URL"""
    resp = requests.get(
        f"{SC_BASE}/search/tracks",
        params={
            "q": query,
            "client_id": CLIENT_ID,
            "limit": 5,
            "offset": 0
        },
        headers=HEADERS,
        timeout=15
    )
    if resp.status_code != 200:
        print(f"Search failed: {resp.status_code} {resp.text[:200]}")
        return None

    tracks = resp.json().get("collection", [])
    if not tracks:
        return None

    # Find first streamable track
    for track in tracks:
        if not track.get("streamable"):
            continue
        if track.get("policy") == "BLOCK":
            continue

        transcodings = track.get("media", {}).get("transcodings", [])

        # Prefer progressive MP3 stream
        stream_url = None
        for t in transcodings:
            fmt = t.get("format", {})
            if fmt.get("protocol") == "progressive" and "mpeg" in fmt.get("mime_type", ""):
                stream_url = get_stream_url(t["url"])
                break

        # Fallback to HLS
        if not stream_url:
            for t in transcodings:
                stream_url = get_stream_url(t["url"])
                if stream_url:
                    break

        if not stream_url:
            continue

        artwork = track.get("artwork_url", "") or ""
        artwork = artwork.replace("large", "t500x500")  # Get high res

        return {
            "id": str(track.get("id", "")),
            "title": track.get("title", "Unknown"),
            "artist": track.get("user", {}).get("username", "Unknown"),
            "album": "",
            "artwork": artwork,
            "duration": (track.get("duration", 0) or 0) // 1000,
            "url": stream_url,
            "ext": "mp3"
        }
    return None

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        resp = requests.get(
            f"{SC_BASE}/search/tracks",
            params={"q": query, "client_id": CLIENT_ID, "limit": 20},
            headers=HEADERS,
            timeout=15
        )
        if resp.status_code != 200:
            return jsonify({"success": False, "error": f"SC error {resp.status_code}"}), 500

        tracks = resp.json().get("collection", [])
        results = []
        for t in tracks:
            if not t.get("streamable") or t.get("policy") == "BLOCK":
                continue
            artwork = (t.get("artwork_url") or "").replace("large", "t500x500")
            results.append({
                "id": str(t.get("id", "")),
                "title": t.get("title", "Unknown"),
                "artist": t.get("user", {}).get("username", "Unknown"),
                "artwork": artwork,
                "duration": (t.get("duration", 0) or 0) // 1000,
            })

        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stream")
def stream():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        result = search_track(query)
        if result:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": "No streamable results"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "musical-api-soundcloud"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "7.0.0",
        "source": "SoundCloud",
        "endpoints": {
            "/search?q=query": "Search tracks",
            "/stream?q=query": "Get stream URL",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
