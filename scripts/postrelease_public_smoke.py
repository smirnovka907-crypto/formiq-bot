"""Read-only public post-release smoke check for the SINGLE existing FORMIQ bot.

No Telegram initData, cookies, user IDs, production secrets or write actions.
Only public GETs and an intentionally unauthorized POST that MUST be 401.
Run from an isolated GitHub Actions runner; do not run this on Render.
"""
import json
import sys
import urllib.error
import urllib.request


ORIGIN = 'https://formiq-bot.onrender.com'
USER_AGENT = 'FORMIQ-Postrelease-Public-Smoke/1.0'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected redirect from canonical production host')


def public_request(path, method='GET', payload=None):
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Use only literal local paths')
    url = ORIGIN + path
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,application/json,*/*'}
    body = None
    if method == 'POST':
        body = json.dumps(payload or {}).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=40) as response:
            return response.status, response.headers, response.read(2_000_000)
    except urllib.error.HTTPError as error:
        # Only status, headers and body are inspected; no raw payload printed.
        with error:
            return error.code, error.headers, error.read(8192)


def ensure(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def main():
    try:
        status, _, body = public_request('/')
        ensure(status == 200 and b'FORMIQ 38.3.3 online' in body,
               'Public health endpoint did not return expected released version')
        print('health: HTTP 200, FORMIQ 38.3.3')

        status, headers, public = public_request('/mini')
        ensure(status == 200, 'Mini App root did not return HTTP 200')
        ensure(b'v5-live.js' in public and b'FORMIQ' in public,
               'Mini App did not serve Aluminium v5')
        ensure(b'/mini/ux-382' not in public and b'/mini/ux-381' not in public,
               'Legacy JS/CSS unexpectedly referenced by launcher')
        ensure('no-store' in headers.get('Cache-Control', ''),
               'Mini App entry missing no-store cache policy')
        print('mini: HTTP 200, V5 launcher, no old 38.2 asset, no-store')

        for endpoint in ('/mini/v5', '/mini/legacy'):
            code, _, content = public_request(endpoint)
            ensure(code == 200 and content == public,
                   endpoint + ' does not serve the same current V5 launcher')
            print(endpoint + ': HTTP 200, identical current V5 launcher')

        status, _, js = public_request('/mini/v5-live.js')
        ensure(status == 200 and b'function onboardForm()' in js
               and b"await send('onboarding'" in js,
               'Native V5 onboarding not present in public JS')
        ensure(b'window.location.assign(\'/mini/legacy\'' not in js,
               'V5 client unexpectedly redirects to legacy onboarding')
        print('V5 JavaScript: HTTP 200, native onboarding, no legacy redirect')

        # A request with NO initData MUST NOT be allowed to read or mutate.
        code, _, data = public_request('/mini/api', 'POST', {'action': 'state'})
        ensure(code == 401, 'Unauthenticated API failed closed status check')
        try:
            unauthorized = json.loads(data)
        except (ValueError, TypeError):
            raise RuntimeError('Unauthenticated API returned invalid JSON') from None
        ensure(unauthorized.get('ok') is False, 'Unauthenticated API not rejected')
        print('API without Telegram initData: HTTP 401, denied')

        print('PASS: public production HTTP smoke, read-only / no Telegram identity')
        return 0
    except Exception:
        # Never print HTTP responses, request headers, URLs with private tokens.
        print('FAIL: public production HTTP smoke; inspect expected statuses safely',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
