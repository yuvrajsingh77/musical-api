from flask import Flask, request, jsonify
import requests
import yt_dlp
import random

app = Flask(__name__)

INVIDIOUS_INSTANCES = [
    "https://invidious.nerdvpn.de",
    "https://invidious.privacyredirect.com",
    "https://inv.nadeko.net",
    "https://invidious.io.lol",
    "https://iv.melmac.space",
]

def search_invidious(query):
    random.shuffle(INVIDIOUS_INSTANCES)
    for instance in INVIDIOUS_INSTANCES:
        try:
            resp = requests.get(f"{instance}/api/v1/search",
                params={"q": query, "type": "video", "sort_by": "relevance"},
                timeout=10)
            if resp.status_code != 200:
                continue
            results = resp.json()
            if not results:
                continue
            video_id = results[0].get("videoId")
            if not video_id:
                continue
            video_resp = requests.get(f"{instance}/api/v1/videos/{video_id}", timeout=10)
            if video_resp.status_code != 200:
                continue
            video_data = video_resp.json()
            audio_formats = [
                f for f in video_data.get("adaptiveFormats", [])
                if f.get("type", "").startswith("audio/")
            ]
            if not audio_formats:
                continue
            audio_formats.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
            best = audio_formats[0]
            return {
                "url": best["url"],
                "title": video_data.get("title", query),
                "duration": video_data.get("lengthSeconds", 0),
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "ext": "webm",
                "abr": best.get("bitrate", 0) // 1000,
                "source": "invidious"
            }
        except Exception as e:
            print(f"Invidious {instance} failed: {e}")
            continue
    return None

def search_ytdlp_fallback(query):
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "socket_timeout": 30,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if info and "entries" in info and info["entries"]:
            entry = info["entries"][0]
            formats = entry.get("formats", [])
            audio_formats = [
                f for f in formats
                if f.get("acodec") != "none"
                and f.get("vcodec") == "none"
                and f.get("url")
            ]
            if not audio_formats:
                audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("url")]
            if audio_formats:
                best = max(audio_formats, key=lambda x: x.get("abr") or x.get("tbr") or 0)
                return {
                    "url": best["url"],
                    "title": entry.get("title", ""),
                    "duration": entry.get("duration", 0),
                    "thumbnail": entry.get("thumbnail", ""),
                    "ext": best.get("ext", "webm"),
                    "abr": best.get("abr", 0),
                    "source": "ytdlp"
                }
    return None

@app.route("/stream")
def stream():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query provided"}), 400
    try:
        result = search_invidious(query)
        if not result:
            result = search_ytdlp_fallback(query)
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
        "version": "2.0.0",
        "endpoints": {
            "/stream?q=song+name": "Get audio stream URL",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
