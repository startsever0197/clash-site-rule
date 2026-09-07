#!/usr/bin/env python3
"""Chrome native messaging bridge for ClashX Pro and Clash for Windows."""
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

IS_WINDOWS = os.name == 'nt'
ROOT = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'ClashSiteRule'
        if IS_WINDOWS else Path.home() / 'Library/Application Support/ClashSiteRule')
BEGIN = '# BEGIN clash-site-rule (managed)'
END = '# END clash-site-rule (managed)'


def read_file(path):
    with path.open('r', encoding='utf-8-sig', newline='') as file:
        return file.read()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def exclusive_lock(path):
    """Lock one-byte lock file on both Windows and POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as lock:
        lock.seek(0)
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if IS_WINDOWS:
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def domain(value):
    if not isinstance(value, str):
        raise ValueError('请输入域名')
    value = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError('暂不支持 IP 地址，请使用网站域名')
    if len(value) > 253 or '.' not in value or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x)
        for x in value.split('.')
    ):
        raise ValueError('域名格式不正确，不能包含协议、路径或端口')
    return value


def render(source, rules):
    # Only edit the rule block; subscriptions may contain credentials and comments.
    if source.count(BEGIN) != source.count(END) or source.count(BEGIN) > 1:
        raise ValueError('自定义规则标记损坏，请先检查配置')
    newline = '\r\n' if '\r\n' in source else '\n'
    source = re.sub(r'(?m)^' + re.escape(BEGIN) + r'\r?\n.*?^' + re.escape(END) + r'\r?\n', '', source, flags=re.S)
    matches = list(re.finditer(r'(?m)^rules:[ \t]*(?:#[^\n]*)?\r?\n', source))
    if len(matches) != 1:
        raise ValueError('配置必须包含一个小写 rules: 列表，目前不支持内联或别名格式')
    pos = matches[0].end()
    tail = source[pos:]
    item = re.search(r'(?m)^([ \t]*)-\s', tail)
    if not item:
        raise ValueError('未找到规则列表，请先在 Clash 中选择常规 YAML 配置')
    indent = item.group(1)
    if not rules:
        return source
    block = BEGIN + newline + ''.join(
        indent + '- ' + json.dumps(f"{r['type']},{r['domain']},{r['policy']}", ensure_ascii=False) + newline
        for r in rules
    ) + END + newline
    return source[:pos] + block + source[pos:]


class Bridge:
    def __init__(self, root=ROOT):
        self.root = root
        self.settings = json.loads(read_file(root / 'settings.json'))

    def clash_home(self):
        override = self.settings.get('clash_home')
        return Path(os.path.expandvars(override)).expanduser() if override else Path.home() / '.config/clash'

    @staticmethod
    def rule_signatures(source):
        match = re.search(r'(?m)^rules:[ \t]*(?:#[^\n]*)?\r?\n', source)
        if not match:
            return set()
        lines = []
        for line in source[match.end():].splitlines():
            if line and not line[0].isspace() and not line.startswith('-'):
                break
            item = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if not item:
                continue
            value = item.group(1)
            try:
                value = json.loads(value) if value.startswith('"') else value.strip("'")
            except ValueError:
                continue
            parts = value.split(',')
            if len(parts) >= 3:
                lines.append((parts[0].upper(), parts[1], parts[-1]))
        return set(lines)

    def windows_profile(self):
        override = self.settings.get('profile_path')
        if override:
            path = Path(os.path.expandvars(override)).expanduser()
            if path.is_file():
                return path
            raise ValueError('settings.json 中的 profile_path 不存在')
        folder = self.clash_home() / 'profiles'
        candidates = [p for pattern in ('*.yaml', '*.yml') for p in folder.glob(pattern)
                      if p.name.lower() != 'list.yml']
        if not candidates:
            raise ValueError('未找到 Clash for Windows Profiles 配置文件')
        live = self.api('/rules').get('rules', [])
        type_map = {'DomainSuffix': 'DOMAIN-SUFFIX', 'DomainKeyword': 'DOMAIN-KEYWORD',
                    'IPCIDR': 'IP-CIDR', 'IPCIDR6': 'IP-CIDR6', 'GeoIP': 'GEOIP',
                    'Domain': 'DOMAIN', 'Process': 'PROCESS-NAME', 'Match': 'MATCH'}
        signatures = {(type_map.get(r.get('type'), str(r.get('type', '')).upper()),
                       str(r.get('payload', '')), str(r.get('proxy', '')))
                      for r in live[:300] if r.get('type') != 'Match'}
        ranked = []
        for path in candidates:
            try:
                score = len(signatures & self.rule_signatures(read_file(path)))
                ranked.append((score, path.stat().st_mtime_ns, path))
            except (OSError, UnicodeError):
                pass
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        if not ranked or ranked[0][0] < 2:
            raise ValueError('无法自动识别当前 Profile；请在 settings.json 设置 profile_path')
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise ValueError('多个 Profile 与运行配置相同；请在 settings.json 设置 profile_path')
        return ranked[0][2]

    def profile(self):
        if IS_WINDOWS:
            return self.windows_profile()
        name = subprocess.check_output(
            ['/usr/bin/defaults', 'read', 'com.west2online.ClashXPro', 'selectConfigName'],
            stderr=subprocess.DEVNULL, text=True, timeout=3
        ).strip()
        if not name or Path(name).name != name:
            raise ValueError('无法识别 ClashX Pro 当前配置')
        path = Path.home() / '.config/clash' / (name if name.endswith('.yaml') else name + '.yaml')
        if not path.is_file():
            raise ValueError('当前 Clash 配置文件不存在')
        return path

    def controller(self):
        configured = self.settings.get('controller')
        if configured:
            return (configured if '://' in configured else 'http://' + configured).rstrip('/')
        config = self.clash_home() / 'config.yaml'
        if config.is_file():
            match = re.search(r'(?m)^external-controller:\s*["\']?([^\s"\']+)', read_file(config))
            if match:
                address = match.group(1)
                if address.startswith(':'):
                    address = '127.0.0.1' + address
                address = re.sub(r'^(?:0\.0\.0\.0|\[?::\]?):', '127.0.0.1:', address)
                return 'http://' + address
        return 'http://127.0.0.1:9090'

    def api(self, route, payload=None):
        headers = {'Content-Type': 'application/json'}
        secret = self.settings.get('secret', '')
        if not secret:
            config = self.clash_home() / 'config.yaml'
            if config.is_file():
                match = re.search(r'(?m)^secret:\s*["\']?([^\s"\']+)', read_file(config))
                secret = match.group(1) if match else ''
        if secret:
            headers['Authorization'] = 'Bearer ' + secret
        request = urllib.request.Request(
            self.controller() + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers, method='GET' if payload is None else 'PUT'
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=8) as response:
            data = response.read()
            return json.loads(data) if data else {}

    def saved(self):
        p = self.root / 'rules.json'
        return json.loads(read_file(p)) if p.exists() else []

    def status(self):
        proxies = self.api('/proxies')['proxies']
        return {'ok': True, 'profile': self.profile().name,
                'mode': self.api('/configs').get('mode'), 'rules': self.saved(),
                'policies': ['DIRECT', 'REJECT'] + sorted(x for x, v in proxies.items()
                    if v.get('type') in ('Selector', 'URLTest', 'Fallback', 'LoadBalance', 'Relay') and x != 'GLOBAL')}

    def apply(self, rules):
        path = self.profile()
        before = read_file(path)
        updated = render(before, rules)
        self.api('/configs')  # Fail before writing if Clash is unavailable.
        backup = self.root / 'backups' / (path.name + '.' + str(time.time_ns()) + '.bak')
        atomic(backup, before)
        if read_file(path) != before or self.profile() != path:
            raise ValueError('配置刚刚发生变化，请重试')
        atomic(path, updated)
        try:
            self.api('/configs', {'path': str(path)})
            live = self.api('/rules')['rules']
            expected = [{'type': 'DomainSuffix' if r['type'] == 'DOMAIN-SUFFIX' else 'Domain',
                         'payload': r['domain'], 'proxy': r['policy']} for r in rules]
            if any(any(live[i].get(k) != v for k, v in r.items()) for i, r in enumerate(expected)):
                raise ValueError('规则未生效')
        except Exception as error:
            if read_file(path) == updated:
                atomic(path, before)
                try:
                    self.api('/configs', {'path': str(path)})
                except Exception:
                    raise ValueError('已还原文件，但 Clash 重载失败，请在菜单中重载配置') from error
            else:
                raise ValueError('配置被其他程序修改，未覆盖；备份位于 ' + str(backup)) from error
            raise ValueError('应用失败，已回滚配置；请检查 Clash 是否运行、代理组是否存在') from error
        atomic(self.root / 'rules.json', json.dumps(rules, ensure_ascii=False, indent=2))
        return dict(self.status(), backup=str(backup))

    def handle(self, message):
        action = message.get('action')
        if action == 'status':
            return self.status()
        if action not in ('add', 'delete', 'reapply'):
            raise ValueError('不支持的操作')
        rules = self.saved()
        if action in ('add', 'delete'):
            host = domain(message.get('domain'))
            kind = message.get('type')
            if kind not in ('DOMAIN', 'DOMAIN-SUFFIX'):
                raise ValueError('不支持的规则类型')
            rules = [r for r in rules if (r['domain'], r['type']) != (host, kind)]
            if action == 'add':
                policy = message.get('policy')
                if policy not in self.status()['policies'] or any(x in policy for x in ',\r\n'):
                    raise ValueError('请选择有效代理组')
                rules.insert(0, {'domain': host, 'type': kind, 'policy': policy})
        available = self.status()['policies']
        if any(r['policy'] not in available for r in rules):
            raise ValueError('保存的规则包含当前配置没有的代理组，请切回原配置或修改相应规则')
        return self.apply(rules)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(read_file(ROOT / 'settings.json'))
        if len(sys.argv) < 2 or sys.argv[1] != settings['origin']:
            raise ValueError('不允许的扩展来源')
        header = sys.stdin.buffer.read(4)
        if len(header) != 4:
            return
        length = struct.unpack('=I', header)[0]
        if length > 65536:
            raise ValueError('消息过长')
        request = json.loads(sys.stdin.buffer.read(length))
        with exclusive_lock(ROOT / 'lock'):
            result = Bridge().handle(request)
    except Exception as error:
        result = {'ok': False, 'error': str(error)}
    raw = json.dumps(result, ensure_ascii=False).encode()
    sys.stdout.buffer.write(struct.pack('=I', len(raw)) + raw)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
