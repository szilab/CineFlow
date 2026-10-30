"""Small standard-library HTTP server for the CineFlow web GUI.

Authentication is optional and configured with ``CINEFLOW_AUTH`` (see
:mod:`cineflow.web.auth`). Without it the server only starts on a loopback
address, unless ``CINEFLOW_AUTH=none`` explicitly allows it, for example
behind an authenticating reverse proxy.
"""

import html
import json
import mimetypes
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cineflow.core.logger import log
from cineflow.web.api import Api
from cineflow.web.auth import (
    AuthError, AuthSettings, Authenticator, Request, cookie_jar, is_loopback,
)

STATIC_DIRECTORY = Path(__file__).resolve().parent / 'static'
MAX_BODY = 2 * 1024 * 1024
DEFAULT_HOST = '127.0.0.1'
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'same-origin',
    'Content-Security-Policy': (
        "default-src 'self'; img-src 'self' data: https://image.tmdb.org; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    ),
}
PUBLIC_API = ('/api/auth/status', '/api/auth/login', '/api/auth/logout')
MUTATING = ('POST', 'PUT', 'DELETE')


class Handler(BaseHTTPRequestHandler):
    """Serve the API, the sign-in endpoints and the static GUI files."""

    api: Api = None             # bound per server by _handler_class
    auth: Authenticator = None

    server_version = 'CineFlow'
    sys_version = ''

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        log(f"Web {self.address_string()} {format % args}", level='DEBUG')

    # ------------------------------------------------------------- responses

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None,
              cookies: tuple = ()) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for key, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(key, value)
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, status: int, payload, cookies: tuple = ()) -> None:
        self._send(status, json.dumps(payload).encode('utf-8'), 'application/json; charset=utf-8',
                   cookies=cookies)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {'error': {'message': message, 'issues': []}})

    def _redirect(self, location: str, cookies: tuple = ()) -> None:
        self._send(302, b'', 'text/plain', headers={'Location': location}, cookies=cookies)

    def _page(self, status: int, message: str) -> None:
        body = (
            '<!doctype html><meta charset="utf-8"><title>CineFlow sign-in</title>'
            f'<p>{html.escape(message)}</p><p><a href="./">Back to CineFlow</a></p>'
        ).encode()
        self._send(status, body, 'text/html; charset=utf-8')

    # --------------------------------------------------------------- request

    def _request(self) -> Request:
        return Request(
            headers={key.lower(): value for key, value in self.headers.items()},
            client_ip=self.client_address[0],
            cookies=cookie_jar(self.headers.get('Cookie', '')),
        )

    def _read_json(self):
        """Return (ok, body); answers the request itself when not ok."""
        # a JSON content type cannot be sent cross-site without a CORS preflight
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            self._error(415, 'Expected application/json.')
            return False, None
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            self._error(413, 'Request too large.')
            return False, None
        raw = self.rfile.read(length) if length else b''
        try:
            return True, (json.loads(raw) if raw else None)
        except (ValueError, UnicodeDecodeError):
            self._error(400, 'Invalid JSON.')
            return False, None

    def _same_origin(self) -> bool:
        """Reject state changes that a foreign page started (Origin header check)."""
        origin = self.headers.get('Origin')
        if not origin or origin == 'null':
            return origin is None
        hosts = {self.headers.get('Host', '')}
        if forwarded := self.headers.get('X-Forwarded-Host'):
            hosts.add(forwarded.split(',')[0].strip())
        if self.auth.settings.public_url:
            hosts.add(urlsplit(self.auth.settings.public_url).netloc)
        return urlsplit(origin).netloc in hosts

    # ------------------------------------------------------------ endpoints

    def _auth_api(self, method: str, path: str, request: Request) -> None:
        auth = self.auth
        if path == '/api/auth/status' and method == 'GET':
            self._json(200, auth.status(request))
            return
        if method != 'POST':
            self._error(405, 'Method not allowed.')
            return
        ok, body = self._read_json()
        if not ok:
            return
        if path == '/api/auth/logout':
            self._json(200, {'authenticated': False}, cookies=(auth.logout_cookie(),))
            return
        body = body if isinstance(body, dict) else {}
        try:
            user = auth.login_password(body.get('username', ''), body.get('password', ''), request.client_ip)
        except AuthError as exc:
            self._error(exc.status, str(exc))
            return
        log(f"GUI sign-in of '{user.name}' with password.", level='INFO')
        self._json(200, {'authenticated': True, 'user': user.to_dict()}, cookies=(auth.session_cookie(user),))

    def _oidc(self, path: str, query: dict, request: Request) -> None:
        auth = self.auth
        try:
            if path == '/auth/oidc/login':
                location, cookie = auth.oidc_start(query.get('next', ''))
                self._redirect(location, cookies=(cookie,))
                return
            user, next_path = auth.oidc_callback(query, request.cookies)
        except AuthError as exc:
            log(f"SSO sign-in failed: {exc}", level='WARNING')
            self._page(exc.status, f"Sign-in failed: {exc}")
            return
        self._redirect(f"{auth.settings.public_url}{next_path or '/'}",
                       cookies=(auth.session_cookie(user), auth.oidc_clear_cookie()))

    def _api(self, method: str, path: str, request: Request) -> None:
        try:
            user = self.auth.identify(request)
        except AuthError as exc:
            self._error(exc.status, str(exc))
            return
        if user is None:
            self._error(401, 'Sign in to use CineFlow.')
            return
        body = None
        if method in MUTATING:
            ok, body = self._read_json()
            if not ok:
                return
            read_only = path.endswith('/validate') or path == '/api/flows/test'
            log(f"GUI {method} {path} by '{user.name}'.", level='DEBUG' if read_only else 'INFO')
        status, payload = self.api.handle(method, path, body)
        self._json(status, payload)

    def _static(self, path: str) -> None:
        name = 'index.html' if path in ('/', '/index.html') else path.lstrip('/')
        if name.startswith('static/'):
            name = name[len('static/'):]
        target = (STATIC_DIRECTORY / name).resolve()
        if STATIC_DIRECTORY not in target.parents or not target.is_file():
            self._send(404, b'Not found', 'text/plain; charset=utf-8')
            return
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type.endswith('javascript'):
            content_type += '; charset=utf-8'
        self._send(200, target.read_bytes(), content_type)

    def _route(self, method: str) -> None:
        try:
            parts = urlsplit(self.path)
            path = parts.path
            request = self._request()
            if method in MUTATING and not self._same_origin():
                self._error(403, 'Cross-origin request refused.')
            elif path in PUBLIC_API:
                self._auth_api(method, path, request)
            elif path.startswith('/api/'):
                self._api(method, path, request)
            elif path in ('/auth/oidc/login', '/auth/oidc/callback') and method == 'GET':
                query = {key: values[0] for key, values in parse_qs(parts.query).items()}
                self._oidc(path, query, request)
            elif method in ('GET', 'HEAD'):
                self._static(path)
            else:
                self._send(HTTPStatus.METHOD_NOT_ALLOWED, b'Method not allowed', 'text/plain')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):  # pylint: disable=invalid-name
        """Answer GET."""
        self._route('GET')

    def do_HEAD(self):  # pylint: disable=invalid-name
        """Answer HEAD."""
        self._route('HEAD')

    def do_POST(self):  # pylint: disable=invalid-name
        """Answer POST."""
        self._route('POST')

    def do_PUT(self):  # pylint: disable=invalid-name
        """Answer PUT."""
        self._route('PUT')

    def do_DELETE(self):  # pylint: disable=invalid-name
        """Answer DELETE."""
        self._route('DELETE')


