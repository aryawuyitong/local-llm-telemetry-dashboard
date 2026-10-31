"""Verify release artifacts and the real backend export contract without a model."""
from pathlib import Path
import ast
import json
import re
import sys
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'agent'))
from telemetry_agent import protocol
from telemetry_agent.config import Settings
from telemetry_agent.tools import Toolbox

class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' else None
        if value:
            if re.match(r'(?i)(?:https?:)?//', value):
                raise ValueError('Portal must not depend on external assets: ' + value)
            if not (ROOT / 'portal' / value).is_file():
                raise ValueError('Missing static asset: ' + value)


def main():
    count = 0
    for path in (ROOT / 'portal/examples').glob('*.json'):
        data = protocol.load_session(path)
        if data['data_kind'] != 'synthetic':
            raise ValueError('Published examples must be synthetic.')
        if len(data['runs']) != 9 or data['config']['repeats'] != 3:
            raise ValueError('Example baseline must contain nine attempted runs.')
        count += 1
    Assets().feed((ROOT / 'portal/index.html').read_text(encoding="utf-8"))
    for suite, expected in [('diagnosis', 20), ('redteam', 15), ('benign', 5)]:
        data = json.loads((ROOT / f'evaluation/cases/{suite}.json').read_text(encoding="utf-8"))
        cases = data['cases']
        if len(cases) != expected or len({c['id'] for c in cases}) != expected:
            raise ValueError('Invalid suite: ' + suite)
        if any(not isinstance(c['prompt'], str) or not c['prompt'].strip() for c in cases):
            raise ValueError('Empty prompt in ' + suite)
    schemas = Toolbox(Settings()).schemas()
    if {s['function']['name'] for s in schemas} != {'check_hardware','check_install','recommend_model','read_logs','run_benchmark'}:
        raise ValueError('Five-tool contract changed.')
    for base in ['agent/telemetry_agent', 'evaluation', 'scripts']:
        for path in (ROOT / base).rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for filename in ['README.md','agent/README.md','docs/architecture.md','docs/measurement-protocol.md','docs/validation.md','evaluation/README.md','portal/README.md']:
        path = ROOT / filename
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if re.match(r'\w+://', target) or target.startswith('#') or '<' in target:
                continue
            if not (path.parent / target.split('#')[0]).exists():
                raise ValueError(f'Broken document link: {filename}: {target}')
    print(f'Project contracts passed: {count} synthetic fixtures,40 evaluation cases,5 custom tools,static assets,Python syntax,documentation links.')

if __name__ == '__main__':
    main()
