import unittest

from tests.load_benchmark.run_benchmark import build_parser, parse_args


class LoadBenchmarkCLITests(unittest.TestCase):
    def test_parser_accepts_shared_session_contract(self):
        args = parse_args(
            [
                "--host",
                "https://127.0.0.1",
                "--profile",
                "20",
                "--output-dir",
                "/tmp/bench",
                "--mode",
                "shared-session",
                "--username",
                "aitest",
                "--password",
                "secret",
            ]
        )

        self.assertEqual(args.profile, "20")
        self.assertEqual(args.mode, "shared-session")

    def test_parser_requires_user_file_for_multi_session_mode(self):
        with self.assertRaises(SystemExit):
            parse_args(
                [
                    "--host",
                    "https://127.0.0.1",
                    "--profile",
                    "50",
                    "--output-dir",
                    "/tmp/bench",
                    "--mode",
                    "multi-session",
                ]
            )


if __name__ == "__main__":
    unittest.main()
