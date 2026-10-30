"""Web GUI authentication: password, OIDC single sign-on and proxy headers."""

import base64
import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from cineflow.web import auth as auth_module
from cineflow.web.auth import (
    AuthError, AuthSettings, Authenticator, Request, User, cookie_jar, hash_password, is_loopback,
    load_secret_key, safe_next, verify_password,
)
from cineflow.web.server import WebServer

KEY = b'k' * 32
ISSUER = 'https://sso.example.org'


def settings(**env) -> AuthSettings:
    return AuthSettings.from_env({f'CINEFLOW_{key}': value for key, value in env.items()})


def request(headers=None, ip='127.0.0.1', cookies=None) -> Request:
    return Request({k.lower(): v for k, v in (headers or {}).items()}, ip, cookies or {})


def cookie_value(set_cookie: str) -> str:
    return set_cookie.split(';')[0].split('=', 1)[1]


# ------------------------------------------------------------------ settings

def test_settings_defaults_and_errors() -> None:
    assert settings().enabled is False and settings().errors == []
    assert settings(AUTH='none').explicit_none is True
    errors = settings(AUTH='none,password,magic', AUTH_SESSION_HOURS='x',
                      AUTH_TRUSTED_PROXIES='not-an-ip', PUBLIC_URL='ftp://x').errors
    assert len(errors) == 6
    assert settings(AUTH='oidc', OIDC_TOKEN_AUTH='jwt').errors[-1].startswith('CINEFLOW_OIDC_TOKEN_AUTH')
    assert settings(AUTH_SESSION_HOURS='0').errors


def test_cookie_settings_follow_public_url() -> None:
    https = settings(PUBLIC_URL='https://web.example.org/cineflow/')
    assert https.secure_cookie is True and https.cookie_path == '/cineflow/'
    assert https.oidc_redirect_url == 'https://web.example.org/cineflow/auth/oidc/callback'
    assert settings().cookie_path == '/' and settings().secure_cookie is False
    assert settings(PUBLIC_URL='http://x', AUTH_SECURE_COOKIE='yes').secure_cookie is True


def test_helpers() -> None:
    assert is_loopback('127.0.0.1') and is_loopback('::1') and is_loopback('localhost')
    assert not is_loopback('0.0.0.0') and not is_loopback('') and not is_loopback('example.org')
    assert cookie_jar('a=1; b=two=2; broken') == {'a': '1', 'b': 'two=2'}
    assert safe_next('/flows?x=1') == '/flows?x=1'
    for bad in ('//evil.org', 'https://evil.org', '/\\evil', 'javascript:x', ''):
        assert safe_next(bad) == ''
    assert User('a', 'password', ('g',)).to_dict() == {'name': 'a', 'method': 'password', 'groups': ['g']}


def test_secret_key_is_generated_once_and_private(isolated_config_directory, monkeypatch) -> None:
    monkeypatch.delenv('CINEFLOW_SECRET_KEY', raising=False)
    first = load_secret_key()
    path = isolated_config_directory / '.cineflow' / 'secret'
    assert load_secret_key() == first and len(first) == 32
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    monkeypatch.setenv('CINEFLOW_SECRET_KEY', 'from-env')
    assert load_secret_key() == b'from-env'


# ------------------------------------------------------------------ password

def test_password_hashing() -> None:
    encoded = hash_password('correct horse', iterations=1000)
    assert verify_password('correct horse', encoded)
    assert not verify_password('wrong', encoded)
    assert not verify_password('x', 'md5$1$a$b') and not verify_password('x', 'garbage')


@pytest.mark.parametrize('env', [
    {'AUTH_PASSWORD': 'secret-pass'},
    {'AUTH_PASSWORD_HASH': hash_password('secret-pass', iterations=1000)},
])
def test_password_login_and_session(env) -> None:
    auth = Authenticator(settings(AUTH='password', AUTH_USERNAME='me', **env), KEY)
    with pytest.raises(AuthError):
        auth.login_password('me', 'nope', '10.0.0.1')
    with pytest.raises(AuthError):
        auth.login_password('other', 'secret-pass', '10.0.0.1')
    user = auth.login_password('me', 'secret-pass', '10.0.0.1')
    cookie = auth.session_cookie(user)
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Path=/' in cookie
    assert auth.identify(request(cookies={'cineflow_session': cookie_value(cookie)})).name == 'me'
    assert auth.identify(request()) is None
    assert auth.status(request())['authenticated'] is False
    assert cookie_value(auth.logout_cookie()) == ''


