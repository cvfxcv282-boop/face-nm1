"""Prepare a mounted data directory, then run the service without root privileges."""
import os
from pathlib import Path
import pwd
import sys

if os.getuid() == 0:
    account = pwd.getpwnam('appuser')
    data = Path(os.environ.get('FB_MANAGER_DATA', '/app/data'))
    data.mkdir(parents=True, exist_ok=True)
    os.chown(data, account.pw_uid, account.pw_gid)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ['HOME'] = account.pw_dir
os.execv(sys.executable, [sys.executable, '/app/cloud_app.py'])
