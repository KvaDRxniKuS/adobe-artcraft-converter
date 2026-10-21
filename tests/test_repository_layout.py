"""Regression checks for the three-file repository root and Windows entry points."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'README.md', 'Start_Converter.bat', 'Build_Windows_EXE.bat'}


class RepositoryLayoutTests(unittest.TestCase):
    def test_only_readme_and_batch_files_live_at_root(self):
        self.assertEqual({path.name for path in ROOT.iterdir() if path.is_file()}, ROOT_FILES)
        for filename in ('app/desktop_app.py', 'app/update_converter.py',
                         'converters/aex_to_effectcraft.py',
                         'converters/fcproj_to_prproj.py',
                         'converters/prproj_to_fcproj.py',
                         'converters/shortcut_converter.py',
                         'config/requirements.txt'):
            self.assertTrue((ROOT / filename).is_file(), filename)

    def test_launch_and_build_use_package_modules_and_dist_exe(self):
        launch = (ROOT / 'Start_Converter.bat').read_text(encoding='utf-8')
        build = (ROOT / 'Build_Windows_EXE.bat').read_text(encoding='utf-8')
        self.assertIn('-m app.update_converter', launch)
        self.assertIn('-m app.desktop_app', launch)
        self.assertIn('app\\update_converter.py', launch)
        self.assertIn('dist\\FilmCraftConverter.exe', launch)
        self.assertIn('config\\requirements.txt', launch)
        self.assertIn('config\\requirements.txt', build)
        self.assertIn('app\\desktop_app.py', build)
        self.assertIn('--paths "."', build)
        self.assertIn('dist\\FilmCraftConverter.exe', build)
        self.assertNotIn('copy /y', build.lower())

    def test_local_data_and_build_products_have_portable_nested_ignores(self):
        for directory in ('uploads', 'dist', 'build', 'effectcraft_plugins',
                          'app', 'converters', 'craft_converter', 'tests', 'tools'):
            self.assertTrue((ROOT / directory / '.gitignore').is_file(), directory)
        self.assertIn('*.wasm', (ROOT / 'effectcraft_plugins/.gitignore').read_text())


if __name__ == '__main__':
    unittest.main()
