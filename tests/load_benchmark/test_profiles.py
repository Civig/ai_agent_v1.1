import unittest

from tests.load_benchmark.profiles import EXPECTED_PROFILE_NAMES, get_profile, load_profiles


class LoadBenchmarkProfilesTests(unittest.TestCase):
    def test_profiles_json_contains_expected_profile_set(self):
        profiles = load_profiles()

        self.assertEqual(tuple(profiles.keys()), EXPECTED_PROFILE_NAMES)
        self.assertEqual(profiles["20"].concurrency, 20)
        self.assertEqual(profiles["50"].recommended_mode, "multi-session")

    def test_get_profile_returns_exact_named_profile(self):
        profile = get_profile("10")

        self.assertEqual(profile.name, "10")
        self.assertEqual(profile.default_ramp_up_seconds, 10)


if __name__ == "__main__":
    unittest.main()