def _handler_class(api: Api, auth: Authenticator) -> type:
    """Return a request handler class bound to an API and an authenticator."""
    return type('BoundHandler', (Handler,), {'api': api, 'auth': auth})


class WebServer:
    """Application component running the GUI server in a background thread."""

    def __init__(self, port: int, host: str | None = None, flow_manager=None,
                 auth_settings: AuthSettings | None = None) -> None:
        self.host = host or os.environ.get('CINEFLOW_WEB_HOST', DEFAULT_HOST)
        settings = auth_settings or AuthSettings.from_env()
        if settings.errors:
            raise ValueError('Web GUI authentication settings: ' + ' '.join(settings.errors))
        if not settings.enabled and not settings.explicit_none and not is_loopback(self.host):
            raise ValueError(
                f"Refusing to serve the web GUI on {self.host} without authentication. "
                "Set CINEFLOW_AUTH (password, oidc, header), or CINEFLOW_AUTH=none when an "
                "authenticating reverse proxy protects it."
            )
        self.auth = Authenticator(settings)
        self.api = Api(flow_manager=flow_manager)
        self._server = ThreadingHTTPServer((self.host, port), _handler_class(self.api, self.auth))
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name='web')
        self._thread.start()
        methods = ', '.join(settings.methods) or 'none'
        log(f"Web GUI listening on http://{self.host}:{self.port}/ (authentication: {methods})", level='INFO')

    def stop(self) -> bool:
        """Stop serving requests."""
        if self._thread.is_alive():
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
        return not self._thread.is_alive()

    def close(self) -> bool:
        """Report whether the server stopped."""
        return self.stop()
