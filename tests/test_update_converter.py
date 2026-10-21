"""Offline tests for the source-only GitHub updater."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.update_converter import (
    EXIT_QT_UNAVAILABLE, GitHubRedirects, REQUIRED_FILES, Revision, UpdateError,
    cached_app, choose_source,
    github_request, install_revision, main, newest_branch, unpack_source,
)

SHA_OLD = 'a' * 40
SHA_NEW = 'b' * 40


def make_archive(destination: Path, *, sha=SHA_NEW, files=None):
    contents = {name: ('print("updated")\n' if name.endswith('.py') else 'data')
                for name in REQUIRED_FILES}
    contents['app/new_module.py'] = 'VALUE = 1\n'
    contents['new_module.py'] = 'VALUE = 2\n'  # Root Python files must not be cached.
    contents['Start_Converter.bat'] = 'remote launcher'
    contents.update(files or {})
    with zipfile.ZipFile(destination, 'w') as archive:
        for filename, content in contents.items():
            archive.writestr(f'adobe-artcraft-converter-{sha[:7]}/{filename}', content)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.local = self.base / 'checkout'
        self.local.mkdir()
        for name in REQUIRED_FILES:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('print("local")\n' if name.endswith('.py') else 'old',
                            encoding='utf-8')
        (self.local / 'dist').mkdir()
        (self.local / 'dist' / 'FilmCraftConverter.exe').write_bytes(b'local exe')
        (self.local / 'Start_Converter.bat').write_text('local launcher', encoding='utf-8')
        uploads = self.local / 'uploads'
        uploads.mkdir()
        (uploads / 'private.fcproj').write_text('private project', encoding='utf-8')
        self.cache = self.base / 'cache'
        self.revision = Revision('feature/latest', SHA_NEW,
                                 datetime(2026, 10, 16, tzinfo=timezone.utc))

    def download(self, sha, destination):
        self.assertEqual(sha, SHA_NEW)
        make_archive(destination, sha=sha)

    def test_latest_commit_across_branches_not_default_branch(self):
        def get_json(url):
            if '/branches?' in url:
                return [{'name': 'main', 'commit': {'sha': SHA_OLD}},
                        {'name': 'feature/latest', 'commit': {'sha': SHA_NEW}}]
            if url.endswith(SHA_OLD):
                return {'sha': SHA_OLD, 'commit': {'committer': {'date': '2026-10-01T00:00:00Z'}}}
            if url.endswith(SHA_NEW):
                return {'sha': SHA_NEW, 'commit': {'committer': {'date': '2026-10-16T00:00:00Z'}}}
            raise AssertionError(url)

        revision = newest_branch(get_json)
        self.assertEqual(revision.branch, 'feature/latest')
        self.assertEqual(revision.sha, SHA_NEW)
        self.assertEqual(revision.committed, datetime(2026, 10, 16, tzinfo=timezone.utc))

    def test_branch_limit_does_not_silently_ignore_newer_branches(self):
        with self.assertRaisesRegex(UpdateError, 'Too many branches'):
            newest_branch(lambda _: [{'name': str(i), 'commit': {'sha': SHA_OLD}}
                                     for i in range(41)])

    def test_equal_commits_prefer_main_and_do_not_repeat_request(self):
        commits = []

        def get_json(url):
            if '/branches?' in url:
                return [{'name': 'topic', 'commit': {'sha': SHA_NEW}},
                        {'name': 'main', 'commit': {'sha': SHA_NEW}}]
            commits.append(url)
            return {'sha': SHA_NEW, 'commit': {'committer': {'date': '2026-10-16T00:00:00Z'}}}

        self.assertEqual(newest_branch(get_json).branch, 'main')
        self.assertEqual(len(commits), 1)

    def test_install_is_versioned_and_keeps_checkout_exe_and_projects(self):
        selected = choose_source(self.local, self.cache,
                                 get_latest=lambda: self.revision, download=self.download)
        self.assertEqual(selected, self.cache / 'versions' / SHA_NEW)
        self.assertEqual((selected / 'app/desktop_app.py').read_text(), 'print("updated")\n')
        self.assertTrue((selected / 'craft_converter' / 'project_import.py').is_file())
        self.assertTrue((selected / 'resources/shortcuts/FilmCraft_Shortcuts_Template.json').is_file())
        self.assertTrue((selected / 'tools/export_ae_effect_metadata.jsx').is_file())
        self.assertFalse((selected / 'project_import.py').exists())
        self.assertTrue((selected / 'app/new_module.py').is_file())
        self.assertFalse((selected / 'new_module.py').exists())
        self.assertEqual((self.local / 'app/desktop_app.py').read_text(), 'print("local")\n')
        self.assertEqual((self.local / 'dist/FilmCraftConverter.exe').read_bytes(), b'local exe')
        self.assertEqual((self.local / 'Start_Converter.bat').read_text(), 'local launcher')
        self.assertFalse((selected / 'Start_Converter.bat').exists())
        self.assertEqual((self.local / 'uploads' / 'private.fcproj').read_text(), 'private project')
        self.assertEqual(cached_app(self.cache), selected)
        # A second launch with the same SHA does not download a second time.
        selected_again = choose_source(self.local, self.cache,
                                       get_latest=lambda: self.revision,
                                       download=lambda *_: self.fail('Downloaded twice'))
        self.assertEqual(selected_again, selected)

    def test_offline_and_failed_download_keep_last_good_version(self):
        old = Revision('main', SHA_OLD, datetime(2026, 10, 1, tzinfo=timezone.utc))
        install_revision(self.cache, old, download=lambda sha, path: make_archive(path, sha=sha))
        previous = cached_app(self.cache)

        def offline():
            raise urllib.error.URLError('offline')

        self.assertEqual(choose_source(self.local, self.cache, get_latest=offline), previous)

        def interrupted_download(sha, path):
            path.write_bytes(b'not a zip')

        self.assertEqual(choose_source(self.local, self.cache,
                                       get_latest=lambda: self.revision,
                                       download=interrupted_download), previous)
        self.assertFalse((self.cache / 'versions' / SHA_NEW).exists())
        self.assertEqual(json.loads((self.cache / 'current.json').read_text())['sha'], SHA_OLD)

    def test_offline_without_cache_uses_local_source(self):
        def offline():
            raise urllib.error.URLError('offline')
        self.assertEqual(choose_source(self.local, self.cache, get_latest=offline), self.local)

    def test_skip_update_uses_local_without_network(self):
        with patch.dict('os.environ', {'FILMCRAFT_SKIP_UPDATE': '1'}):
            self.assertEqual(choose_source(
                self.local, self.cache,
                get_latest=lambda: self.fail('Network requested')),
                self.local)

    def test_source_archive_preserves_package_and_shortcut_layout(self):
        repository = Path(__file__).resolve().parents[1]
        archive = self.base / 'current.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            for directory in (repository / 'app', repository / 'converters',
                              repository / 'craft_converter'):
                for path in directory.glob('*.py'):
                    package.write(path, f'root/{path.relative_to(repository).as_posix()}')
            for name in REQUIRED_FILES:
                if not name.endswith('.py'):
                    package.write(repository / name, f'root/{name}')
            package.write(repository / 'effectcraft_plugins/DeepGlow_EffectCraft.wasm',
                          'root/effectcraft_plugins/DeepGlow_EffectCraft.wasm')
            package.writestr('root/tools/ignored.py', 'raise RuntimeError("tools are not needed")')
        output = self.base / 'installed'
        unpack_source(archive, output)
        self.assertEqual((output / 'craft_converter/premiere_seed.py').read_bytes(),
                         (repository / 'craft_converter/premiere_seed.py').read_bytes())
        for name in REQUIRED_FILES:
            self.assertTrue((output / name).is_file(), name)
        for name in ('direct_fc_to_prproj.py', 'graphic_raster.py', 'premiere_text.py',
                     'premiere_text_seed.py', 'effectcraft_pixel_sorter.py',
                     'effectcraft_deep_glow.py', 'effectcraft_measured_lut.py',
                     'effectcraft_measured_beam.py', 'beam_layout.py', 'measured_beam.py',
                     'lut_layout.py', 'measured_port.py'):
            self.assertFalse((output / name).exists(), name)
            self.assertTrue((output / 'craft_converter' / name).is_file(), name)
        # Embedded WASM is shipped as Python data; only allowlisted AE-host
        # scripts enter tools (no binary build products or .aex inputs).
        for name in ('effectcraft_pixel_sorter.py', 'effectcraft_deep_glow.py',
                     'effectcraft_measured_lut.py', 'effectcraft_measured_beam.py'):
            self.assertEqual((output / 'craft_converter' / name).read_bytes(),
                             (repository / 'craft_converter' / name).read_bytes())
        self.assertFalse((output / 'effectcraft_plugins').exists())
        self.assertEqual(sorted(p.name for p in (output / 'tools').iterdir()),
                         ['export_ae_deep_glow_values.jsx', 'export_ae_effect_metadata.jsx'])
        for name in ('export_ae_effect_metadata.jsx', 'export_ae_deep_glow_values.jsx'):
            self.assertEqual((output / 'tools' / name).read_bytes(),
                             (repository / 'tools' / name).read_bytes())
        self.assertFalse((output / 'FilmCraft_Shortcuts_Template.json').exists())
        self.assertIn('Pillow', (output / 'config/requirements.txt').read_text(encoding='utf-8'))
        self.assertIn('flatbuffers', (output / 'config/requirements.txt').read_text(encoding='utf-8'))
        # Import the unpacked source from outside the checkout, as the launcher
        # does when it starts a cached copy; root-only imports would fail here.
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        subprocess.run([sys.executable, '-c',
                        'import app.update_converter, converters.aex_to_effectcraft; '
                        'import converters.fcproj_to_prproj, converters.prproj_to_fcproj; '
                        'import craft_converter.project_import; '
                        'from pathlib import Path; '
                        'assert Path("resources/shortcuts/Premiere_Shortcuts_Template.kys").is_file()'],
                       cwd=output, env=env, check=True, capture_output=True)
        for module in ('app.update_converter', 'converters.aex_to_effectcraft',
                       'converters.prproj_to_fcproj', 'converters.fcproj_to_prproj',
                       'converters.shortcut_converter'):
            with self.subTest(module=module):
                subprocess.run([sys.executable, '-m', module, '--help'],
                               cwd=output, env=env, check=True, capture_output=True)

    def test_archive_rejects_duplicate_and_symlink_and_bad_python(self):
        archive = self.base / 'source.zip'
        make_archive(archive, files={'app/bad.py': 'def broken(\n'})
        with self.assertRaises(SyntaxError):
            unpack_source(archive, self.base / 'bad')

        with zipfile.ZipFile(archive, 'w') as package:
            for name in REQUIRED_FILES:
                package.writestr(f'root/{name}', 'print("ok")' if name.endswith('.py') else 'data')
            package.writestr('root/app/DESKTOP_APP.PY', 'print("duplicate")')
        with self.assertRaisesRegex(UpdateError, 'duplicate'):
            unpack_source(archive, self.base / 'duplicate')

        with zipfile.ZipFile(archive, 'w') as package:
            for name in REQUIRED_FILES - {'app/desktop_app.py'}:
                package.writestr(f'root/{name}', 'print("ok")' if name.endswith('.py') else 'data')
            link = zipfile.ZipInfo('root/app/desktop_app.py')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(link, 'other.py')
        with self.assertRaisesRegex(UpdateError, 'symlink'):
            unpack_source(archive, self.base / 'symlink')

        make_archive(archive, files={'craft_converter/PROJECT_IMPORT.PY': 'print("duplicate")'})
        with self.assertRaisesRegex(UpdateError, 'duplicate'):
            unpack_source(archive, self.base / 'nested_duplicate')

        with zipfile.ZipFile(archive, 'w') as package:
            for name in REQUIRED_FILES - {'craft_converter/project_import.py'}:
                package.writestr(f'root/{name}', 'print("ok")' if name.endswith('.py') else 'data')
            link = zipfile.ZipInfo('root/craft_converter/project_import.py')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(link, '../desktop_app.py')
        with self.assertRaisesRegex(UpdateError, 'symlink'):
            unpack_source(archive, self.base / 'nested_symlink')

        make_archive(archive, files={'../escaped.py': 'print("escape")'})
        with self.assertRaisesRegex(UpdateError, 'Unsafe archive path'):
            unpack_source(archive, self.base / 'traversal')
        self.assertFalse((self.base / 'escaped.py').exists())

    def test_github_request_refuses_untrusted_hosts_without_network(self):
        with self.assertRaisesRegex(UpdateError, 'non-GitHub'):
            github_request('https://example.com/not-github')
        request = urllib.request.Request('https://api.github.com/repos/owner/repo')
        with self.assertRaisesRegex(UpdateError, 'unexpected host'):
            GitHubRedirects().redirect_request(request, None, 302, 'redirect', {},
                                                'https://example.com/source.zip')

    def test_default_source_directory_is_checkout_root(self):
        root = Path(__file__).resolve().parents[1]
        with patch('app.update_converter.choose_source', return_value=root) as choose, \
             patch.dict(sys.modules, {'PySide6': None, 'PySide6.QtWidgets': None}):
            self.assertEqual(main(['--cache-dir', str(self.cache)]), EXIT_QT_UNAVAILABLE)
        self.assertEqual(choose.call_args.args[0], root)

    def test_launcher_uses_selected_source_or_reports_missing_qt(self):
        argv = ['--source-dir', str(self.local), '--cache-dir', str(self.cache)]
        with patch('app.update_converter.choose_source', return_value=self.local), \
             patch.dict(sys.modules, {'PySide6': None, 'PySide6.QtWidgets': None}):
            self.assertEqual(main(argv), EXIT_QT_UNAVAILABLE)
        qt = types.ModuleType('PySide6.QtWidgets')
        qt.QApplication = object
        with patch('app.update_converter.choose_source', return_value=self.local), \
             patch.dict(sys.modules, {'PySide6': types.ModuleType('PySide6'),
                                      'PySide6.QtWidgets': qt}), \
             patch('app.update_converter.subprocess.call', return_value=0) as launch:
            self.assertEqual(main(argv), 0)
            launch.assert_called_once_with(
                [sys.executable, '-m', 'app.desktop_app'], cwd=self.local)


if __name__ == '__main__':
    unittest.main()
