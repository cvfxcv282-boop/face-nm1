import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from playwright.async_api import Page, async_playwright

from cloud_app import create_app, allowed_url


class CloudTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, 'test-password-12345', executable=os.environ.get('TEST_BROWSER', '/usr/bin/chromium'), secure=False)
        self.manager = self.app['manager']
        self.client = TestClient(TestServer(self.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def post(self, path, data):
        return await self.client.post('/api/' + path, json=data, headers={'X-Nawafidh': '1'})

    async def signin(self):
        result = await self.post('login', {'password': 'test-password-12345'})
        self.assertEqual(result.status, 200)

    async def test_authentication_and_network_boundary(self):
        self.assertEqual((await self.client.get('/api/profiles')).status, 401)
        self.assertEqual((await self.client.post('/api/login', json={'password': 'test-password-12345'})).status, 403)
        self.assertEqual((await self.post('login', {'password': 'wrong'})).status, 401)
        await self.signin()
        self.assertEqual((await self.post('action', {'id': '../secret', 'action': 'open'})).status, 404)
        await self.post('logout', {})
        self.assertEqual((await self.client.get('/api/profiles')).status, 401)
        for url in ('http://127.0.0.1/', 'https://facebook.com.evil.test/', 'file:///etc/passwd', 'https://169.254.169.254/', 'https://example.com/'):
            self.assertFalse(allowed_url(url))
        self.assertTrue(allowed_url('https://www.facebook.com/'))
        self.assertTrue(allowed_url('https://static.xx.fbcdn.net/image'))

    async def test_browser_controls_isolation_and_persistence(self):
        await self.signin()
        first = await (await self.post('add', {'name': 'حساب العمل'})).json()
        second = await (await self.post('add', {'name': 'حساب آخر'})).json()
        with patch.object(Page, 'goto', new_callable=AsyncMock):
            for item in (first, second):
                response = await self.post('action', {'id': item['id'], 'action': 'open'})
                self.assertEqual(response.status, 200, await response.text())
            page = self.manager.page(first['id'])
            await page.set_content('<input id="field" style="position:absolute;left:10px;top:10px;width:300px;height:50px">')
            for action in ({'action': 'tap', 'x': 30, 'y': 30}, {'action': 'text', 'text': 'مرحبا'}, {'action': 'key', 'key': 'Enter'}, {'action': 'scroll', 'dy': 100}):
                result = await self.post('action', {'id': first['id'], **action})
                self.assertEqual(result.status, 200)
            self.assertEqual(await page.locator('#field').input_value(), 'مرحبا')
            frame = await self.client.get('/api/frame/' + first['id'])
            self.assertEqual(frame.content_type, 'image/jpeg')
            self.assertGreater(len(await frame.read()), 1000)
            context = self.manager.contexts[first['id']]
            await context.add_cookies([{'name': 'isolation-test', 'value': 'one', 'domain': '.facebook.com', 'path': '/', 'expires': 2000000000}])
            self.assertEqual(await self.manager.contexts[second['id']].cookies(), [])
            await self.post('action', {'id': first['id'], 'action': 'close'})
            await self.post('action', {'id': first['id'], 'action': 'open'})
            self.assertTrue(any(c['name'] == 'isolation-test' for c in await self.manager.contexts[first['id']].cookies()))
            self.assertEqual((await self.post('action', {'id': first['id'], 'action': 'tap', 'x': -1, 'y': 10})).status, 400)
            third = await (await self.post('add', {'name': 'ثالث'})).json()
            self.assertEqual((await self.post('action', {'id': third['id'], 'action': 'open'})).status, 400)

    async def test_android_sized_ui(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.environ.get('TEST_BROWSER', '/usr/bin/chromium'))
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(str(self.client.make_url('/')))
            await page.locator('#password').fill('test-password-12345')
            await page.get_by_role('button', name='دخول', exact=True).click()
            await page.locator('#dashboard').wait_for(state='visible')
            await page.locator('#name').fill('جلسة الهاتف')
            await page.get_by_role('button', name='＋ إضافة').click()
            await page.get_by_text('جلسة الهاتف', exact=True).wait_for()
            self.assertTrue(await page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            await page.screenshot(path='mobile-preview.png', full_page=True)
            with patch.object(Page, 'goto', new_callable=AsyncMock):
                await page.get_by_role('button', name='فتح المتصفح', exact=True).click()
                await page.locator('#viewer').wait_for(state='visible')
                ident = self.manager.profiles()[0]['id']
                remote = self.manager.page(ident)
                await remote.set_content('<input id="demo" style="position:absolute;left:10px;top:10px;width:300px;height:60px"><h2 style="margin-top:100px">Browser test</h2>')
                await page.wait_for_function("document.getElementById('screen').naturalWidth > 0")
                await page.locator('#screen').tap(position={'x': 30, 'y': 30})
                await page.locator('#typing').fill('Android input')
                await page.get_by_role('button', name='إرسال', exact=True).click()
                for _ in range(30):
                    if await remote.locator('#demo').input_value() == 'Android input':
                        break
                    await page.wait_for_timeout(100)
                self.assertEqual(await remote.locator('#demo').input_value(), 'Android input')
                await page.get_by_role('button', name='إغلاق الجلسة', exact=True).click()
                await page.locator('#dashboard').wait_for(state='visible')
            await page.get_by_role('button', name='خروج', exact=True).click()
            await page.locator('#loginPanel').wait_for(state='visible')
            self.assertFalse(errors)
            await browser.close()


if __name__ == '__main__':
    unittest.main()
