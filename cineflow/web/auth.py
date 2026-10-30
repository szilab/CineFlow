"""Optional authentication of the web GUI.

Methods, enabled with ``CINEFLOW_AUTH`` (comma-separated):

- ``password`` — one local account, signed session cookie;
- ``oidc`` — single sign-on with an OpenID Connect provider (authorization
  code flow with PKCE), e.g. VoidAuth, Authelia, Authentik, Keycloak;
- ``header`` — trust a user header set by an authenticating reverse proxy
  (forward auth), only for requests from ``CINEFLOW_AUTH_TRUSTED_PROXIES``;
- ``none`` — no authentication (explicit opt-in on non-loopback addresses).

Everything is configured through environment variables so the GUI itself can
never lock its users out or weaken its own protection.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests

from cineflow.core.logger import log
from cineflow.runtime import config_directory

METHODS = ('password', 'oidc', 'header')
SESSION_COOKIE = 'cineflow_session'
OIDC_COOKIE = 'cineflow_oidc'
PBKDF2_ITERATIONS = 600_000
LOGIN_ATTEMPTS = 5          # failed password logins per client ...
LOGIN_WINDOW = 300          # ... within this many seconds
OIDC_STATE_SECONDS = 600


class AuthError(Exception):
    """Authentication failed; ``status`` is the HTTP status to answer."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class User:
    """An authenticated GUI user."""

    name: str
    method: str
    groups: tuple = ()

    def to_dict(self) -> dict:
        """Return the JSON-serializable user."""
        return {'name': self.name, 'method': self.method, 'groups': list(self.groups)}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _split(value: str | None) -> tuple:
    return tuple(item.strip() for item in (value or '').split(',') if item.strip())


def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a ``pbkdf2_sha256$iterations$salt$hash`` password hash."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a hash made by :func:`hash_password`."""
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), _unb64(salt), int(iterations))
        return hmac.compare_digest(_b64(digest), expected)
    except (ValueError, TypeError):
        return False


