from pathlib import Path
import ast, base64, gzip, re, subprocess
from html.parser import HTMLParser

source = Path(__file__).resolve().parents[1] / 'main.py'
text = source.read_text(encoding='utf-8')
module = ast.parse(text)
assert re.search(r"(?m)^VERSION = '[0-9]+\.[0-9]+\.[0-9]+'$", text)
assert 'def formiq_chat_keyboard():' in text
assert "InlineKeyboardButton('FormIQ'" in text
assert "InlineKeyboardButton('Разбудить'" in text
assert 'welcome_jpeg()' in text
home = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'home')
caption = next(node.value for node in home.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == 'caption' for target in node.targets))
approved = ('Добро пожаловать в FORMIQ!\\n\\n'
            'Твоя форма заслуживает умного подхода.\\n\\n'
            'Тренируйся, следи за питанием и наблюдай за своим прогрессом.\\n\\n'
            'Веди дневник самостоятельно или доверь Yandex AI создание '
            'персонального плана, анализ результатов и адаптацию тренировок.')
assert ast.literal_eval(caption) == approved, 'Only exact owner-approved four paragraphs'

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
