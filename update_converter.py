#!/usr/bin/env python3
"""Check GitHub branches and launch the newest *source* build on Windows.

Only application source files are cached. The launcher, an existing EXE, Git
checkout, and user projects are never overwritten. No GitHub credentials are
needed for this public repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPOSITORY = 'KvaDRxniKuS/adobe-artcraft-converter'
API = f'https://api.github.com/repos/{REPOSITORY}'
GITHUB_HOSTS = {'api.github.com', 'codeload.github.com', 'github.com'}
SHA_PATTERN = re.compile(r'[a-fA-F0-9]{40}\Z')
SAFE_PY_NAME = re.compile(r'[A-Za-z0-9_.-]+\.py\Z', re.IGNORECASE)
# Explicit paths keep cached source layout consistent with the checkout. The
# entry points stay in the root; support modules and templates live below it.
ROOT_ENTRY_POINTS = frozenset({
    'desktop_app.py', 'update_converter.py', 'prproj_to_fcproj.py',
    'fcproj_to_prproj.py', 'shortcut_converter.py', 'aex_to_effectcraft.py',
})
CORE_MODULES = frozenset({
    'craft_converter/__init__.py', 'craft_converter/direct_fc_to_prproj.py',
    'craft_converter/project_import.py', 'craft_converter/reverse_project.py',
    'craft_converter/graphic_raster.py', 'craft_converter/premiere_seed.py',
    'craft_converter/premiere_text.py', 'craft_converter/premiere_text_seed.py',
    'craft_converter/effectcraft_pixel_sorter.py',
    'craft_converter/effectcraft_deep_glow.py',
})
SHORTCUT_TEMPLATES = frozenset({
    'resources/shortcuts/FilmCraft_Shortcuts_Template.json',
    'resources/shortcuts/Premiere_Shortcuts_Template.kys',
})
REQUIRED_FILES = ROOT_ENTRY_POINTS | CORE_MODULES | SHORTCUT_TEMPLATES | {'requirements.txt'}
MAX_BRANCHES = 40  # Unauthenticated GitHub API calls are limited to 60 per hour.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
EXIT_QT_UNAVAILABLE = 42  # Batch launcher may fall back to an existing EXE.


class UpdateError(RuntimeError):
    """A remote or cached update could not be safely installed."""


@dataclass(frozen=True)
class Revision:
    branch: str
    sha: str
    committed: datetime


def valid_sha(value: str) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        target = urllib.parse.urlparse(new_url)
        if target.scheme != 'https' or target.hostname not in GITHUB_HOSTS:
            raise UpdateError('GitHub redirected to an unexpected host')
        return super().redirect_request(request, response, code, message, headers, new_url)


def github_request(url: str, *, timeout: int = 10):
    """Open only the official GitHub API/archive hosts over HTTPS."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in GITHUB_HOSTS:
        raise UpdateError(f'Refusing non-GitHub URL: {url}')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'FilmCraftConverter-SourceUpdater',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    response = urllib.request.build_opener(GitHubRedirects).open(request, timeout=timeout)
    final = urllib.parse.urlparse(response.geturl())
    if final.scheme != 'https' or final.hostname not in GITHUB_HOSTS:
        response.close()
        raise UpdateError('GitHub redirected to an unexpected host')
    return response


def github_json(url: str):
    with github_request(url) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise UpdateError('GitHub API response is too large')
    return json.loads(data.decode('utf-8'))


