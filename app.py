import json, os, secrets, shutil, subprocess, sys, threading, uuid, webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('FB_MANAGER_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
TOKEN = secrets.token_urlsafe(32)
PORT = int(os.environ.get('PORT', '8765'))

def browser():
    candidates = [shutil.which(n) for n in ('google-chrome', 'chromium', 'chromium-browser', 'msedge')]
    candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        for tail in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            if os.environ.get(base): candidates.append(str(Path(os.environ[base]) / tail))
    return next((p for p in candidates if p and Path(p).is_file()), None)

def profiles():
    path = DATA / 'profiles.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else []

def save(items):
    tmp = DATA / 'profiles.tmp'
    tmp.write_text(json.dumps(items, ensure_ascii=False), 'utf-8')
    tmp.replace(DATA / 'profiles.json')

def launch(item):
    exe = browser()
    if not exe: raise ValueError('ثبّت Chrome أو Edge على جهازك أولًا ثم أعد المحاولة.')
    folder = DATA / 'sessions' / item['id']
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, '--user-data-dir=' + str(folder), '--new-window', '--no-first-run', 'https://www.facebook.com/'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def respond(self, status, value, html=False):
        body = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')
    def do_GET(self):
        if not self.valid_host(): return self.respond(403, {'error': 'Forbidden'})
        if self.path == '/': return self.respond(200, (ROOT / 'index.html').read_text('utf-8').replace('__TOKEN__', TOKEN), True)
        if self.path == '/api/profiles': return self.respond(200, {'profiles': profiles(), 'browser': bool(browser())})
        self.respond(404, {'error': 'Not found'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-App-Token') != TOKEN:
            return self.respond(403, {'error': 'Forbidden'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > 4096: raise ValueError('طلب غير صالح')
            body = json.loads(self.rfile.read(size))
            items = profiles()
            if self.path == '/api/add':
                name = str(body.get('name', '')).strip()
                if not name or len(name) > 60: raise ValueError('أدخل اسمًا بين حرف و60 حرفًا.')
                if len(items) >= 30: raise ValueError('الحد الأقصى 30 ملفًا.')
                items.append({'id': uuid.uuid4().hex, 'name': name})
                save(items)
                return self.respond(200, {'ok': True})
            if self.path == '/api/open':
                ids = body.get('ids', [])
                if not isinstance(ids, list) or not 1 <= len(ids) <= 10: raise ValueError('اختر من ملف واحد إلى 10 ملفات في المرة الواحدة.')
                selected = [p for p in items if p['id'] in ids]
                if len(selected) != len(set(ids)): raise ValueError('ملف غير موجود.')
                opened = []
                for p in selected:
                    launch(p)
                    opened.append(p['id'])
                return self.respond(200, {'opened': opened})
            self.respond(404, {'error': 'Not found'})
        except (ValueError, TypeError, OSError) as e:
            self.respond(400, {'error': str(e)})

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Open http://127.0.0.1:{PORT} — Ctrl+C to stop', flush=True)
    if '--no-browser' not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
