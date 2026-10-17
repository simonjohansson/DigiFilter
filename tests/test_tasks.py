"""Workflow checks without stock firmware, compilers or network access."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import tasks
import ob1_check


class Workflows(unittest.TestCase):
    def test_subprocess_preserves_spaces_and_shell_characters(self):
        with tempfile.TemporaryDirectory(prefix='DigiFilter space ') as directory:
            script = Path(directory) / 'echo arguments.py'
            script.write_text('import sys; print(sys.argv[1])', encoding='utf-8')
            value = 'path with spaces; $HOME & more'
            self.assertEqual(tasks.run([sys.executable, script, value], capture=True), value)

    def test_subprocess_failure_is_not_swallowed(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            tasks.run([sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual(error.exception.returncode, 7)

    def test_artifacts_keep_sdk_os_suffixes(self):
        with patch.object(tasks, 'manifest', return_value={'id': 'digifilter', 'version': '1.1a', 'os': '1.53'}):
            self.assertEqual(tasks.artifact(tasks.ROOT, '1.53').name, 'digifilter-1.1a.elemod')
            self.assertEqual(tasks.artifact(tasks.ROOT, '1.54').name, 'digifilter-1.1a-os1.54.elemod')

    def test_mislabeled_stock_is_rejected_before_building(self):
        with patch.dict(os.environ, {'DIGIFILTER_BUILD_OS': ''}), \
                patch.object(tasks, 'stock_os', return_value='1.54'):
            with self.assertRaisesRegex(ValueError, 'does not contain stock OS 1.53'):
                tasks.stocks()

    def test_build_os_selection(self):
        for selected, expected in (('', ('1.53', '1.54')), ('1.54', ('1.54',))):
            with self.subTest(selected=selected), \
                    patch.dict(os.environ, {'DIGIFILTER_BUILD_OS': selected}), \
                    patch.object(tasks, 'stock_os', side_effect=expected):
                self.assertEqual(tasks.stocks(), [
                    tasks.ROOT / 'firmware' / f'Digitakt_OS{version}.syx'
                    for version in expected])
        with patch.dict(os.environ, {'DIGIFILTER_BUILD_OS': '1.55'}), \
                patch.object(tasks, 'stock_os') as identify:
            with self.assertRaisesRegex(ValueError, 'DIGIFILTER_BUILD_OS'):
                tasks.stocks()
            identify.assert_not_called()

    def test_stock_device_and_os_are_validated_by_content(self):
        devices = Mock()
        device, release = Mock(key='digitakt-mk1'), Mock(version='1.53')
        devices.identify.return_value = device, release
        with tempfile.TemporaryDirectory() as directory:
            stock = Path(directory) / 'arbitrary name.syx'
            stock.write_bytes(b'fixture')
            with patch.dict(sys.modules, {'elekloader': Mock(devices=devices)}):
                self.assertEqual(tasks.stock_os(stock), '1.53')
                device.key = 'digitone-mk1'
                with self.assertRaises(ValueError):
                    tasks.stock_os(stock)
                device.key, release.version = 'digitakt-mk1', '1.52'
                with self.assertRaises(ValueError):
                    tasks.stock_os(stock)

    def test_bootstrap_uses_native_installer_only_when_needed(self):
        for platform, interpreter, installer in (
                ('win32', 'powershell', 'tools/install-patched-unicorn.ps1'),
                ('darwin', 'bash', 'tools/install-patched-unicorn.sh'),
                ('linux', 'bash', 'tools/install-patched-unicorn.sh')):
            with self.subTest(platform=platform), patch.object(sys, 'platform', platform), \
                    patch.object(tasks, 'emulator_python', return_value=Path('/fake/python')), \
                    patch.object(tasks, 'run') as run, patch.dict(os.environ), \
                    patch.object(subprocess, 'run', return_value=Mock(returncode=1)):
                tasks.bootstrap()
                command = run.call_args_list[1].args[0]
                self.assertEqual(command[0], interpreter)
                self.assertEqual(command[-1], installer)
                self.assertEqual(os.environ['PYTHON'], str(Path('/fake/python')))
        with patch.object(tasks, 'emulator_python', return_value=Path('/fake/python')), \
                patch.object(tasks, 'run') as run, \
                patch.object(subprocess, 'run', return_value=Mock(returncode=0)):
            tasks.bootstrap()
            self.assertEqual(run.call_count, 2)

    def test_windows_native_builder_uses_dll_and_compiler_path(self):
        with patch.object(sys, 'platform', 'win32'), \
                patch.dict(os.environ, {'CC': 'C:/Compiler Tools/gcc.exe'}), \
                patch.object(subprocess, 'check_call') as compile_, \
                patch.object(ctypes, 'CDLL') as load:
            ob1_check.build()
            command = compile_.call_args.args[0]
            self.assertEqual(command[0], 'C:/Compiler Tools/gcc.exe')
            self.assertNotIn('-fPIC', command)
            self.assertTrue(command[-1].endswith('.dll'))
            load.assert_called_once_with(command[-1])

    def test_release_requires_clean_source(self):
        with patch.object(tasks, 'run', return_value=' M filter.c') as run:
            with self.assertRaisesRegex(ValueError, 'commit first'):
                tasks.release()
            self.assertEqual(run.call_count, 1)

    def test_release_requires_both_os_builds(self):
        with patch.dict(os.environ, {'DIGIFILTER_BUILD_OS': '1.54'}), \
                patch.object(tasks, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'unset DIGIFILTER_BUILD_OS'):
                tasks.release()
            run.assert_not_called()

    def test_release_stops_when_source_is_not_pushed(self):
        with patch.object(tasks, 'run', side_effect=['', None, 'unpushed commit']) as run:
            with self.assertRaisesRegex(ValueError, 'push first'):
                tasks.release()
            self.assertEqual(run.call_args.args[0], ['git', 'log', 'origin/master..HEAD'])
            self.assertFalse(any(call.args[0][0] == 'gh' for call in run.call_args_list))

    def test_release_stops_when_fetch_fails(self):
        with patch.object(tasks, 'run', side_effect=['', subprocess.CalledProcessError(1, 'git')]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                tasks.release()
            self.assertEqual(run.call_count, 2)

    def test_release_publishes_both_elemods_at_the_checked_commit(self):
        with patch.object(tasks, 'run', side_effect=['', None, '', 'commit-sha', None]) as run, \
                patch.object(tasks, 'manifest', return_value={'id': 'digifilter', 'version': '2.0', 'os': '1.53'}), \
                patch.object(tasks, 'OUT', Path('out')):
            tasks.release()
            self.assertEqual(run.call_args.args[0], [
                'gh', 'release', 'create', 'v2.0',
                Path('out/os1.53/digifilter-2.0.elemod'),
                Path('out/os1.54/digifilter-2.0-os1.54.elemod'),
                '--target', 'commit-sha', '--title', 'DigiFilter 2.0', '--generate-notes'])


if __name__ == '__main__':
    unittest.main()
