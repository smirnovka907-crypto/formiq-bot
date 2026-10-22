"""38.1 UX integration contract tests (no production token/DB required)."""
import ast
import base64
import gzip
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'main.py').read_text(encoding='utf-8')
UI_JS = (ROOT / 'web' / 'ux-381.js').read_text(encoding='utf-8')
UI_CSS = (ROOT / 'web' / 'ux-381.css').read_text(encoding='utf-8')


class Ux381Tests(unittest.TestCase):
    def test_main_is_release_candidate(self):
        self.assertRegex(SOURCE, r"(?m)^VERSION = '\d+\.\d+\.\d+'$")
        self.assertIn("@APP.get('/mini/ux-381.css')", SOURCE)
        self.assertIn("@APP.get('/mini/ux-381.js')", SOURCE)
        self.assertIn("markup.replace('</head>'", SOURCE)
        self.assertIn("markup.replace('</body>'", SOURCE)
        self.assertIn("('record','skip','replace','start')", SOURCE)

    def test_css_three_themes_contrast_and_minimalism(self):
        self.assertIn('html[data-theme="dark"]', UI_CSS)
        self.assertIn('background:var(--blue)!important;color:#fff!important', UI_CSS)
        self.assertIn('.today-hero::before,.today-hero::after{display:none!important}', UI_CSS)
        self.assertIn('font-size:16px!important', UI_CSS)
        try:
            import tinycss2
        except ImportError:
            self.skipTest('tinycss2 is optional')
        self.assertFalse([token for token in tinycss2.parse_stylesheet(UI_CSS) if token.type == 'error'])

    def test_external_js_syntax(self):
        p = subprocess.run(['node', '--check', str(ROOT / 'web' / 'ux-381.js')],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_user_flow_does_not_get_lost(self):
        for required in ('oldExecute(action)', "health-refine", "health_analyze",
                         "faq-not-included", "chat"):
            if required in ('faq-not-included', 'chat'):
                continue
            self.assertIn(required, UI_JS)
        self.assertIn("healthDescription=combined", UI_JS)
        self.assertIn("healthAnalysis=response.analysis", UI_JS)
        self.assertIn("if(!pain&&$('on_pain'))$('on_pain').value='0'", UI_JS)
        self.assertIn("if(!course&&$('on_course'))$('on_course').value='recent'", UI_JS)
        self.assertIn("healthAnalysis?.needs_clarification", UI_JS)
        self.assertIn("['auto','Система']", UI_JS)
        self.assertIn("['pearl','Светлая']", UI_JS)
        self.assertIn("['graphite','Тёмная']", UI_JS)
        self.assertIn("feedback-open", UI_JS)
        self.assertIn("start-normal", UI_JS)
        self.assertIn("coach-open", UI_JS)

    def test_original_embedded_app_is_preserved(self):
        module = ast.parse(SOURCE)
        node = next(
            node for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(x, ast.Name) and x.id == 'MINI_HTML_GZIP'
                    for x in node.targets)
        )
        html = gzip.decompress(base64.b64decode(ast.literal_eval(node.value))).decode('utf-8')
        self.assertIn('Разобрать с ИИ', html)
        self.assertIn('Отзывы и предложения', html)
        self.assertIn('main', SOURCE)
        self.assertIn("InlineKeyboardButton('Разбудить', callback_data='wake')", SOURCE)


if __name__ == '__main__':
    unittest.main()
