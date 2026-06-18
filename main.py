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

def search_youtube_id(query):
    """Use YouTube's internal web API to search"""
    try:
        url = "https://www.youtube.com/youtubei/v1/search"
        params = {"key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"}
        payload = {
            "query": query,
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20220801.00.00",
                    "hl": "en",
                    "gl": "IN"
                }
            }
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-YouTube-Client-Name": "1",
            "X-YouTube-Client-Version": "2.20220801.00.00"
        }
        resp = requests.post(
            url,
            params=params,
            json=payload,
            headers=headers,
            timeout=15
        )
        if resp.status_code != 200:
            app.logger.error(f"YouTube API returned {resp.status_code}")
            return None

        data = resp.json()
        contents = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )
        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                video = item.get("videoRenderer", {})
                video_id = video.get("videoId")
                if video_id:
                    title = video.get("title", {}).get("runs", [{}])[0].get("text", "")
                    app.logger.info(f"Found video: {video_id} - {title}")
                    return video_id

        app.logger.error("No video IDs found in YouTube API response")
        return None
    except Exception as e:
        app.logger.error(f"YouTube API search error: {e}")
        return None

def get_youtube_stream(title, artist, album=""):
    query = f"{title} {artist} official audio".strip()
    app.logger.info(f"Searching YouTube for: {query}")

    video_id = search_youtube_id(query)
    if not video_id:
        video_id = search_youtube_id(f"{title} {artist}")
    if not video_id:
        app.logger.error(f"No video ID found for: {query}")
        return None

    app.logger.info(f"Found video ID: {video_id}")
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": False,
        "no_warnings": False,
        "socket_timeout": 40,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                app.logger.error("yt-dlp returned None")
                return None

            formats = info.get("formats", [])
            app.logger.info(f"Got {len(formats)} formats")

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
                app.logger.error("No audio formats found")
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
    query = request.args.get("q", "").strip()
    title = request.args.get("title", "").strip()
    artist = request.args.get("artist", "").strip()
    album = request.args.get("album", "").strip()

    if not query and not title:
        return jsonify({"success": False, "error": "No query"}), 400

    try:
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

        stream_data = get_youtube_stream(search_title, search_artist, search_album)
        if not stream_data:
            stream_data = get_youtube_stream(search_title, search_artist)
        if not stream_data:
            stream_data = get_youtube_stream(search_title, "")
        if not stream_data:
            return jsonify({
                "success": False,
                "error": "YouTube stream failed - check Railway logs"
            }), 404

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
        "version": "11.0.0",
        "source": "iTunes (metadata) + YouTube (audio)",
        "endpoints": {
            "/search?q=query": "Search via iTunes",
            "/stream?title=X&artist=Y": "Get stream URL",
            "/audio?url=encoded_url": "Proxy audio",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
