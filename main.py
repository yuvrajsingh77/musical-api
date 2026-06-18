from flask import Flask, request, jsonify, Response
import requests

app = Flask(__name__)

RAILWAY_URL = "https://web-production-7318d.up.railway.app"
ITUNES_BASE = "https://itunes.apple.com"
SC_BASE = "https://api-v2.soundcloud.com"
CLIENT_ID = "9RxIC6NwiaJEj6SsGAJgmHYOYauqhn9E"

SC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://soundcloud.com",
    "Referer": "https://soundcloud.com/"
}

def search_itunes(query, limit=20):
    try:
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
    except Exception as e:
        app.logger.error(f"iTunes search error: {e}")
        return []

def get_sc_stream_url(transcoding_url):
    try:
        resp = requests.get(
            transcoding_url,
            params={"client_id": CLIENT_ID},
            headers=SC_HEADERS,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("url")
    except Exception as e:
        app.logger.error(f"SC transcoding error: {e}")
    return None

def search_youtube_music_id(query):
    """Search YouTube Music for video ID"""
    try:
        # YouTube Music internal API
        url = "https://music.youtube.com/youtubei/v1/search"
        params = {"key": "AIzaSyC9XL3ZjWddXya6X74dJoCTL-NKNELL6tv"}
        payload = {
            "query": query,
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20220727.01.00",
                    "hl": "en",
                    "gl": "IN"
                }
            }
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Referer": "https://music.youtube.com/",
            "Origin": "https://music.youtube.com"
        }
        resp = requests.post(
            url,
            params=params,
            json=payload,
            headers=headers,
            timeout=15
        )
        if resp.status_code != 200:
            app.logger.error(f"YTMusic API: {resp.status_code}")
            return None

        # Parse response to find video IDs
        import re
        data = resp.text
        video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', data)
        
        seen = set()
        for vid in video_ids:
            if vid not in seen:
                seen.add(vid)
                app.logger.info(f"Found YTMusic video ID: {vid}")
                return vid

        return None
    except Exception as e:
        app.logger.error(f"YTMusic search error: {e}")
        return None

def get_youtube_stream(title, artist, album=""):
    query = f"{title} {artist}".strip()
    app.logger.info(f"Searching YouTube Music for: {query}")

    video_id = search_youtube_music_id(query)
    if not video_id:
        app.logger.error(f"No video ID found")
        return None

    app.logger.info(f"Got video ID: {video_id}")
    video_url = f"https://music.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": False,
        "no_warnings": False,
        "socket_timeout": 40,
        "extractor_args": {
            "youtube": {
                "player_client": ["web_music"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.youtube.com/",
            "Origin": "https://music.youtube.com"
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return None

            formats = info.get("formats", [])
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
            app.logger.info(f"Best: {best.get('ext')} {best.get('abr')}kbps")

            proxy_url = f"{RAILWAY_URL}/audio?url=" + requests.utils.quote(best["url"], safe="")
            return {
                "youtube_id": video_id,
                "url": proxy_url,
                "ext": best.get("ext", "webm")
            }
    except Exception as e:
        app.logger.error(f"yt-dlp error: {type(e).__name__}: {str(e)}")
        return None
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
    title = request.args.get("title", "").strip()
    artist = request.args.get("artist", "").strip()
    query = request.args.get("q", "").strip()

    if not title and not query:
        return jsonify({"success": False, "error": "Provide title+artist or q"}), 400

    try:
        # Step 1: Get iTunes metadata
        if title and artist:
            itunes_results = search_itunes(f"{title} {artist}", limit=1)
        else:
            itunes_results = search_itunes(query, limit=1)

        if itunes_results:
            itunes_song = itunes_results[0]
            search_title = itunes_song["title"]
            search_artist = itunes_song["artist"]
        else:
            # Use provided params directly
            itunes_song = None
            search_title = title or query
            search_artist = artist

        app.logger.info(f"Searching SC for: {search_title} - {search_artist}")

        # Step 2: Search SoundCloud with iTunes metadata
        sc_data = search_soundcloud(search_title, search_artist)
        if not sc_data:
            return jsonify({
                "success": False,
                "error": f"No SoundCloud stream found for: {search_title} {search_artist}"
            }), 404

        # Step 3: Combine iTunes metadata + SoundCloud audio
        result = {
            "id": itunes_song["id"] if itunes_song else search_title,
            "title": itunes_song["title"] if itunes_song else search_title,
            "artist": itunes_song["artist"] if itunes_song else search_artist,
            "album": itunes_song["album"] if itunes_song else "",
            "artwork": itunes_song["artwork"] if itunes_song else sc_data.get("sc_artwork", ""),
            "duration": itunes_song["duration"] if itunes_song else sc_data.get("duration", 0),
            "url": sc_data["url"],
            "ext": "mp3"
        }
        return jsonify({"success": True, "data": result})

    except Exception as e:
        app.logger.error(f"Stream error: {e}")
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
            "Referer": "https://soundcloud.com/",
            "Origin": "https://soundcloud.com"
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
    return jsonify({"status": "ok", "service": "musical-api-itunes-sc"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "12.0.0",
        "source": "iTunes (metadata) + SoundCloud (audio via Railway proxy)",
        "endpoints": {
            "/search?q=query": "Search via iTunes",
            "/stream?title=X&artist=Y": "Get stream",
            "/audio?url=encoded_url": "Proxy audio",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
