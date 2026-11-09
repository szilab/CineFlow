"""Torrent helpers: info hashes and Jellyfin folder names of downloads."""

import base64
import hashlib
import re
from urllib.parse import parse_qs, urljoin
import requests
from cineflow.core.logger import log
from cineflow.utils.misc import sanitize_path

MAX_REDIRECTS = 5


def media_folder(media: dict, suffix: str = '') -> str | None:
    """Return the Jellyfin folder name of an item: 'Title (year) [tmdbid-N]' and the suffix.

    The year and the TMDb ID are left out when unknown; None without a title.
    ``{field}`` in the suffix is replaced by that field of the item (empty when
    missing). Characters not allowed in a folder name are removed.
    """
    title = sanitize_path(media.get('title') or '').strip().rstrip('.').strip()
    if not title:
        return None
    name = title
    if media.get('year'):
        name += f" ({media['year']})"
    if media.get('tmdbid'):
        name += f" [tmdbid-{media['tmdbid']}]"
    if suffix:
        name += sanitize_path(re.sub(r'\{(\w+)\}', lambda match: _field_text(media.get(match.group(1))), suffix))
    # Windows does not allow a folder name to end with a space or a dot
    return name.rstrip(' .')


def _field_text(value) -> str:
    """Return an item value as folder name text."""
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return ','.join(str(item) for item in value)
    return str(value)


def folder_plan(files: list, target: str) -> tuple[str, str | None]:
    """Return how the content of a torrent gets a folder named ``target``.

    ``files`` are the file names of the torrent relative to its download directory.
    - ``('wait', None)``: no file list yet, the metadata has not arrived;
    - ``('done', root)``: the root folder already has the name;
    - ``('rename', root)``: the root folder is renamed;
    - ``('move', None)``: no root folder (a single file), the content moves into a new folder.
    """
    names = [str(name).replace('\\', '/') for name in files or [] if name]
    if not names:
        return 'wait', None
    roots = {name.split('/', 1)[0] for name in names}
    if len(roots) == 1 and all('/' in name for name in names):
        root = roots.pop()
        return ('done' if root == target else 'rename'), root
    return 'move', None


def join_path(directory: str, name: str) -> str:
    """Join a path of the download client's machine, keeping its separator."""
    directory = str(directory or '')
    separator = '\\' if '\\' in directory and '/' not in directory else '/'
    return directory.rstrip('/\\') + separator + name


def same_path(first: str, second: str) -> bool:
    """Return whether two client paths are the same, ignoring separators and a trailing one."""
    def norm(path: str) -> str:
        return str(path or '').replace('\\', '/').rstrip('/')
    return bool(norm(first)) and norm(first) == norm(second)


def path_name(path: str) -> str:
    """Return the last part of a client path."""
    return str(path or '').replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]


def magnet_hash(link: str) -> str | None:
    """Return the lowercase hex v1 info hash of a magnet link."""
    if not link or not str(link).startswith('magnet:?'):
        return None
    for value in parse_qs(str(link)[len('magnet:?'):]).get('xt', []):
        if not value.lower().startswith('urn:btih:'):
            continue
        digest = value[len('urn:btih:'):]
        if re.fullmatch(r'[0-9a-fA-F]{40}', digest):
            return digest.lower()
        if re.fullmatch(r'[A-Za-z2-7]{32}', digest):
            return base64.b32decode(digest.upper()).hex()
    return None


def info_hash(content: bytes) -> str | None:
    """Return the hex v1 info hash (SHA-1 of the bencoded info dictionary) of a torrent file."""
    try:
        if content[:1] != b'd':
            return None
        index = 1
        while content[index:index + 1] != b'e':
            key_end = _value_end(content, index)
            key = content[content.index(b':', index) + 1:key_end]
            value_end = _value_end(content, key_end)
            if key == b'info':
                return hashlib.sha1(content[key_end:value_end]).hexdigest()
            index = value_end
    except (ValueError, IndexError, RecursionError):
        pass
    return None


def _value_end(data: bytes, index: int) -> int:
    """Return the end index of the bencoded value starting at ``index``."""
    marker = data[index:index + 1]
    if marker == b'i':
        return data.index(b'e', index) + 1
    if marker in (b'l', b'd'):
        index += 1
        while data[index:index + 1] != b'e':
            if index >= len(data):
                raise ValueError('Unterminated bencoded value.')
            index = _value_end(data, index)
        return index + 1
    if marker.isdigit():
        colon = data.index(b':', index)
        end = colon + 1 + int(data[index:colon])
        if end > len(data):
            raise ValueError('Bencoded string past the end.')
        return end
    raise ValueError('Invalid bencoded value.')


def link_hash(link: str) -> str | None:
    """Return the v1 info hash of a magnet link or of the torrent an HTTP link serves.

    An HTTP link (e.g. of Jackett) is downloaded; a redirect to a magnet link is followed.
    """
    if not link:
        return None
    if link.startswith('magnet:'):
        return magnet_hash(link)
    if not link.startswith(('http://', 'https://')):
        return None
    url = link
    try:
        for _ in range(MAX_REDIRECTS + 1):
            response = requests.get(url, timeout=30, allow_redirects=False, headers={'User-Agent': 'CineFlow'})
            if response.is_redirect:
                url = urljoin(url, response.headers.get('Location', ''))
                if url.startswith('magnet:'):
                    return magnet_hash(url)
                continue
            response.raise_for_status()
            return info_hash(response.content)
        log(f"Too many redirects while reading torrent '{link}'.", level='WARNING')
    except requests.RequestException as exc:
        log(f"Failed to read torrent '{link}': {exc}", level='WARNING')
    return None
