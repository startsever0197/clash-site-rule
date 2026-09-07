import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('host', Path(__file__).parents[1] / 'native/host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

SOURCE = 'proxies:\n  - {name: private, password: unchanged}\nrules:\n - DOMAIN-SUFFIX,cc98.org,DIRECT\n - MATCH,Proxy\n'
RULE = {'domain': 'example.org', 'type': 'DOMAIN-SUFFIX', 'policy': 'DIRECT'}


class Tests(unittest.TestCase):
    def test_domain_validation(self):
        self.assertEqual(host.domain('WWW.Example.org.'), 'www.example.org')
        self.assertEqual(host.domain('例子.中国'), 'xn--fsqu00a.xn--fiqs8s')
        for value in ['https://a.com', 'a.com,DIRECT', 'a.com\n- MATCH,REJECT', '127.0.0.1', 'a..com', '-a.com']:
            with self.assertRaises(ValueError): host.domain(value)

    def test_roundtrip_preserves_original(self):
        rendered = host.render(SOURCE, [RULE])
        self.assertLess(rendered.index('example.org'), rendered.index('cc98.org'))
        self.assertEqual(host.render(rendered, []), SOURCE)
        self.assertEqual(host.render(rendered, [RULE]), rendered)

    def test_unicode_policy_is_quoted(self):
        output = host.render(SOURCE, [dict(RULE, policy='🇨🇳 国内网站')])
        self.assertIn('"DOMAIN-SUFFIX,example.org,🇨🇳 国内网站"', output)

    def test_reject_unsupported_yaml(self):
        for source in ['rules: [MATCH,DIRECT]\n', 'rules: *alias\n', SOURCE + 'rules:\n - MATCH,DIRECT\n']:
            with self.assertRaises(ValueError): host.render(source, [RULE])

    def test_apply_rolls_back_on_reload_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'settings.json').write_text('{}')
            profile = root / 'profile.yaml'; profile.write_text(SOURCE)
            bridge = host.Bridge(root)
            calls = []
            def api(route, payload=None):
                calls.append(payload)
                if payload and len(calls) == 2: raise OSError('reload failed')
                return {}
            with patch.object(bridge, 'profile', return_value=profile), patch.object(bridge, 'api', side_effect=api):
                with self.assertRaisesRegex(ValueError, '已回滚'): bridge.apply([RULE])
            self.assertEqual(profile.read_text(), SOURCE)
            self.assertFalse((root / 'rules.json').exists())
            self.assertEqual(len(list((root / 'backups').iterdir())), 1)

    def test_success_verifies_runtime_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'settings.json').write_text('{}')
            profile = root / 'profile.yaml'; profile.write_text(SOURCE)
            bridge = host.Bridge(root)
            def api(route, payload=None):
                return {'rules': [{'type': 'DomainSuffix', 'payload': 'example.org', 'proxy': 'DIRECT'}]} if route == '/rules' else {}
            with patch.object(bridge, 'profile', return_value=profile), patch.object(bridge, 'api', side_effect=api), patch.object(bridge, 'status', return_value={'ok': True}):
                self.assertTrue(bridge.apply([RULE])['ok'])
            self.assertEqual(json.loads((root / 'rules.json').read_text()), [RULE])

    def test_replace_does_not_duplicate(self):
        bridge = object.__new__(host.Bridge)
        with patch.object(bridge, 'saved', return_value=[RULE]), patch.object(bridge, 'status', return_value={'policies': ['DIRECT', 'REJECT']}), patch.object(bridge, 'apply', side_effect=lambda r: r):
            result = bridge.handle(dict(RULE, action='add', policy='REJECT'))
            self.assertEqual(result, [dict(RULE, policy='REJECT')])


if __name__ == '__main__': unittest.main()
