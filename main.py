from flask import Flask, request, jsonify, Response
import requests
import re

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
        app.logger.error(f"iTunes error: {e}")
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

def search_soundcloud(title, artist):
    queries = [
        f"{title} {artist}",
        f"{title} {artist.split(',')[0].strip()}",
        f"{title}",
    ]
    for query in queries:
        try:
            app.logger.info(f"SC query: {query}")
            resp = requests.get(
                f"{SC_BASE}/search/tracks",
                params={
                    "q": query,
                    "client_id": CLIENT_ID,
                    "limit": 10,
                    "offset": 0
                },
                headers=SC_HEADERS,
                timeout=15
            )
            if resp.status_code != 200:
                app.logger.error(f"SC {resp.status_code} for: {query}")
                continue

            tracks = resp.json().get("collection", [])
            app.logger.info(f"SC returned {len(tracks)} tracks")

            for track in tracks:
                if not track.get("streamable"):
                    continue
                if track.get("policy") == "BLOCK":
                    continue

                transcodings = track.get("media", {}).get("transcodings", [])
                raw_url = None

                # Prefer progressive MP3
                for t in transcodings:
                    fmt = t.get("format", {})
                    if fmt.get("protocol") == "progressive" and "mpeg" in fmt.get("mime_type", ""):
                        raw_url = get_sc_stream_url(t["url"])
                        break

                # Fallback to any format
                if not raw_url:
                    for t in transcodings:
                        raw_url = get_sc_stream_url(t["url"])
                        if raw_url:
                            break

                if not raw_url:
                    continue

                artwork = (track.get("artwork_url") or "").replace("large", "t500x500")
                proxy_url = f"{RAILWAY_URL}/audio?url=" + requests.utils.quote(raw_url, safe="")
                app.logger.info(f"SC stream found: {track.get('title')}")

                return {
                    "sc_id": str(track.get("id", "")),
                    "sc_title": track.get("title", ""),
                    "sc_artwork": artwork,
                    "url": proxy_url,
                    "duration": (track.get("duration", 0) or 0) // 1000
                }
        except Exception as e:
            app.logger.error(f"SC exception: {e}")
            continue
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
        # Step 1: iTunes metadata
        if title and artist:
            itunes_results = search_itunes(f"{title} {artist}", limit=1)
        elif title:
            itunes_results = search_itunes(title, limit=1)
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

        app.logger.info(f"Searching SC for: {search_title} - {search_artist}")

        # Step 2: SoundCloud audio
        sc_data = search_soundcloud(search_title, search_artist)
        if not sc_data:
            return jsonify({
                "success": False,
                "error": f"No stream found for: {search_title}"
            }), 404

        # Step 3: Combine iTunes metadata + SC audio
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
        "version": "16.0.0",
        "source": "iTunes (metadata) + SoundCloud (audio)",
        "endpoints": {
            "/search?q=query": "Search via iTunes",
            "/stream?title=X&artist=Y": "Get stream",
            "/stream?q=query": "Get stream by query",
            "/audio?url=encoded_url": "Proxy audio",
            "/health": "Health check"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
