from flask import Flask, request, jsonify
import requests
import random

app = Flask(__name__)

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.tokhmi.xyz",
    "https://piped-api.garudalinux.org",
    "https://api.piped.projectsegfau.lt",
]

def search_piped(query):
    random.shuffle(PIPED_INSTANCES)
    for instance in PIPED_INSTANCES:
        try:
            # Search for the song
            search_resp = requests.get(
                f"{instance}/search",
                params={"q": query, "filter": "music_songs"},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if search_resp.status_code != 200:
                continue

            items = search_resp.json().get("items", [])
            if not items:
                continue

            video_id = items[0].get("url", "").replace("/watch?v=", "")
            if not video_id:
                continue

            # Get streams for the video
            streams_resp = requests.get(
                f"{instance}/streams/{video_id}",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if streams_resp.status_code != 200:
                continue

            data = streams_resp.json()
            audio_streams = data.get("audioStreams", [])
            if not audio_streams:
                continue

            # Pick highest quality audio
            best = max(audio_streams, key=lambda x: x.get("bitrate", 0))

            return {
                "url": best["url"],
                "title": data.get("title", query),
                "duration": data.get("duration", 0),
                "thumbnail": data.get("thumbnailUrl", ""),
                "ext": "webm",
                "abr": best.get("bitrate", 0) // 1000,
                "source": "piped"
            }
        except Exception as e:
            print(f"Piped {instance} failed: {e}")
            continue
    return None

@app.route("/stream")
def stream():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query provided"}), 400
    try:
        result = search_piped(query)
        if result:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": False, "error": "No results found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "musical-api"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "3.0.0",
        "endpoints": {
            "/stream?q=song+name": "Get audio stream URL via Piped",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
