from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from . import __version__
from .i18n import tr
from .network import TLS_CONTEXT

logger = logging.getLogger(__name__)

FREE_API = "https://api-free.deepl.com/v2/translate"
PRO_API = "https://api.deepl.com/v2/translate"

TARGET_LANGUAGES = (
    ("", "Do not translate"),
    ("EN-GB", "English (British)"),
    ("EN-US", "English (American)"),
    ("AR", "Arabic"), ("BG", "Bulgarian"), ("CS", "Czech"),
    ("DA", "Danish"), ("DE", "German"), ("EL", "Greek"),
    ("ES", "Spanish"), ("ET", "Estonian"), ("FI", "Finnish"),
    ("FR", "French"), ("HU", "Hungarian"), ("ID", "Indonesian"),
    ("IT", "Italian"), ("JA", "Japanese"), ("KO", "Korean"),
    ("LT", "Lithuanian"), ("LV", "Latvian"), ("NB", "Norwegian"),
    ("NL", "Dutch"), ("PL", "Polish"), ("PT-BR", "Portuguese (Brazilian)"),
    ("PT-PT", "Portuguese"),
    ("RO", "Romanian"),
    ("RU", "Russian"),
    ("SK", "Slovak"), ("SL", "Slovenian"), ("SV", "Swedish"),
    ("TR", "Turkish"), ("UK", "Ukrainian"), ("ZH-HANS", "Chinese (simplified)"),
    ("ZH-HANT", "Chinese (traditional)"),
)


class DeepLError(RuntimeError):
    pass


class DeepLClient:
    def __init__(self, api_key: str = "", target_language: str = "") -> None:
        self.api_key = api_key.strip()
        self.target_language = target_language.strip().upper()

    def translate(self, text: str) -> str:
        if not self.api_key:
            raise DeepLError(tr("Enter a DeepL API key in preferences first."))
        if not self.target_language:
            raise DeepLError(
                tr("Choose a lyrics translation language in preferences first.")
            )
        request = urllib.request.Request(
            FREE_API if self.api_key.endswith(":fx") else PRO_API,
            data=json.dumps({
                "text": [text],
                "target_lang": self.target_language,
                "preserve_formatting": True,
            }).encode("utf-8"),
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"BlindSpot/{__version__}",
            },
            method="POST",
        )
        try:
            logger.debug(
                "DeepL request endpoint=%s target=%s characters=%d",
                "free" if self.api_key.endswith(":fx") else "pro",
                self.target_language,
                len(text),
            )
            with urllib.request.urlopen(
                request,
                timeout=30,
                context=TLS_CONTEXT,
            ) as response:
                value = json.loads(response.read().decode("utf-8"))
            return str(value["translations"][0]["text"]).strip()
        except urllib.error.HTTPError as error:
            logger.warning(
                "DeepL HTTP error status=%d endpoint=%s target=%s",
                error.code,
                "free" if self.api_key.endswith(":fx") else "pro",
                self.target_language,
            )
            if error.code == 403:
                message = tr("DeepL rejected the API key.")
            elif error.code == 456:
                message = tr("The DeepL translation quota has been reached.")
            else:
                message = tr("DeepL returned error {status}.").format(
                    status=error.code
                )
            raise DeepLError(message) from error
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise DeepLError(tr("Lyrics translation failed.")) from error
