from __future__ import annotations

import ssl
import unittest
from pathlib import Path

import certifi

from blindspot.network import TLS_CONTEXT


class NetworkTests(unittest.TestCase):
    def test_bundled_certificate_store_is_used_for_https(self) -> None:
        certificate_store = Path(certifi.where())

        self.assertTrue(certificate_store.is_file())
        self.assertGreater(certificate_store.stat().st_size, 100_000)
        self.assertEqual(TLS_CONTEXT.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(TLS_CONTEXT.check_hostname)


if __name__ == "__main__":
    unittest.main()
