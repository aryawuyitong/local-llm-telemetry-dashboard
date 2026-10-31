"""Exercise shipped UTF-8 resources under a simulated Windows cp1252 default."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import agent, config, tools

PROJECT = Path(__file__).resolve().parents[2]
_ORIGINAL_PATH_OPEN = Path.open


def windows_default_open(path, *args, **kwargs):
    mode = args[0] if args else kwargs.get('mode', 'r')
    if 'b' not in mode and kwargs.get('encoding') in (None, 'locale'):
        kwargs['encoding'] = 'cp1252'
    return _ORIGINAL_PATH_OPEN(path, *args, **kwargs)


class MinimalTools:
    allow_list = [{'ollama_tag': 'qwen2.5:0.5b'}]

    def schemas(self):
        return [{'function': {'name': 'check_hardware'}}]


class TextEncoding(unittest.TestCase):
    def test_agent_and_catalog_read_utf8_even_with_windows_legacy_default(self):
        value = 'Learn “模型” and café → safe deployment.'
        with self.assertRaises(UnicodeDecodeError):
            value.encode('utf-8').decode('cp1252')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'skill.md').write_bytes(value.encode('utf-8'))
            (root / 'models.json').write_bytes(json.dumps({'models': [{'description': value}]}, ensure_ascii=False).encode('utf-8'))
            (root / 'error_catalog.json').write_bytes(json.dumps({'errors': [{'description': value}]}, ensure_ascii=False).encode('utf-8'))
            with mock.patch.object(Path, 'open', windows_default_open), \
                 mock.patch.object(config, 'SKILL_DIR', root), mock.patch.object(agent, 'SKILL_DIR', root), \
                 mock.patch.object(agent, 'hardware_info', return_value={'os': 'Windows', 'os_version': 'test', 'arch': 'x64'}):
                self.assertEqual(config.load_allow_list()[0]['description'], value)
                self.assertEqual(config.load_error_catalog()[0]['description'], value)
                local = agent.LabAgent(config.Settings(router=False), llm=object(), toolbox=MinimalTools())
                self.assertIn(value, local.messages[0]['content'])

    def test_project_contract_checker_reads_real_portal_under_cp1252_default(self):
        spec = importlib.util.spec_from_file_location('release_contract_check_encoding', PROJECT / 'scripts/check_project.py')
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        with mock.patch.object(Path, 'open', windows_default_open), contextlib.redirect_stdout(io.StringIO()):
            check.main()

    def test_runtime_check_and_launchers_share_python_311_minimum(self):
        toolbox = tools.Toolbox(config.Settings())
        for version, expected in (((3, 10, 99), False), ((3, 11, 0), True), ((3, 13, 0), True)):
            with self.subTest(version=version), mock.patch.object(tools.sys, 'version_info', version):
                report = toolbox.check_install(up_to_step=1)
                self.assertIs(report['steps'][0]['ok'], expected)
        for name in ('Start Lab Helper.command', 'Start Lab Helper.bat'):
            source = (PROJECT / 'agent' / name).read_text(encoding='utf-8')
            self.assertIn('sys.version_info >= (3, 11)', source)
            self.assertNotIn('Python 3.9+', source)


if __name__ == '__main__':
    unittest.main()
