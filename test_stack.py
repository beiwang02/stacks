import os, tempfile, unittest
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

if __name__ == '__main__': unittest.main()
