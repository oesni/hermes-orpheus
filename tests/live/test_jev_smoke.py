"""Offline checks for the explicit live decision probe (no API requests)."""
import tempfile
import unittest
from pathlib import Path
from orpheus.config import Registry
from tests.live.jev_smoke import CASES, KEY, config, credential


class JevSmokeTests(unittest.TestCase):
    def parse(self, text, key_name=KEY):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.env'
            path.write_text(text)
            return credential(path, key_name)

    def test_literal_key_and_comment(self):
        self.assertEqual(self.parse(f'{KEY}=fake-test-token # comment\nOTHER=ignored'), 'fake-test-token')
        self.assertEqual(self.parse(f'export {KEY}="fake-test-token"'), 'fake-test-token')

    def test_custom_variable_name(self):
        self.assertEqual(self.parse('CUSTOM_TOKEN=fake-test-token', 'CUSTOM_TOKEN'), 'fake-test-token')

    def test_duplicate_missing_and_whitespace_rejected(self):
        for text in ('OTHER=ignored', f'{KEY}=\n', f'{KEY}=a\n{KEY}=b', f'{KEY}=a b'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_fixture_admitted_and_both_stages_use_jev(self):
        registry = Registry.from_dict(config())
        self.assertFalse(registry.unavailable_policies)
        self.assertFalse(registry.quarantined)
        self.assertEqual(set(registry.presets), {'reviewer', 'writer'})
        policy = registry.policies['jev-smoke']
        for stage in ('preset_selector', 'field_resolver'):
            self.assertEqual(policy[stage]['kind'], 'systemone')
        for _, task, _, _ in CASES:
            self.assertNotIn('choose', task.lower())
            self.assertNotIn('effort', task.lower())