def newest_branch(get_json=github_json) -> Revision:
    """Choose the branch whose HEAD has the latest committer timestamp."""
    branches = get_json(f'{API}/branches?per_page=100')
    if not isinstance(branches, list) or not branches:
        raise UpdateError('GitHub returned no branches')
    # Request 100 at once so exceeding our smaller limit cannot be hidden by pagination.
    if len(branches) > MAX_BRANCHES:
        raise UpdateError('Too many branches for an unauthenticated update check')

    dates: dict[str, datetime] = {}
    revisions = []
    for branch in branches:
        name = branch['name']
        sha = branch['commit']['sha']
        if not isinstance(name, str) or not valid_sha(sha):
            raise UpdateError('GitHub returned an invalid branch or commit')
        sha = sha.lower()
        if sha not in dates:
            commit = get_json(f'{API}/commits/{sha}')
            if commit.get('sha', '').lower() != sha:
                raise UpdateError('GitHub commit SHA does not match its branch')
            info = commit.get('commit', {})
            date = (info.get('committer') or {}).get('date') or (info.get('author') or {}).get('date')
            if not date:
                raise UpdateError(f'Missing commit date for {name}')
            dates[sha] = datetime.fromisoformat(date.replace('Z', '+00:00')).astimezone(timezone.utc)
        revisions.append(Revision(name, sha, dates[sha]))
    # If both branches point to the same HEAD, prefer main over a topic branch.
    return max(revisions, key=lambda r: (r.committed, r.branch == 'main', r.branch))


def default_cache_dir() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / '.cache'
    return base / 'FilmCraftConverter' / 'source-updates'


def valid_app_dir(folder: Path) -> bool:
    return folder.is_dir() and all((folder / name).is_file() for name in REQUIRED_FILES)


def valid_cached_version(folder: Path, versions: Path) -> bool:
    return (not versions.is_symlink() and not folder.is_symlink()
            and folder.resolve().parent == versions.resolve()
            and valid_app_dir(folder)
            and all(not (folder / name).is_symlink() for name in REQUIRED_FILES)
            and all(not (folder / directory).is_symlink() for directory in
                    ('craft_converter', 'resources', 'resources/shortcuts')))


def cached_app(cache_dir: Path) -> Path | None:
    """Only a validated SHA inside our version directory may be launched."""
    try:
        state = json.loads((cache_dir / 'current.json').read_text(encoding='utf-8'))
        sha = state['sha']
        if valid_sha(sha):
            versions = cache_dir / 'versions'
            folder = versions / sha.lower()
            if valid_cached_version(folder, versions):
                return folder
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        pass
    return None


def download_archive(sha: str, destination: Path) -> None:
    if not valid_sha(sha):
        raise UpdateError('Invalid commit SHA')
    url = f'{API}/zipball/{sha}'
    with github_request(url, timeout=20) as response, destination.open('xb') as out:
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_ARCHIVE_BYTES:
            raise UpdateError('Update archive exceeds the size limit')
        size = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise UpdateError('Update archive exceeds the size limit')
            out.write(chunk)


def unpack_source(archive: Path, destination: Path) -> None:
    """Extract only root entry points, internal modules and shortcut data."""
    destination.mkdir()
    seen = set()
    archive_root = None
    total = 0
    with zipfile.ZipFile(archive) as package:
        if len(package.infolist()) > 2000:
            raise UpdateError('Update archive contains too many entries')
        for member in package.infolist():
            if member.is_dir():
                continue
            parts = PurePosixPath(member.filename).parts
            if len(parts) < 2:
                continue
            if parts[0] in ('', '.', '..', '/') or any(part in ('', '.', '..') for part in parts[1:]):
                raise UpdateError('Unsafe archive path')
            relative = '/'.join(parts[1:])
            # No arbitrary directories: tests, tools, user data and WASM builds
            # never enter the source-only update cache. The embedded effects
            # travel inside craft_converter/effectcraft_*.py instead.
            if len(parts) == 2:
                selected = SAFE_PY_NAME.fullmatch(parts[1]) or relative == 'requirements.txt'
            elif len(parts) == 3 and parts[1] == 'craft_converter':
                selected = SAFE_PY_NAME.fullmatch(parts[2])
            elif len(parts) == 4 and parts[1:3] == ('resources', 'shortcuts'):
                selected = relative in SHORTCUT_TEMPLATES
            else:
                selected = False
            if not selected:
                continue
            if archive_root is None:
                archive_root = parts[0]
            elif archive_root != parts[0]:
                raise UpdateError('Source archive has multiple root directories')
            if (member.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise UpdateError('Source archive contains a symlink')
            key = relative.casefold()
            if key in seen:
                raise UpdateError('Source archive contains duplicate filenames')
            seen.add(key)
            if member.file_size > MAX_FILE_BYTES:
                raise UpdateError(f'Update file is too large: {relative}')
            total += member.file_size
            if total > MAX_SOURCE_BYTES:
                raise UpdateError('Update source exceeds the size limit')
            target = destination.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open('xb') as out:
                written = 0
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise UpdateError('Update file is too large: ' + relative)
                    out.write(chunk)
    if not valid_app_dir(destination):
        raise UpdateError('Archive lacks required application files')
    # Reject damaged/incompatible Python source before changing the selected version.
    for path in list(destination.glob('*.py')) + list((destination / 'craft_converter').glob('*.py')):
        compile(path.read_bytes(), str(path), 'exec')


def save_current(cache_dir: Path, revision: Revision) -> None:
    state = {'sha': revision.sha, 'branch': revision.branch,
             'committed': revision.committed.isoformat()}
    temp = cache_dir / f'.current-{os.getpid()}.tmp'
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, cache_dir / 'current.json')
    finally:
        temp.unlink(missing_ok=True)