def test_password_login_is_rate_limited(monkeypatch) -> None:
    auth = Authenticator(settings(AUTH='password', AUTH_PASSWORD='right-pass'), KEY)
    for _ in range(auth_module.LOGIN_ATTEMPTS):
        with pytest.raises(AuthError):
            auth.login_password('admin', 'wrong', '10.0.0.9')
    with pytest.raises(AuthError) as blocked:
        auth.login_password('admin', 'right-pass', '10.0.0.9')
    assert blocked.value.status == 429
    assert auth.login_password('admin', 'right-pass', '10.0.0.10').name == 'admin'
    later = time.time() + auth_module.LOGIN_WINDOW + 1
    monkeypatch.setattr(auth_module.time, 'time', lambda: later)
    assert auth.login_password('admin', 'right-pass', '10.0.0.9').name == 'admin'


def test_password_login_disabled() -> None:
    with pytest.raises(AuthError):
        Authenticator(settings(AUTH='header'), KEY).login_password('a', 'b', '1.1.1.1')


def test_tampered_expired_and_foreign_sessions_are_rejected(monkeypatch) -> None:
    auth = Authenticator(settings(AUTH='password', AUTH_PASSWORD='p' * 10), KEY)
    token = cookie_value(auth.session_cookie(User('admin', 'password')))
    body, signature = token.split('.')
    assert auth.unsign(f"{body}.{signature[:-2]}xx") is None
    assert auth.unsign('garbage') is None
    assert Authenticator(auth.settings, b'other' * 8).unsign(token) is None
    oidc_token = auth.sign({'u': 'x', 'm': 'oidc', 'exp': time.time() + 60})
    assert auth.identify(request(cookies={'cineflow_session': oidc_token})) is None  # method not enabled
    monkeypatch.setattr(auth_module.time, 'time', lambda: 10 ** 12)
    assert auth.unsign(token) is None


def test_allowed_users_and_groups() -> None:
    auth = Authenticator(settings(AUTH='password', AUTH_PASSWORD='p' * 10, AUTH_ALLOWED_USERS='alice',
                                  AUTH_ALLOWED_GROUPS='media'), KEY)
    assert auth._authorize(User('alice', 'password')).name == 'alice'
    assert auth._authorize(User('bob', 'password', ('media',))).name == 'bob'
    with pytest.raises(AuthError) as denied:
        auth._authorize(User('bob', 'password'))
    assert denied.value.status == 403
    with pytest.raises(AuthError):
        auth.login_password('admin', 'p' * 10, '1.2.3.4')
    token = auth.sign({'u': 'mallory', 'm': 'password', 'exp': time.time() + 60})
    assert auth.identify(request(cookies={'cineflow_session': token})) is None


# -------------------------------------------------------------------- header

def test_proxy_header_is_trusted_only_from_trusted_proxies() -> None:
    auth = Authenticator(settings(AUTH='header', AUTH_TRUSTED_PROXIES='172.16.0.0/12',
                                  AUTH_ALLOWED_GROUPS='admins'), KEY)
    headers = {'Remote-User': 'alice', 'Remote-Groups': 'users, admins'}

    user = auth.identify(request(headers, ip='172.18.0.5'))
    assert user.name == 'alice' and user.groups == ('users', 'admins') and user.method == 'header'
    assert auth.identify(request(headers, ip='10.0.0.20')) is None
    assert auth.identify(request({'Remote-User': 'bob'}, ip='172.18.0.5')) is None   # not in group
    assert auth.identify(request({}, ip='172.18.0.5')) is None
    assert auth.identify(request(headers, ip='not-an-ip')) is None


def test_no_authentication_means_anonymous() -> None:
    assert Authenticator(settings(), b'').identify(request()).name == 'anonymous'


