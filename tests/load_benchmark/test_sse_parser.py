import unittest

from tests.load_benchmark.sse_parser import iter_sse_events, summarize_sse_events


class LoadBenchmarkSSEParserTests(unittest.TestCase):
    def test_parser_reads_job_id_tokens_and_done(self):
        lines = [
            'data: {"job_id":"job-1"}',
            "",
            'data: {"token":"O"}',
            "",
            'data: {"token":"K"}',
            "",
            'data: {"done":true}',
            "",
        ]

        summary = summarize_sse_events(iter_sse_events(lines))

        self.assertEqual(summary.job_id, "job-1")
        self.assertTrue(summary.completed)
        self.assertEqual(summary.final_text, "OK")
        self.assertFalse(summary.incomplete)

    def test_parser_marks_incomplete_stream_without_done(self):
        lines = [
            'data: {"job_id":"job-2"}',
            "",
            'data: {"token":"partial"}',
            "",
        ]

        summary = summarize_sse_events(iter_sse_events(lines))

        self.assertFalse(summary.completed)
        self.assertTrue(summary.incomplete)
        self.assertEqual(summary.final_text, "partial")


if __name__ == "__main__":
    unittest.main()
