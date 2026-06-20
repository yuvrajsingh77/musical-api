from flask import Flask, request, jsonify, Response
import requests
import yt_dlp
import re

app = Flask(__name__)

RAILWAY_URL = "https://web-production-7318d.up.railway.app"
ITUNES_BASE = "https://itunes.apple.com"

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
        app.logger.error(f"iTunes error: {e}")
        return []

def search_youtube_music_id(query):
    """Search YouTube Music - try multiple approaches"""

    # Approach 1: YouTube Music API
    try:
        url = "https://music.youtube.com/youtubei/v1/search"
        params = {"key": "AIzaSyC9XL3ZjWddXya6X74dJoCTL-NKNELL6tv", "prettyPrint": "false"}
        payload = {
            "query": query,
            "params": "EgWKAQIIAWoKEAkQBRAKEAMQBA%3D%3D",
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20230501.01.00",
                    "hl": "en",
                    "gl": "US",
                    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            }
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Referer": "https://music.youtube.com/",
            "Origin": "https://music.youtube.com",
            "X-YouTube-Client-Name": "67",
            "X-YouTube-Client-Version": "1.20230501.01.00"
        }
        resp = requests.post(
            url, params=params, json=payload, headers=headers, timeout=15
        )
        app.logger.info(f"YTMusic API status: {resp.status_code}")
        if resp.status_code == 200:
            text = resp.text
            ids = re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', text)
            ids2 = re.findall(r'videoId":"([a-zA-Z0-9_-]{11})"', text)
            all_ids = list(dict.fromkeys(ids + ids2))
            app.logger.info(f"Found {len(all_ids)} video IDs in YTMusic response")
            if all_ids:
                app.logger.info(f"First ID: {all_ids[0]}")
                return all_ids[0]
            else:
                app.logger.error(f"YTMusic response preview: {text[:500]}")
    except Exception as e:
        app.logger.error(f"YTMusic API error: {e}")

    # Approach 2: Regular YouTube search API
    try:
        url2 = "https://www.youtube.com/youtubei/v1/search"
        params2 = {"key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"}
        payload2 = {
            "query": f"{query} audio",
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20230501.00.00",
                    "hl": "en",
                    "gl": "IN"
                }
            }
        }
        headers2 = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
        resp2 = requests.post(
            url2, params=params2, json=payload2, headers=headers2, timeout=15
        )
        app.logger.info(f"YouTube API status: {resp2.status_code}")
        if resp2.status_code == 200:
            text2 = resp2.text
            ids3 = re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', text2)
            unique = list(dict.fromkeys(ids3))
            app.logger.info(f"Found {len(unique)} IDs from YouTube API")
            if unique:
                app.logger.info(f"First YouTube ID: {unique[0]}")
                return unique[0]
            else:
                app.logger.error(f"YouTube response preview: {text2[:500]}")
    except Exception as e:
        app.logger.error(f"YouTube API error: {e}")

    return None

def get_stream(title, artist):
    query = f"{title} {artist}".strip()
    app.logger.info(f"Getting stream for: {query}")

    video_id = search_youtube_music_id(query)
    if not video_id:
        video_id = search_youtube_music_id(title)
    if not video_id:
        app.logger.error("No video ID found from any source")
        return None

    app.logger.info(f"Using video ID: {video_id}")
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
            app.logger.info(f"Best format: {best.get('ext')} {best.get('abr')}kbps")

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
        if title and artist:
            itunes_results = search_itunes(f"{title} {artist}", limit=1)
        else:
            itunes_results = search_itunes(query, limit=1)

        if itunes_results:
            itunes_song = itunes_results[0]
            search_title = itunes_song["title"]
            search_artist = itunes_song["artist"]
        else:
            itunes_song = None
            search_title = title or query
            search_artist = artist

        app.logger.info(f"iTunes result: {search_title} - {search_artist}")

        stream_data = get_stream(search_title, search_artist)
        if not stream_data:
            stream_data = get_stream(search_title, "")
        if not stream_data:
            return jsonify({
                "success": False,
                "error": f"No stream found for: {search_title} {search_artist}"
            }), 404

        result = {
            "id": itunes_song["id"] if itunes_song else search_title,
            "title": itunes_song["title"] if itunes_song else search_title,
            "artist": itunes_song["artist"] if itunes_song else search_artist,
            "album": itunes_song["album"] if itunes_song else "",
            "artwork": itunes_song["artwork"] if itunes_song else "",
            "duration": itunes_song["duration"] if itunes_song else 0,
            "url": stream_data["url"],
            "ext": stream_data["ext"]
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
            "Referer": "https://music.youtube.com/",
            "Origin": "https://music.youtube.com"
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
    return jsonify({"status": "ok", "service": "musical-api-ytmusic"})

@app.route("/")
def index():
    return jsonify({
        "name": "Musical API",
        "version": "14.0.0",
        "source": "iTunes (metadata) + YouTube Music (audio)",
        "endpoints": {
            "/search?q=query": "Search via iTunes",
            "/stream?title=X&artist=Y": "Get stream",
            "/audio?url=encoded_url": "Proxy audio",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
