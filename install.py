#!/usr/bin/env python3
import base64
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys

PROJECT = Path(__file__).resolve().parent
ROOT = Path.home() / 'Library/Application Support/ClashSiteRule'
ROOT.mkdir(parents=True, exist_ok=True)
manifest = json.loads((PROJECT / 'extension/manifest.json').read_text())
digest = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
extension_id = ''.join(chr(ord('a') + int(c, 16)) for c in digest)
origin = 'chrome-extension://' + extension_id + '/'
shutil.copy2(PROJECT / 'native/host.py', ROOT / 'host.py')
launcher = ROOT / 'launch.sh'
launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'host.py')) + ' "$@"\n')
launcher.chmod(0o700)
settings = ROOT / 'settings.json'
data = json.loads(settings.read_text()) if settings.exists() else {'secret': ''}
data['origin'] = origin
settings.write_text(json.dumps(data, indent=2))
settings.chmod(0o600)
hosts = Path.home() / 'Library/Application Support/Google/Chrome/NativeMessagingHosts'
hosts.mkdir(parents=True, exist_ok=True)
(hosts / 'local.clash_site_rule.json').write_text(json.dumps({
    'name': 'local.clash_site_rule', 'description': 'Clash site rule editor',
    'path': str(launcher), 'type': 'stdio', 'allowed_origins': [origin]
}, indent=2))
print('本地辅助程序安装完成。扩展 ID：' + extension_id)
print('在 chrome://extensions 打开开发者模式，加载已解压的扩展程序，选择：')
print(PROJECT / 'extension')
