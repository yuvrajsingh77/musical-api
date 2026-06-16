from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

def search_youtube(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'default_search': 'ytsearch1',
        'source_address': '0.0.0.0',
        'socket_timeout': 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if info and 'entries' in info and info['entries']:
            entry = info['entries'][0]
            formats = entry.get('formats', [])
            audio_formats = [
                f for f in formats
                if f.get('acodec') != 'none'
                and f.get('vcodec') == 'none'
                and f.get('url')
            ]
            if not audio_formats:
                audio_formats = [
                    f for f in formats
                    if f.get('acodec') != 'none'
                    and f.get('url')
                ]
            if audio_formats:
                best = max(
                    audio_formats,
                    key=lambda x: x.get('abr') or x.get('tbr') or 0
                )
                return {
                    'url': best['url'],
                    'title': entry.get('title', ''),
                    'duration': entry.get('duration', 0),
                    'thumbnail': entry.get('thumbnail', ''),
                    'ext': best.get('ext', 'webm'),
                    'abr': best.get('abr', 0)
                }
    return None

@app.route('/stream')
def stream():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'No query provided'}), 400
    try:
        result = search_youtube(query)
        if result:
            return jsonify({'success': True, 'data': result})
        return jsonify({'success': False, 'error': 'No results found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'musical-api'})

@app.route('/')
def index():
    return jsonify({
        'name': 'Musical API',
        'version': '1.0.0',
        'endpoints': {
            '/stream?q=song+name': 'Get YouTube audio stream URL',
            '/health': 'Health check'
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