def install_revision(cache_dir: Path, revision: Revision,
                     download=download_archive) -> Path:
    if not valid_sha(revision.sha):
        raise UpdateError('Invalid commit SHA')
    versions = cache_dir / 'versions'
    if versions.is_symlink():
        raise UpdateError('Update cache versions directory must not be a symlink')
    versions.mkdir(parents=True, exist_ok=True)
    target = versions / revision.sha.lower()
    if target.exists() or target.is_symlink():
        if not valid_cached_version(target, versions):
            raise UpdateError('Cached version is incomplete or unsafe; remove it manually')
        save_current(cache_dir, revision)
        return target

    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=cache_dir))
    try:
        archive = staging / 'source.zip'
        download(revision.sha, archive)
        extracted = staging / 'app'
        unpack_source(archive, extracted)
        try:
            os.replace(extracted, target)
        except OSError:
            if not valid_cached_version(target, versions):  # Another launch may have installed it.
                raise
        save_current(cache_dir, revision)
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def choose_source(source_dir: Path, cache_dir: Path,
                  get_latest=newest_branch, download=download_archive) -> Path:
    local = source_dir if valid_app_dir(source_dir) else None
    existing = cached_app(cache_dir)
    if os.environ.get('FILMCRAFT_SKIP_UPDATE') == '1':
        if local is None:
            raise UpdateError('Local source is incomplete')
        print('Update check skipped by FILMCRAFT_SKIP_UPDATE=1.', file=sys.stderr)
        return local
    try:
        revision = get_latest()
        selected = install_revision(cache_dir, revision, download)
        print(f'Using {revision.branch} @ {revision.sha[:12]} (latest commit).', file=sys.stderr)
        return selected
    except Exception as exc:
        # Network, archive, and cache errors must not prevent an offline launch.
        print(f'Update check failed: {exc}', file=sys.stderr)
        if existing:
            print('Starting the last downloaded source version.', file=sys.stderr)
            return existing
        if local:
            print('Starting the local source version.', file=sys.stderr)
            return local
        raise UpdateError('No usable project source is available') from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Update FilmCraft Converter source and launch it')
    parser.add_argument('--source-dir', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--cache-dir', type=Path, default=default_cache_dir())
    args = parser.parse_args(argv)
    try:
        app_dir = choose_source(args.source_dir.resolve(), args.cache_dir.resolve())
    except UpdateError as exc:
        print(f'Cannot launch FilmCraft Converter: {exc}', file=sys.stderr)
        return 1
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401 - verify Qt can actually load
    except (ImportError, OSError):
        print('Source cannot run without PySide6/Qt. '
              'Install requirements.txt to use source updates (the EXE is not updated).', file=sys.stderr)
        return EXIT_QT_UNAVAILABLE
    return subprocess.call([sys.executable, str(app_dir / 'desktop_app.py')], cwd=app_dir)


if __name__ == '__main__':
    raise SystemExit(main())
