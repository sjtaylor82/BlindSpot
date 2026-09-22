import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from blindspot.deepl import DeepLClient, DeepLError, FREE_API, PRO_API


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps({"translations": [{"text": "Bonjour"}]}).encode()


class DeepLClientTests(unittest.TestCase):
    @patch("blindspot.deepl.urllib.request.urlopen", return_value=Response())
    def test_free_key_translates_and_preserves_formatting(self, urlopen):
        result = DeepLClient("secret:fx", "FR").translate("Hello\nworld")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(result, "Bonjour")
        self.assertEqual(request.full_url, FREE_API)
        self.assertEqual(body["text"], ["Hello\nworld"])
        self.assertTrue(body["preserve_formatting"])

    @patch("blindspot.deepl.urllib.request.urlopen", return_value=Response())
    def test_pro_key_uses_pro_endpoint(self, urlopen):
        DeepLClient("secret", "DE").translate("Hello")
        self.assertEqual(urlopen.call_args.args[0].full_url, PRO_API)

    @patch("blindspot.deepl.urllib.request.urlopen")
    def test_quota_error_is_explained(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            FREE_API, 456, "quota", {}, io.BytesIO()
        )
        with self.assertRaisesRegex(DeepLError, "quota"):
            DeepLClient("secret:fx", "FR").translate("Hello")