# ---------------------------------------------------------------------- OIDC

def jwt(payload: dict) -> str:
    part = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b'=').decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(payload)}.signature"


class FakeProvider:
    """Mocked OpenID provider endpoints."""

    def __init__(self, monkeypatch) -> None:
        self.metadata = {
            'issuer': ISSUER,
            'authorization_endpoint': f'{ISSUER}/authorize',
            'token_endpoint': f'{ISSUER}/token',
            'userinfo_endpoint': f'{ISSUER}/userinfo',
        }
        self.claims = {}
        self.userinfo = {}
        self.token_calls = []
        self.fail = None
        monkeypatch.setattr(auth_module.requests, 'get', self.get)
        monkeypatch.setattr(auth_module.requests, 'post', self.post)

    @staticmethod
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None)

    def get(self, url, timeout, headers=None):
        if self.fail == 'discovery':
            raise requests.ConnectionError('down')
        if url.endswith('/.well-known/openid-configuration'):
            return self.response(self.metadata)
        assert headers['Authorization'] == 'Bearer access'
        return self.response(self.userinfo)

    def post(self, url, data, auth, timeout, headers):
        self.token_calls.append({'url': url, 'data': data, 'auth': auth})
        if self.fail == 'token':
            raise requests.HTTPError('400')
        return self.response({'id_token': jwt(self.claims), 'access_token': 'access'})


def oidc_auth(**env) -> Authenticator:
    return Authenticator(settings(AUTH='oidc', OIDC_ISSUER=ISSUER + '/', OIDC_CLIENT_ID='cineflow',
                                  OIDC_CLIENT_SECRET='shh', PUBLIC_URL='https://web.example.org/cineflow',
                                  **env), KEY)


def start_login(auth: Authenticator, provider: FakeProvider, next_path='/x') -> tuple[dict, dict]:
    location, cookie = auth.oidc_start(next_path)
    query = {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}
    assert location.startswith(f'{ISSUER}/authorize?')
    state = auth.unsign(cookie_value(cookie))
    provider.claims = {'iss': ISSUER, 'aud': 'cineflow', 'exp': time.time() + 300, 'nonce': state['n'],
                       'sub': 'u1', 'preferred_username': 'alice', 'groups': ['media']}
    return query, {'cineflow_oidc': cookie_value(cookie)}


def test_oidc_login_flow(monkeypatch) -> None:
    provider = FakeProvider(monkeypatch)
    auth = oidc_auth()
    query, cookies = start_login(auth, provider)

    assert query['client_id'] == 'cineflow' and query['code_challenge_method'] == 'S256'
    assert query['redirect_uri'] == 'https://web.example.org/cineflow/auth/oidc/callback'
    assert query['scope'] == 'openid profile email groups'
    user, next_path = auth.oidc_callback({'code': 'abc', 'state': query['state']}, cookies)

    assert (user.name, user.groups, next_path) == ('alice', ('media',), '/x')
    call = provider.token_calls[0]
    assert call['auth'] == ('cineflow', 'shh') and call['data']['code'] == 'abc'
    assert call['data']['code_verifier'] and 'client_secret' not in call['data']
    session = cookie_value(auth.session_cookie(user))
    assert auth.status(request(cookies={'cineflow_session': session}))['user']['name'] == 'alice'
    assert 'Secure' in auth.session_cookie(user) and 'Path=/cineflow/' in auth.session_cookie(user)


def test_oidc_post_auth_and_userinfo_fallback(monkeypatch) -> None:
    provider = FakeProvider(monkeypatch)
    auth = oidc_auth(OIDC_TOKEN_AUTH='post', OIDC_USER_CLAIM='email')
    query, cookies = start_login(auth, provider)
    del provider.claims['groups']
    provider.userinfo = {'sub': 'u1', 'email': 'alice@example.org', 'groups': ['a', 'b']}

    user, _ = auth.oidc_callback({'code': 'abc', 'state': query['state']}, cookies)

    assert user.name == 'alice@example.org' and user.groups == ('a', 'b')
    assert provider.token_calls[0]['data']['client_secret'] == 'shh' and provider.token_calls[0]['auth'] is None


