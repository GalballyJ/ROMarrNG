import os
import unittest
from unittest.mock import patch

from scripts import check_stable_image_tags


class LatestReleaseVersionTests(unittest.TestCase):
    @patch.dict(os.environ, {"GH_TOKEN": "test-token", "GITHUB_TOKEN": ""}, clear=True)
    @patch("scripts.check_stable_image_tags.https_request")
    def test_latest_release_uses_available_github_token(self, request):
        request.return_value = (200, None, b'{"tag_name":"v0.14.11"}')

        version = check_stable_image_tags.latest_release_version()

        self.assertEqual(version, "0.14.11")
        self.assertEqual(
            request.call_args.args[2]["Authorization"], "Bearer test-token"
        )

    @patch.dict(os.environ, {}, clear=True)
    @patch("scripts.check_stable_image_tags.https_request")
    def test_latest_release_keeps_anonymous_fallback(self, request):
        request.return_value = (200, None, b'{"tag_name":"v0.14.11"}')

        version = check_stable_image_tags.latest_release_version()

        self.assertEqual(version, "0.14.11")
        self.assertNotIn("Authorization", request.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
