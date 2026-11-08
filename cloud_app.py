"""Single-owner remote browser for mobile clients. Run behind HTTPS."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import uuid
from urllib.parse import urlsplit

from aiohttp import web
from playwright.async_api import async_playwright, Error as BrowserError

ROOT = Path(__file__).resolve().parent
ALLOWED = ('facebook.com', 'fbcdn.net', 'fbsbx.com')


def allowed_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme in ('https', 'wss') and any(host == d or host.endswith('.' + d) for d in ALLOWED)


class Manager:
    def __init__(self, data, executable=None, limit=2):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.executable = executable
        self.limit = limit
        self.contexts = {}
        self.lock = asyncio.Lock()
        self.pw = None

    def profiles(self):
        path = self.data / 'profiles.json'
        return json.loads(path.read_text('utf-8')) if path.exists() else []

    def save(self, items):
        temp = self.data / 'profiles.tmp'
        temp.write_text(json.dumps(items, ensure_ascii=False), 'utf-8')
        temp.replace(self.data / 'profiles.json')

    def exists(self, ident):
        return any(p['id'] == ident for p in self.profiles())

    async def start(self, ident):
        if not self.exists(ident):
            raise ValueError('الملف غير موجود.')
        if ident in self.contexts:
            return
        if len(self.contexts) >= self.limit:
            raise ValueError(f'يمكن تشغيل {self.limit} جلسات معًا. أغلق إحدى الجلسات أولًا.')
        if not self.pw:
            self.pw = await async_playwright().start()
        context = await self.pw.chromium.launch_persistent_context(
            str(self.data / 'sessions' / ident), executable_path=self.executable,
            headless=True, viewport={'width': 390, 'height': 700},
            is_mobile=True, has_touch=True, device_scale_factor=1,
            accept_downloads=False, service_workers='block',
            args=['--disable-dev-shm-usage'],
        )
        # Restrict browser requests to Facebook and its asset domains.
        async def route(request):
            if allowed_url(request.request.url):
                await request.continue_()
            else:
                await request.abort()
        await context.route('**/*', route)
        async def websocket(ws):
            if allowed_url(ws.url):
                ws.connect_to_server()
            else:
                await ws.close()
        await context.route_web_socket('**/*', websocket)
        self.contexts[ident] = context
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(8000)
            await page.goto('https://www.facebook.com/', wait_until='domcontentloaded', timeout=45000)
        except BrowserError:
            await context.close()
            self.contexts.pop(ident, None)
            raise ValueError('تعذر تحميل فيسبوك على الخادم. تحقق من اتصال الاستضافة ثم أعد الفتح.')

    def page(self, ident):
        context = self.contexts.get(ident)
        if not context or not context.pages:
            raise ValueError('الجلسة مغلقة. افتحها من القائمة.')
        return context.pages[-1]

    async def close(self, ident):
        context = self.contexts.pop(ident, None)
        if context:
            await context.close()

    async def shutdown(self):
        for ident in list(self.contexts):
            await self.close(ident)
        if self.pw:
            await self.pw.stop()


def create_app(data, password, executable=None, secure=True, limit=2):
    if len(password) < 12:
        raise ValueError('Set APP_PASSWORD to at least 12 characters before starting.')
    if not 1 <= limit <= 10:
        raise ValueError('MAX_ACTIVE_SESSIONS must be between 1 and 10.')
    manager = Manager(data, executable, limit)
    sessions = {}
    attempts = []

    @web.middleware
    async def guard(request, handler):
        try:
            if request.method == 'POST' and request.headers.get('X-Nawafidh') != '1':
                raise web.HTTPForbidden()
            if request.method == 'POST' and not isinstance(await request.json(), dict):
                raise ValueError('Expected an object')
            if request.path.startswith('/api/') and request.path != '/api/login':
                now = time.time()
                token = request.cookies.get('nawafidh', '')
                if sessions.get(token, 0) <= now:
                    return web.json_response({'error': 'سجّل الدخول إلى الأداة أولًا.'}, status=401)
            response = await handler(request)
        except (ValueError, KeyError, TypeError):
            response = web.json_response({'error': 'تعذر تنفيذ الطلب. تحقق من المدخلات وحالة الجلسة.'}, status=400)
        except BrowserError:
            response = web.json_response({'error': 'تعذر التحكم في المتصفح. أغلق الجلسة ثم افتحها مجددًا.'}, status=400)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    app = web.Application(middlewares=[guard], client_max_size=16384)
    app['manager'] = manager

    async def home(request):
        return web.Response(text=(ROOT / 'mobile.html').read_text('utf-8'), content_type='text/html')

    async def javascript(request):
        return web.Response(text=(ROOT / 'mobile.js').read_text('utf-8'), content_type='application/javascript')

    async def health(request):
        return web.Response(text='ok')

    async def login(request):
        now = time.time()
        attempts[:] = [t for t in attempts if now - t < 60]
        if len(attempts) >= 10:
            return web.json_response({'error': 'انتظر دقيقة قبل إعادة المحاولة.'}, status=429)
        attempts.append(now)
        body = await request.json()
        candidate = body.get('password', '')
        if not isinstance(candidate, str) or not hmac.compare_digest(candidate.encode(), password.encode()):
            return web.json_response({'error': 'كلمة مرور الأداة غير صحيحة.'}, status=401)
        for token in list(sessions):
            if sessions[token] <= now:
                del sessions[token]
        if len(sessions) >= 16:
            del sessions[next(iter(sessions))]
        token = secrets.token_urlsafe(32)
        sessions[token] = now + 43200
        response = web.json_response({'ok': True})
        response.set_cookie('nawafidh', token, httponly=True, secure=secure, samesite='Strict', max_age=43200)
        return response

    async def logout(request):
        sessions.pop(request.cookies.get('nawafidh', ''), None)
        response = web.json_response({'ok': True})
        response.del_cookie('nawafidh')
        return response

    async def profiles(request):
        return web.json_response({'profiles': [dict(p, running=p['id'] in manager.contexts) for p in manager.profiles()], 'limit': limit})

    async def add(request):
        body = await request.json()
        name = body.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            return web.json_response({'error': 'اكتب اسمًا بين حرف و60 حرفًا.'}, status=400)
        async with manager.lock:
            items = manager.profiles()
            if len(items) >= 30:
                return web.json_response({'error': 'الحد الأقصى 30 ملفًا.'}, status=400)
            item = {'id': uuid.uuid4().hex, 'name': name.strip()}
            manager.save(items + [item])
        return web.json_response(item)

    async def action(request):
        body = await request.json()
        ident, kind = body.get('id'), body.get('action')
        if not isinstance(ident, str) or not manager.exists(ident):
            return web.json_response({'error': 'الملف غير موجود.'}, status=404)
        async with manager.lock:
            try:
                if kind == 'open':
                    await manager.start(ident)
                elif kind == 'close':
                    await manager.close(ident)
                else:
                    page = manager.page(ident)
                    if kind == 'tap':
                        x, y = int(body['x']), int(body['y'])
                        if not (0 <= x < 390 and 0 <= y < 700):
                            raise ValueError()
                        await page.touchscreen.tap(x, y)
                    elif kind == 'text':
                        text = body.get('text')
                        if not isinstance(text, str) or not 0 < len(text) <= 2000:
                            raise ValueError()
                        await page.keyboard.insert_text(text)
                    elif kind == 'key':
                        key = body.get('key')
                        if key not in ('Enter', 'Tab', 'Backspace', 'ControlOrMeta+A', 'Escape'):
                            raise ValueError()
                        await page.keyboard.press(key)
                    elif kind == 'scroll':
                        await page.mouse.wheel(0, max(-650, min(650, int(body['dy']))))
                    elif kind == 'reload':
                        await page.reload(wait_until='domcontentloaded', timeout=30000)
                    elif kind == 'back':
                        await page.go_back(wait_until='domcontentloaded', timeout=30000)
                    else:
                        raise ValueError()
            except ValueError as error:
                return web.json_response({'error': str(error) or 'طلب غير صالح.'}, status=400)
        return web.json_response({'ok': True})

    async def frame(request):
        ident = request.match_info['ident']
        async with manager.lock:
            page = manager.page(ident)
            image = await page.screenshot(type='jpeg', quality=65, timeout=10000)
        return web.Response(body=image, content_type='image/jpeg')

    async def cleanup(app):
        await manager.shutdown()

    app.add_routes([web.get('/', home), web.get('/mobile.js', javascript), web.get('/health', health),
                    web.post('/api/login', login), web.post('/api/logout', logout),
                    web.get('/api/profiles', profiles), web.post('/api/add', add),
                    web.post('/api/action', action), web.get('/api/frame/{ident}', frame)])
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    app = create_app(os.environ.get('FB_MANAGER_DATA', ROOT / 'data'), os.environ.get('APP_PASSWORD', ''),
                     os.environ.get('BROWSER_EXECUTABLE'), os.environ.get('COOKIE_SECURE', '1') != '0',
                     int(os.environ.get('MAX_ACTIVE_SESSIONS', '2')))
    web.run_app(app, host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), access_log=None)
