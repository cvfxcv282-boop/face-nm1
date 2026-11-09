"""Start the private Codespaces app and display its locally generated password."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'codespaces'
PORT = 10000


def healthy():
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health', timeout=2) as response:
            return response.status == 200 and response.read() == b'ok'
    except OSError:
        return False


def main():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    password_file = DATA / 'app-password.txt'
    if not password_file.exists():
        with password_file.open('x', encoding='utf-8') as file:
            os.chmod(password_file, 0o600)
            file.write(secrets.token_urlsafe(24))
    password = password_file.read_text('utf-8').strip()
    if not healthy():
        env = os.environ.copy()
        env.update(APP_PASSWORD=password, FB_MANAGER_DATA=str(DATA), PORT=str(PORT), COOKIE_SECURE='1')
        with (DATA / 'server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'cloud_app.py')], cwd=ROOT,
                                       env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        for _ in range(40):
            if healthy():
                break
            if process.poll() is not None:
                raise SystemExit('تعذر التشغيل. راجع data/codespaces/server.log')
            time.sleep(0.25)
        else:
            raise SystemExit('الخادم لم يصبح جاهزًا. راجع data/codespaces/server.log')
    print('\nنوافذ جاهز. كلمة مرور الأداة الخاصة بك:\n' + password)
    name = os.environ.get('CODESPACE_NAME')
    domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')
    if name:
        print(f'\nافتح: https://{name}-{PORT}.{domain}')
    else:
        print('\nمن تبويب Ports افتح المنفذ 10000.')
    print('\nاحتفظ بالمنفذ Private. عند الانتهاء أوقف Codespace لتوفير حصتك المجانية.')


if __name__ == '__main__':
    main()
