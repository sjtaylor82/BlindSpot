from __future__ import annotations

import ssl

import certifi


TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