@pytest.mark.parametrize(('change', 'message'), [
    (lambda claims: claims.update(iss='https://evil.org'), 'issuer'),
    (lambda claims: claims.update(aud=['other']), 'audience'),
    (lambda claims: claims.update(exp=1), 'expired'),
    (lambda claims: claims.update(nonce='replayed'), 'nonce'),
    (lambda claims: [claims.pop(key) for key in ('preferred_username', 'sub')], 'no user name'),
])
def test_oidc_rejects_bad_id_tokens(monkeypatch, change, message) -> None:
    provider = FakeProvider(monkeypatch)
    provider.metadata.pop('userinfo_endpoint')
    auth = oidc_auth()
    query, cookies = start_login(auth, provider)
    change(provider.claims)

    with pytest.raises(AuthError, match=message):
        auth.oidc_callback({'code': 'abc', 'state': query['state']}, cookies)


def test_oidc_rejects_bad_callbacks(monkeypatch) -> None:
    provider = FakeProvider(monkeypatch)
    auth = oidc_auth(AUTH_ALLOWED_GROUPS='admins')
    query, cookies = start_login(auth, provider)

    with pytest.raises(AuthError, match='expired'):
        auth.oidc_callback({'code': 'abc', 'state': query['state']}, {})
    with pytest.raises(AuthError, match='refused'):
        auth.oidc_callback({'error': 'access_denied'}, cookies)
    with pytest.raises(AuthError, match='Invalid'):
        auth.oidc_callback({'code': 'abc', 'state': 'forged'}, cookies)
    with pytest.raises(AuthError) as denied:
        auth.oidc_callback({'code': 'abc', 'state': query['state']}, cookies)
    assert denied.value.status == 403
    provider.fail = 'token'
    with pytest.raises(AuthError, match='token request'):
        auth.oidc_callback({'code': 'abc', 'state': query['state']}, cookies)
    with pytest.raises(AuthError):
        Authenticator(settings(AUTH='password', AUTH_PASSWORD='x' * 9), KEY).oidc_callback({}, {})


def test_oidc_provider_problems(monkeypatch) -> None:
    provider = FakeProvider(monkeypatch)
    provider.metadata['issuer'] = 'https://other.example.org'
    with pytest.raises(AuthError, match='issuer'):
        oidc_auth().oidc_start()
    provider.metadata['issuer'] = ISSUER
    del provider.metadata['token_endpoint']
    with pytest.raises(AuthError, match='token_endpoint'):
        oidc_auth().oidc_start()
    provider.fail = 'discovery'
    with pytest.raises(AuthError, match='unreachable'):
        oidc_auth().oidc_start()
    with pytest.raises(AuthError):
        Authenticator(settings(), b'').oidc_start()


def test_oidc_settings_require_issuer_client_and_public_url() -> None:
    assert len(settings(AUTH='oidc').errors) == 3


# -------------------------------------------------------------------- server

def http(port, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, method=method)
    if body is not None or method != 'GET':
        req.add_header('Content-Type', 'application/json')
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_server_refuses_public_address_without_auth(isolated_config_directory) -> None:
    with pytest.raises(ValueError, match='without authentication'):
        WebServer(port=0, host='0.0.0.0', auth_settings=settings())
    with pytest.raises(ValueError, match='authentication settings'):
        WebServer(port=0, host='127.0.0.1', auth_settings=settings(AUTH='password'))
    server = WebServer(port=0, host='0.0.0.0', auth_settings=settings(AUTH='none'))
    server.stop()


