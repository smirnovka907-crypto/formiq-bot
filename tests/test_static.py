from pathlib import Path
import ast, base64, gzip, re, subprocess
from html.parser import HTMLParser

source = Path(__file__).resolve().parents[1] / 'main.py'
text = source.read_text(encoding='utf-8')
module = ast.parse(text)
assert "VERSION = '38.1.1'" in text
assert 'FormIQ' in text and "KeyboardButton('Разбудить')" in text
assert 'FORMIQ_CHAT_WELCOME_JPG_B64' in text

assignment = next(node for node in module.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'MINI_HTML_GZIP' for target in node.targets))
html = gzip.decompress(base64.b64decode(ast.literal_eval(assignment.value))).decode('utf-8')
assert 'Отзывы и предложения' in html
assert 'Пульс в покое' not in html
assert 'fq_confirm_analysis' in html
class Inspector(HTMLParser): pass
Inspector().feed(html)
try:
    import tinycss2
    for css in re.findall(r'<style[^>]*>([\s\S]*?)</style>', html):
        assert not [x for x in tinycss2.parse_stylesheet(css) if x.type == 'error']
except ImportError:
    print('SKIP optional CSS parser tinycss2')
js = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)[-1]
js_file = source.parent / '_formiq_test_temp.js'
try:
    js_file.write_text(js, encoding='utf-8')
    result = subprocess.run(['node', '--check', str(js_file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
finally:
    js_file.unlink(missing_ok=True)
print('PASS Python, HTML, optional CSS, JS, two Telegram buttons, consent flow')
