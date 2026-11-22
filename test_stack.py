import os, tempfile, unittest, tarfile
from unittest import mock
from pathlib import Path
import stack

class StackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        stack.ROOT = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_name_rejects_escape(self):
        with self.assertRaises(SystemExit): stack.project_path('../x')
        with self.assertRaises(SystemExit): stack.project_path('/tmp/x')

    def test_projects_only_lists_real_compose_files(self):
        good = stack.ROOT / 'demo'; good.mkdir(); (good / 'compose.yaml').write_text('services: {}')
        link = stack.ROOT / 'link'; link.symlink_to(good, target_is_directory=True)
        self.assertEqual([good], stack.projects())

    def test_compose_names(self):
        p = stack.ROOT / 'demo'; p.mkdir(); (p / 'compose.yml').write_text('services: {}')
        self.assertEqual(p / 'compose.yml', stack.compose_file(p))

    def test_discover_finds_nested_projects_and_skips_symlinks(self):
        source = Path(self.tmp.name) / 'source'; source.mkdir()
        nested = source / 'old' / 'demo'; nested.mkdir(parents=True)
        (nested / 'docker-compose.yaml').write_text('services: {}')
        link = source / 'link'; link.symlink_to(nested, target_is_directory=True)
        self.assertEqual([nested], stack.discover(source))

    def test_discover_respects_depth(self):
        source = Path(self.tmp.name) / 'source'; source.mkdir()
        nested = source / 'a' / 'b' / 'c' / 'demo'; nested.mkdir(parents=True)
        (nested / 'compose.yaml').write_text('services: {}')
        self.assertEqual([], stack.discover(source, max_depth=2))

    def test_organize_copies_without_overwriting(self):
        source = Path(self.tmp.name) / 'source'; source.mkdir()
        project = source / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        with mock.patch.object(stack, 'confirm', return_value=True):
            stack.organize(str(source))
        self.assertTrue((stack.ROOT / 'demo' / 'compose.yaml').is_file())
        self.assertTrue(project.is_dir())

    def test_organize_skips_existing_destination(self):
        source = Path(self.tmp.name) / 'source'; source.mkdir()
        project = source / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        target = stack.ROOT / 'demo'; target.mkdir()
        with mock.patch('builtins.input', return_value='y'):
            stack.organize(str(source))
        self.assertFalse((target / 'compose.yaml').exists())

    def test_remove_requires_interactive_terminal(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        with mock.patch.object(stack.sys.stdin, 'isatty', return_value=False), mock.patch.object(stack, 'run') as run:
            with self.assertRaises(SystemExit): stack.remove('demo')
        self.assertTrue(project.exists())
        run.assert_not_called()

    def test_remove_requires_exact_name_before_down(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        config = mock.Mock(returncode=0, stdout='{"name":"demo"}')
        labels = mock.Mock(returncode=0, stdout='')
        with mock.patch.object(stack.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', return_value='wrong'), mock.patch.object(stack, 'run', side_effect=[config, labels]) as run:
            stack.remove('demo')
        self.assertTrue(project.exists())
        self.assertEqual(run.call_count, 2)

    def test_remove_archives_files_without_down_volumes(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        (project / 'data').write_text('keep me')
        config = mock.Mock(returncode=0, stdout='{"name":"actual"}')
        labels = mock.Mock(returncode=0, stdout=str(project.resolve()) + '\n')
        with mock.patch.object(stack.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=['demo', 'y']), mock.patch.object(stack, 'run', side_effect=[config, labels, mock.Mock(returncode=0)]) as run:
            stack.remove('demo')
        self.assertEqual(run.call_args.args[0][-3:], ['-p', 'actual', 'down'])
        self.assertFalse(project.exists())
        archived, = (stack.ROOT / '.removed').glob('*/demo/data')
        self.assertEqual(archived.read_text(), 'keep me')

    def test_backup_creates_archive_without_docker(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        (project / 'data.txt').write_text('keep')
        output = Path(self.tmp.name) / 'backup.tar.gz'
        stack.backup('demo', str(output))
        self.assertTrue(output.is_file())
        with tarfile.open(output) as archive:
            self.assertIn('demo/compose.yaml', archive.getnames())

    def test_backup_refuses_overwrite(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        output = Path(self.tmp.name) / 'backup.tar.gz'; output.write_text('existing')
        with self.assertRaises(SystemExit): stack.backup('demo', str(output))

    def test_self_update_preserves_original_on_invalid_python(self):
        target = stack.ROOT / 'stack.py'; target.write_text('original')
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'#!/usr/bin/env python3\nVERSION = "9.0.0"\ndef broken(\n'
        with mock.patch.object(stack, '__file__', str(target)), mock.patch.object(stack, 'confirm', return_value=True), mock.patch.object(stack, 'urlopen', return_value=response):
            with self.assertRaises(SystemExit): stack.self_update()
        self.assertEqual(target.read_text(), 'original')

    def test_remove_data_requires_delete_data_phrase(self):
        project = stack.ROOT / 'demo'; project.mkdir()
        (project / 'compose.yaml').write_text('services: {}')
        answers = iter(['demo', 'y', 'demo', 'NO'])
        config = type('Result', (), {'returncode': 0, 'stdout': '{"name":"demo"}'})()
        labels = type('Result', (), {'returncode': 0, 'stdout': str(project.resolve()) + '\n'})()
        with mock.patch.object(stack.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', side_effect=answers), mock.patch.object(stack, 'run', side_effect=[config, labels]) as run:
            stack.remove('demo', data=True)
        self.assertTrue(project.exists())
        self.assertEqual(run.call_count, 2)

if __name__ == '__main__': unittest.main()