def test_server_password_session_flow(isolated_config_directory, monkeypatch) -> None:
    monkeypatch.setenv('CINEFLOW_SECRET_KEY', 'test-key')
    server = WebServer(port=0, host='127.0.0.1',
                       auth_settings=settings(AUTH='password', AUTH_PASSWORD='letmein-now'))
    try:
        port = server.port
        assert http(port, 'GET', '/')[0] == 200                      # the sign-in page is public
        status, _, body = http(port, 'GET', '/api/auth/status')
        assert status == 200 and json.loads(body)['methods'] == ['password']
        assert http(port, 'GET', '/api/flows')[0] == 401
        assert http(port, 'POST', '/api/auth/login', {'username': 'admin', 'password': 'bad'})[0] == 401
        assert http(port, 'GET', '/api/auth/login')[0] == 405
        status, headers, _ = http(port, 'POST', '/api/auth/login', {'username': 'admin', 'password': 'letmein-now'})
        assert status == 200
        session = headers['Set-Cookie'].split(';')[0]
        assert http(port, 'GET', '/api/flows', headers={'Cookie': session})[0] == 200
        assert http(port, 'POST', '/api/flows/validate', {'flow': {}},
                    headers={'Cookie': session, 'Origin': 'https://evil.example'})[0] == 403
        assert http(port, 'POST', '/api/flows/validate', {'flow': {}},
                    headers={'Cookie': session, 'Origin': f'http://127.0.0.1:{port}'})[0] == 200
        status, headers, _ = http(port, 'POST', '/api/auth/logout', {})
        assert status == 200 and 'Max-Age=0' in headers['Set-Cookie']
        assert http(port, 'GET', '/auth/oidc/login')[0] == 400                  # SSO not enabled
    finally:
        server.stop()


def test_server_oidc_endpoints(isolated_config_directory, monkeypatch) -> None:
    provider = FakeProvider(monkeypatch)
    server = WebServer(port=0, host='127.0.0.1', auth_settings=settings(
        AUTH='oidc', OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID='cineflow', PUBLIC_URL='http://127.0.0.1:1/app'))
    try:
        status, headers, _ = http(server.port, 'GET', '/auth/oidc/login?next=/x')
        assert status == 302 and headers['Location'].startswith(f'{ISSUER}/authorize')
        state_cookie = headers['Set-Cookie'].split(';')[0]
        query = parse_qs(urlsplit(headers['Location']).query)
        state = server.auth.unsign(state_cookie.split('=', 1)[1])
        provider.claims = {'iss': ISSUER, 'aud': 'cineflow', 'exp': time.time() + 60, 'nonce': state['n'],
                           'sub': 's', 'preferred_username': 'alice', 'groups': []}
        status, headers, _ = http(server.port, 'GET',
                                  f"/auth/oidc/callback?code=c&state={query['state'][0]}",
                                  headers={'Cookie': state_cookie})
        assert status == 302 and headers['Location'] == 'http://127.0.0.1:1/app/x'
        assert any(value.startswith('cineflow_session=') for value in headers.get_all('Set-Cookie'))
        status, _, body = http(server.port, 'GET', '/auth/oidc/callback?code=c&state=forged',
                               headers={'Cookie': state_cookie})
        assert status == 401 and b'Sign-in failed' in body
    finally:
        server.stop()


def test_server_header_auth(isolated_config_directory) -> None:
    server = WebServer(port=0, host='127.0.0.1', auth_settings=settings(AUTH='header'))
    try:
        assert http(server.port, 'GET', '/api/flows')[0] == 401
        assert http(server.port, 'GET', '/api/flows', headers={'Remote-User': 'alice'})[0] == 200
    finally:
        server.stop()


def test_hash_password_command(monkeypatch, capsys) -> None:
    from cineflow.main import main

    monkeypatch.setattr('sys.stdin', SimpleNamespace(isatty=lambda: False, readline=lambda: 'long-password\n'))
    with pytest.raises(SystemExit) as code:
        main(['hash-password'])
    assert code.value.code == 0
    assert verify_password('long-password', capsys.readouterr().out.strip())

    monkeypatch.setattr('sys.stdin', SimpleNamespace(isatty=lambda: False, readline=lambda: 'short\n'))
    with pytest.raises(SystemExit) as code:
        main(['hash-password'])
    assert code.value.code == 1

    answers = iter(['first-password', 'other-password'])
    monkeypatch.setattr('sys.stdin', SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr('getpass.getpass', lambda prompt='': next(answers))
    with pytest.raises(SystemExit) as code:
        main(['hash-password'])
    assert code.value.code == 1
