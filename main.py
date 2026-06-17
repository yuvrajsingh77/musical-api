from flask import Flask, request, jsonify, Response
import requests
import yt_dlp

app = Flask(__name__)

RAILWAY_URL = "https://web-production-7318d.up.railway.app"
ITUNES_BASE = "https://itunes.apple.com"

def search_itunes(query, limit=20):
    resp = requests.get(
        f"{ITUNES_BASE}/search",
        params={
            "term": query,
            "media": "music",
            "entity": "song",
            "limit": limit,
            "country": "IN"
        },
        timeout=10
    )
    if resp.status_code != 200:
        return []
    results = []
    for t in resp.json().get("results", []):
        if t.get("kind") != "song":
            continue
        artwork = t.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        results.append({
            "id": str(t.get("trackId", "")),
            "title": t.get("trackName", "Unknown"),
            "artist": t.get("artistName", "Unknown"),
            "album": t.get("collectionName", ""),
            "artwork": artwork,
            "duration": (t.get("trackTimeMillis", 0) or 0) // 1000,
            "genre": t.get("primaryGenreName", "")
        })
    return results

def get_youtube_stream(title, artist, album=""):
    # Build precise query using iTunes metadata
    query = f"{title} {artist} {album} official audio"
    query = query.strip()

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "default_search": "ytsearch1",
        "socket_timeout": 40,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if not info or "entries" not in info or not info["entries"]:
            return None

        entry = info["entries"][0]
        formats = entry.get("formats", [])

        # Prefer audio-only
        audio_formats = [
            f for f in formats
            if f.get("acodec") != "none"
            and f.get("vcodec") == "none"
            and f.get("url")
        ]
        if not audio_formats:
            audio_formats = [
                f for f in formats
                if f.get("acodec") != "none" and f.get("url")
            ]
        if not audio_formats:
            return None

        best = max(audio_formats, key=lambda x: x.get("abr") or x.get("tbr") or 0)
        proxy_url = f"{RAILWAY_URL}/audio?url=" + requests.utils.quote(best["url"], safe="")

        return {
            "youtube_id": entry.get("id", ""),
            "url": proxy_url,
            "ext": best.get("ext", "webm")
        }

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "No query"}), 400
    try:
        results = search_itunes(query)
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stream")
def stream():
    query = request.args.get("q", "").strip()
    title = request.args.get("title", "").strip()
    artist = request.args.get("artist", "").strip()
    album = request.args.get("album", "").strip()

    if not query and not title:
        return jsonify({"success": False, "error": "No query"}), 400

    try:
        # If title+artist provided, use them directly for precise YouTube search
        # Otherwise search iTunes first to get metadata
        if title and artist:
            itunes_results = search_itunes(f"{title} {artist}", limit=1)
            itunes_song = itunes_results[0] if itunes_results else None
            search_title = title
            search_artist = artist
            search_album = album
        else:
            itunes_results = search_itunes(query, limit=1)
            if not itunes_results:
                return jsonify({"success": False, "error": "No iTunes results"}), 404
            itunes_song = itunes_results[0]
            search_title = itunes_song["title"]
            search_artist = itunes_song["artist"]
            search_album = itunes_song["album"]

        # Get YouTube stream URL
        stream_data = get_youtube_stream(search_title, search_artist, search_album)
        if not stream_data:
            return jsonify({"success": False, "error": "No YouTube stream found"}), 404

        # Combine iTunes metadata + YouTube audio
        result = {
            "id": itunes_song["id"] if itunes_song else search_title,
            "title": itunes_song["title"] if itunes_song else search_title,
            "artist": itunes_song["artist"] if itunes_song else search_artist,
            "album": itunes_song["album"] if itunes_song else search_album,
            "artwork": itunes_song["artwork"] if itunes_song else "",
            "duration": itunes_song["duration"] if itunes_song else 0,
            "url": stream_data["url"],
            "ext": stream_data["ext"]
        }
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/audio")
def audio():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL"}), 400
    try:
        range_header = request.headers.get("Range", None)
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if range_header:
            req_headers["Range"] = range_header

        resp = requests.get(
            url,
            headers=req_headers,
            stream=True,
            timeout=60
        )

        excluded = {"transfer-encoding", "connection", "keep-alive", "content-encoding"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        response_headers["Accept-Ranges"] = "bytes"
        response_headers["Access-Control-Allow-Origin"] = "*"

        def generate():
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            status=resp.status_code,
            headers=response_headers
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "musical-api-itunes-yt"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "10.0.0",
        "source": "iTunes (metadata) + YouTube (audio)",
        "endpoints": {
            "/search?q=query": "Search via iTunes",
            "/stream?q=query": "Get stream (iTunes metadata + YouTube audio)",
            "/stream?title=X&artist=Y&album=Z": "Get stream with exact metadata",
            "/audio?url=encoded_url": "Proxy audio",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
