import unittest

from llm_gateway import (
    JOB_KIND_FILE_CHAT,
    JOB_STATUS_CANCELLED,
    WORKLOAD_CHAT,
    classify_observability_error,
    compute_queue_wait_ms,
    compute_total_job_ms,
    extract_job_observability_fields,
)


class ObservabilityBaselineTests(unittest.TestCase):
    def test_compute_queue_wait_ms_uses_enqueued_and_started_timestamps(self):
        job = {"enqueued_at_ms": 1_000, "started_at_ms": 1_450}
        self.assertEqual(compute_queue_wait_ms(job), 450)

    def test_compute_total_job_ms_uses_created_and_finished_timestamps(self):
        job = {"created_at_ms": 2_000, "finished_at_ms": 3_250}
        self.assertEqual(compute_total_job_ms(job), 1_250)

    def test_extract_job_observability_fields_returns_safe_context(self):
        fields = extract_job_observability_fields(
            {
                "id": "job-123",
                "username": "alice",
                "job_kind": JOB_KIND_FILE_CHAT,
                "workload_class": WORKLOAD_CHAT,
                "target_kind": "gpu",
                "model_key": "gemma2:2b",
                "model_name": "gemma2:2b",
                "prompt": "hello",
                "history": [{"role": "user", "content": "hi"}],
                "file_chat": {"files": [{"name": "a.txt"}, {"name": "b.pdf"}]},
            }
        )

        self.assertEqual(fields["job_id"], "job-123")
        self.assertEqual(fields["username"], "alice")
        self.assertEqual(fields["job_kind"], JOB_KIND_FILE_CHAT)
        self.assertEqual(fields["workload_class"], WORKLOAD_CHAT)
        self.assertEqual(fields["target_kind"], "gpu")
        self.assertEqual(fields["model_key"], "gemma2:2b")
        self.assertEqual(fields["file_count"], 2)
        self.assertEqual(fields["prompt_chars"], 5)
        self.assertEqual(fields["history_messages"], 1)

    def test_classify_observability_error_maps_validation_and_parse_errors(self):
        self.assertEqual(
            classify_observability_error("Поддерживаются только TXT, PDF, DOCX, PNG, JPG и JPEG."),
            "validation_error",
        )
        self.assertEqual(
            classify_observability_error("PDF parser unavailable on server"),
            "parse_error",
        )

    def test_classify_observability_error_maps_timeout_and_cancelled(self):
        self.assertEqual(
            classify_observability_error("Deadline exceeded", phase="queue"),
            "queue_timeout",
        )
        self.assertEqual(
            classify_observability_error("timeout", phase="inference"),
            "inference_timeout",
        )
        self.assertEqual(
            classify_observability_error("cancelled", terminal_status=JOB_STATUS_CANCELLED),
            "cancelled",
        )


if __name__ == "__main__":
    unittest.main()
