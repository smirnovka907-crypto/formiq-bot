"""Tests for opt-in Aluminium v5 entry; no PostgreSQL or Telegram access."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UX = (ROOT / 'web' / 'ux-381.js').read_text(encoding='utf-8')
V5 = (ROOT / 'web' / 'v5-live.js').read_text(encoding='utf-8')


class PrivatePreviewEntry(unittest.TestCase):
    @staticmethod
    def flag_expression():
        tree = ast.parse(MAIN)
        fn = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == 'mini_state')
        assignment = next(node for node in fn.body
                          if isinstance(node, ast.Assign) and
                          any(isinstance(t, ast.Name) and t.id == 'result' for t in node.targets))
        key_to_value = {k.value: v for k, v in zip(assignment.value.keys, assignment.value.values)
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        return compile(ast.Expression(key_to_value['v5_preview_enabled']), '<flag>', 'eval')

    def test_admin_enabled_only_for_configured_owner(self):
        expr = self.flag_expression()
        for admin, user, allowed in [(0, 1, False), (0, 0, False),
                                     (42, 42, True), (42, 43, False),
                                     (112233, 998877, False)]:
            with self.subTest(admin=admin, user=user):
                result = eval(expr, {'__builtins__': {'int': int, 'bool': bool}},
                              {'ADMIN_ID': admin, 'chat': user})
                self.assertIs(result, allowed)

    def test_opt_in_link_requires_owner_flag(self):
        self.assertIn('if(state?.v5_preview_enabled&&', UX)
        self.assertIn("link.href='/mini/v5'", UX)
        self.assertIn("link.id='fq-v5-staging-entry'", UX)
        self.assertIn("document.getElementById('fq-v5-staging-entry')", UX)
        self.assertNotIn('window.open(', UX)
        self.assertNotIn('Telegram.WebApp.openLink(', UX)

    def test_old_mini_default_and_sensitive_data_are_untouched(self):
        self.assertIn("web_app=types.WebAppInfo(url=BASE_URL + '/mini')", MAIN)
        self.assertIn("@APP.get('/mini/v5')", MAIN)
        self.assertIn("X-Formiq-Init", V5)
        self.assertIn("if(!token)", V5)
        self.assertNotIn('localStorage', V5)


if __name__ == '__main__':
    unittest.main()