def load_secret_key() -> bytes:
    """Return the session signing key from the environment or a private file."""
    if configured := os.environ.get('CINEFLOW_SECRET_KEY'):
        return configured.encode()
    path = config_directory() / '.cineflow' / 'secret'
    try:
        return bytes.fromhex(path.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(key.hex())
    return key


@dataclass
class AuthSettings:  # pylint: disable=too-many-instance-attributes
    """Authentication settings read from the environment."""

    methods: tuple = ()
    explicit_none: bool = False
    session_hours: float = 12
    username: str = 'admin'
    password: str = ''
    password_hash: str = ''
    header_user: str = 'Remote-User'
    header_groups: str = 'Remote-Groups'
    trusted_proxies: tuple = ()
    allowed_users: tuple = ()
    allowed_groups: tuple = ()
    public_url: str = ''
    oidc_issuer: str = ''
    oidc_client_id: str = ''
    oidc_client_secret: str = ''
    oidc_scopes: str = 'openid profile email groups'
    oidc_user_claim: str = 'preferred_username'
    oidc_groups_claim: str = 'groups'
    oidc_token_auth: str = 'basic'
    oidc_label: str = 'Single sign-on'
    secure_cookie: bool = False
    errors: list = field(default_factory=list)

    @classmethod
    def from_env(cls, env: dict | None = None) -> 'AuthSettings':  # noqa: C901
        """Read and check the settings."""
        env = os.environ if env is None else env
        get = lambda key, default='': env.get(f'CINEFLOW_{key}', default).strip()  # noqa: E731
        raw = [item.lower() for item in _split(get('AUTH'))]
        settings = cls(
            methods=tuple(item for item in raw if item != 'none'),
            explicit_none=raw == ['none'],
            username=get('AUTH_USERNAME', 'admin') or 'admin',
            password=get('AUTH_PASSWORD'),
            password_hash=get('AUTH_PASSWORD_HASH'),
            header_user=get('AUTH_HEADER', 'Remote-User') or 'Remote-User',
            header_groups=get('AUTH_GROUPS_HEADER', 'Remote-Groups') or 'Remote-Groups',
            allowed_users=_split(get('AUTH_ALLOWED_USERS')),
            allowed_groups=_split(get('AUTH_ALLOWED_GROUPS')),
            public_url=get('PUBLIC_URL').rstrip('/'),
            oidc_issuer=get('OIDC_ISSUER').rstrip('/'),
            oidc_client_id=get('OIDC_CLIENT_ID'),
            oidc_client_secret=get('OIDC_CLIENT_SECRET'),
            oidc_scopes=get('OIDC_SCOPES', 'openid profile email groups') or 'openid profile email groups',
            oidc_user_claim=get('OIDC_USER_CLAIM', 'preferred_username') or 'preferred_username',
            oidc_groups_claim=get('OIDC_GROUPS_CLAIM', 'groups') or 'groups',
            oidc_token_auth=(get('OIDC_TOKEN_AUTH', 'basic') or 'basic').lower(),
            oidc_label=get('OIDC_LABEL', 'Single sign-on') or 'Single sign-on',
        )
        errors = settings.errors
        if 'none' in raw and len(raw) > 1:
            errors.append("CINEFLOW_AUTH=none cannot be combined with other methods.")
        for method in settings.methods:
            if method not in METHODS:
                errors.append(f"Unknown authentication method '{method}'.")
        try:
            settings.session_hours = float(get('AUTH_SESSION_HOURS', '12') or 12)
            if settings.session_hours <= 0:
                raise ValueError
        except ValueError:
            errors.append("CINEFLOW_AUTH_SESSION_HOURS must be a positive number.")
        try:
            settings.trusted_proxies = tuple(
                ipaddress.ip_network(item, strict=False)
                for item in _split(get('AUTH_TRUSTED_PROXIES', '127.0.0.1,::1'))
            )
        except ValueError as exc:
            errors.append(f"Invalid CINEFLOW_AUTH_TRUSTED_PROXIES: {exc}")
        if 'password' in settings.methods and not (settings.password or settings.password_hash):
            errors.append("Password login needs CINEFLOW_AUTH_PASSWORD or CINEFLOW_AUTH_PASSWORD_HASH.")
        if 'oidc' in settings.methods:
            for key in ('oidc_issuer', 'oidc_client_id', 'public_url'):
                if not getattr(settings, key):
                    errors.append(f"OIDC login needs CINEFLOW_{key.upper()}.")
            if settings.oidc_token_auth not in ('basic', 'post'):
                errors.append("CINEFLOW_OIDC_TOKEN_AUTH must be 'basic' or 'post'.")
        if settings.public_url and urlsplit(settings.public_url).scheme not in ('http', 'https'):
            errors.append("CINEFLOW_PUBLIC_URL must be an http(s) URL.")
        secure = get('AUTH_SECURE_COOKIE').lower()
        settings.secure_cookie = secure in ('1', 'true', 'yes', 'on') or (
            not secure and settings.public_url.startswith('https://'))
        return settings

    @property
    def enabled(self) -> bool:
        """Return whether any authentication method is active."""
        return bool(self.methods)

    @property
    def cookie_path(self) -> str:
        """Return the cookie path: the public URL path, or the root."""
        return (urlsplit(self.public_url).path.rstrip('/') or '') + '/' if self.public_url else '/'

    @property
    def oidc_redirect_url(self) -> str:
        """Return the OIDC callback URL registered at the provider."""
        return f"{self.public_url}/auth/oidc/callback"


@dataclass
class Request:
    """The parts of an HTTP request authentication looks at."""

    headers: dict           # lower-case names
    client_ip: str
    cookies: dict

    def header(self, name: str) -> str:
        """Return a header value or an empty string."""
        return self.headers.get(name.lower(), '')


class Authenticator:
    """Identifies users and issues signed session cookies."""

    def __init__(self, settings: AuthSettings, secret_key: bytes | None = None) -> None:
        self.settings = settings
        self._key = secret_key if secret_key is not None else (load_secret_key() if settings.enabled else b'')
        self._failures: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._discovery: tuple[float, dict] | None = None

    # ------------------------------------------------------------ signing

    def sign(self, payload: dict) -> str:
        """Return a signed, URL-safe token for a payload."""
        body = _b64(json.dumps(payload, separators=(',', ':')).encode())
        signature = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def unsign(self, token: str) -> dict | None:
        """Return the payload of a valid, unexpired token."""
        try:
            body, signature = token.split('.')
            expected = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(_unb64(body))
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or payload.get('exp', 0) < time.time():
            return None
        return payload

    def _cookie(self, name: str, value: str, max_age: int) -> str:
        parts = [f"{name}={value}", f"Path={self.settings.cookie_path}", f"Max-Age={max_age}",
                 'HttpOnly', 'SameSite=Lax']
        if self.settings.secure_cookie:
            parts.append('Secure')
        return '; '.join(parts)

    def session_cookie(self, user: User) -> str:
        """Return the Set-Cookie value of a new session."""
        lifetime = int(self.settings.session_hours * 3600)
        token = self.sign({'u': user.name, 'm': user.method, 'g': list(user.groups),
                           'exp': int(time.time()) + lifetime})
        return self._cookie(SESSION_COOKIE, token, lifetime)

    def logout_cookie(self) -> str:
        """Return the Set-Cookie value that ends the session."""
        return self._cookie(SESSION_COOKIE, '', 0)

    # ------------------------------------------------------- identification

    def _trusted_proxy(self, client_ip: str) -> bool:
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        return any(address in network for network in self.settings.trusted_proxies)

    def _authorize(self, user: User) -> User:
        """Apply the allowed user and group lists."""
        allowed_users = self.settings.allowed_users
        allowed_groups = self.settings.allowed_groups
        if not allowed_users and not allowed_groups:
            return user
        if user.name in allowed_users or set(user.groups) & set(allowed_groups):
            return user
        raise AuthError(f"User '{user.name}' is not allowed to use CineFlow.", 403)

    def identify(self, request: Request) -> User | None:
        """Return the user of a request, or None when it is not authenticated."""
        if not self.settings.enabled:
            return User('anonymous', 'none')
        if 'header' in self.settings.methods and self._trusted_proxy(request.client_ip):
            if name := request.header(self.settings.header_user).strip():
                groups = tuple(group.strip() for group in
                               request.header(self.settings.header_groups).replace(';', ',').split(',')
                               if group.strip())
                try:
                    return self._authorize(User(name, 'header', groups))
                except AuthError:
                    return None
        token = request.cookies.get(SESSION_COOKIE)
        payload = self.unsign(token) if token else None
        if payload and payload.get('m') in self.settings.methods:
            try:
                return self._authorize(User(payload['u'], payload['m'], tuple(payload.get('g') or ())))
            except AuthError:
                return None
        return None

    def status(self, request: Request) -> dict:
        """Return what the login page needs to know."""
        user = self.identify(request)
        return {
            'enabled': self.settings.enabled,
            'authenticated': user is not None,
            'user': user.to_dict() if user else None,
            'methods': list(self.settings.methods),
            'oidc_label': self.settings.oidc_label if 'oidc' in self.settings.methods else None,
        }

    # -------------------------------------------------------------- password

    def login_password(self, username: str, password: str, client_ip: str) -> User:
        """Check the local account; raises AuthError on failure."""
        if 'password' not in self.settings.methods:
            raise AuthError('Password login is not enabled.', 400)
        now = time.time()
        with self._lock:
            failures = self._failures[client_ip]
            while failures and failures[0] < now - LOGIN_WINDOW:
                failures.popleft()
            if len(failures) >= LOGIN_ATTEMPTS:
                raise AuthError('Too many failed logins. Try again in a few minutes.', 429)
        settings = self.settings
        valid_name = hmac.compare_digest(str(username), settings.username)
        if settings.password_hash:
            valid_password = verify_password(str(password), settings.password_hash)
        else:
            valid_password = hmac.compare_digest(str(password).encode(), settings.password.encode())
        if not (valid_name and valid_password):
            with self._lock:
                self._failures[client_ip].append(now)
            log(f"Failed GUI login for '{username}' from {client_ip}.", level='WARNING')
            raise AuthError('Wrong user name or password.')
        with self._lock:
            self._failures.pop(client_ip, None)
        return self._authorize(User(settings.username, 'password'))

    # ------------------------------------------------------------------ OIDC

    def _provider(self) -> dict:
        """Return the provider metadata, cached for an hour."""
        if self._discovery and self._discovery[0] > time.time():
            return self._discovery[1]
        url = f"{self.settings.oidc_issuer}/.well-known/openid-configuration"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            metadata = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AuthError(f"SSO provider is unreachable: {exc}", 502) from exc
        if str(metadata.get('issuer', '')).rstrip('/') != self.settings.oidc_issuer:
            raise AuthError('SSO provider issuer does not match CINEFLOW_OIDC_ISSUER.', 502)
        for key in ('authorization_endpoint', 'token_endpoint'):
            if not metadata.get(key):
                raise AuthError(f"SSO provider metadata has no {key}.", 502)
        self._discovery = (time.time() + 3600, metadata)
        return metadata

    def oidc_start(self, next_path: str = '') -> tuple[str, str]:
        """Return the provider login URL and the Set-Cookie value holding the state."""
        if 'oidc' not in self.settings.methods:
            raise AuthError('Single sign-on is not enabled.', 400)
        metadata = self._provider()
        state, nonce, verifier = (secrets.token_urlsafe(24), secrets.token_urlsafe(24),
                                  secrets.token_urlsafe(48))
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        cookie = self._cookie(OIDC_COOKIE, self.sign({
            's': state, 'n': nonce, 'v': verifier, 'next': safe_next(next_path),
            'exp': int(time.time()) + OIDC_STATE_SECONDS,
        }), OIDC_STATE_SECONDS)
        query = urlencode({
            'response_type': 'code',
            'client_id': self.settings.oidc_client_id,
            'redirect_uri': self.settings.oidc_redirect_url,
            'scope': self.settings.oidc_scopes,
            'state': state,
            'nonce': nonce,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        })
        return f"{metadata['authorization_endpoint']}?{query}", cookie

    def _token_request(self, metadata: dict, code: str, verifier: str) -> dict:
        settings = self.settings
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': settings.oidc_redirect_url,
            'code_verifier': verifier,
            'client_id': settings.oidc_client_id,
        }
        auth = None
        if settings.oidc_client_secret:
            if settings.oidc_token_auth == 'basic':
                auth = (settings.oidc_client_id, settings.oidc_client_secret)
            else:
                data['client_secret'] = settings.oidc_client_secret
        try:
            response = requests.post(metadata['token_endpoint'], data=data, auth=auth, timeout=15,
                                     headers={'Accept': 'application/json'})
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AuthError(f"SSO token request failed: {exc}", 502) from exc

    def _claims(self, tokens: dict, nonce: str, metadata: dict) -> dict:
        """Check the ID token and return the user claims.

        The ID token comes straight from the token endpoint over the back
        channel, so per OpenID Connect Core 3.1.3.7 the TLS connection
        authenticates it; issuer, audience, expiry and nonce are still checked.
        """
        try:
            payload = json.loads(_unb64(tokens['id_token'].split('.')[1]))
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise AuthError('SSO provider returned no valid ID token.', 502) from exc
        audience = payload.get('aud')
        audiences = audience if isinstance(audience, list) else [audience]
        if str(payload.get('iss', '')).rstrip('/') != self.settings.oidc_issuer:
            raise AuthError('ID token issuer mismatch.')
        if self.settings.oidc_client_id not in audiences:
            raise AuthError('ID token audience mismatch.')
        if payload.get('exp', 0) < time.time() - 60:
            raise AuthError('ID token expired.')
        if not hmac.compare_digest(str(payload.get('nonce', '')), nonce):
            raise AuthError('ID token nonce mismatch.')
        claims = dict(payload)
        wanted = (self.settings.oidc_user_claim, self.settings.oidc_groups_claim)
        if any(key not in claims for key in wanted):
            claims = {**self._userinfo(metadata, tokens, payload.get('sub')), **claims}
        return claims

    @staticmethod
    def _userinfo(metadata: dict, tokens: dict, subject: str) -> dict:
        """Return the userinfo claims of the same subject, or nothing."""
        if not metadata.get('userinfo_endpoint') or not tokens.get('access_token'):
            return {}
        try:
            response = requests.get(metadata['userinfo_endpoint'], timeout=10,
                                    headers={'Authorization': f"Bearer {tokens['access_token']}"})
            response.raise_for_status()
            info = response.json()
        except (requests.RequestException, ValueError) as exc:
            log(f"SSO userinfo request failed: {exc}", level='WARNING')
            return {}
        return info if isinstance(info, dict) and info.get('sub') == subject else {}

    def oidc_callback(self, query: dict, cookies: dict) -> tuple[User, str]:
        """Finish the SSO login; return the user and where to go next."""
        if 'oidc' not in self.settings.methods:
            raise AuthError('Single sign-on is not enabled.', 400)
        state = self.unsign(cookies.get(OIDC_COOKIE, ''))
        if not state:
            raise AuthError('The sign-in expired. Start it again.')
        if query.get('error'):
            raise AuthError(f"SSO provider refused the sign-in: {query.get('error')}")
        if not hmac.compare_digest(str(query.get('state', '')), state['s']) or not query.get('code'):
            raise AuthError('Invalid SSO sign-in response.')
        metadata = self._provider()
        claims = self._claims(self._token_request(metadata, query['code'], state['v']), state['n'], metadata)
        name = claims.get(self.settings.oidc_user_claim) or claims.get('email') or claims.get('sub')
        if not name:
            raise AuthError('SSO provider returned no user name.')
        groups = claims.get(self.settings.oidc_groups_claim) or ()
        groups = tuple(str(group) for group in (groups if isinstance(groups, list) else [groups]))
        user = self._authorize(User(str(name), 'oidc', groups))
        log(f"GUI sign-in of '{user.name}' through SSO.", level='INFO')
        return user, state.get('next') or ''

    def oidc_clear_cookie(self) -> str:
        """Return the Set-Cookie value removing the SSO state."""
        return self._cookie(OIDC_COOKIE, '', 0)


def safe_next(path: str) -> str:
    """Return a relative in-app path, never an external redirect target."""
    path = str(path or '')
    if not path.startswith('/') or path.startswith('//') or '\\' in path or ':' in path.split('?')[0]:
        return ''
    return path


def is_loopback(host: str) -> bool:
    """Return whether a listen address is reachable only from this machine."""
    if host in ('localhost', ''):
        return host == 'localhost'
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def cookie_jar(header: str) -> dict:
    """Parse a Cookie request header."""
    jar = {}
    for part in (header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep and name:
            jar[name] = value
    return jar


def secret_file() -> Path:
    """Return the path of the generated session key."""
    return config_directory() / '.cineflow' / 'secret'
