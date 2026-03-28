import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UploadFrontendContractTests(unittest.TestCase):
    def test_template_exposes_attachment_controls(self):
        template = (ROOT / "templates" / "chat.html").read_text(encoding="utf-8")
        self.assertIn('id="attachmentInput"', template)
        self.assertIn('id="attachmentList"', template)
        self.assertIn('id="attachBtn"', template)

    def test_frontend_keeps_sse_fallback_and_file_endpoint(self):
        source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('"/api/chat_with_files"', source)
        self.assertIn("this.streamController.start({", source)
        self.assertIn("const hasAttachments = attachments.length > 0;", source)
        self.assertIn("sendMessageWithFiles", source)
        self.assertIn("setUploadingDocuments(hasAttachments)", source)

    def test_frontend_attachment_store_deduplicates_files(self):
        source = (ROOT / "static" / "js" / "chat-store.js").read_text(encoding="utf-8")
        self.assertIn("attachment.name === file.name", source)
        self.assertIn("attachment.size === file.size", source)
        self.assertIn("attachment.lastModified === file.lastModified", source)


if __name__ == "__main__":
    unittest.main()
