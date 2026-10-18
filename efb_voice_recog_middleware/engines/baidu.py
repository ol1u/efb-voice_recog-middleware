import threading
import time
from io import BytesIO
from typing import Dict

import pydub
import requests

from . import SpeechEngine


class BaiduSpeech(SpeechEngine):
    engine_name: str = "Baidu"
    TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
    API_URL = "https://vop.baidu.com/server_api"
    TOKEN_EXPIRY_GRACE_SECONDS = 60
    lang_list = [
        'zh', 'en', 'zh-yue', 'zh-x-en',
        'zh-x-sichuan', 'zh-x-farfield']

    languages = {
        "zh": 1537,
        "zh-x-en": 1536,
        "en": 1737,
        "ct": 1637,  # for compatibility
        "zh-yue": 1637,
        "zh-x-sichuan": 1837,
        "zh-x-farfield": 1936
    }

    def __init__(self, key_dict: Dict[str, str], timeout: float = 20):
        self.key_dict = key_dict
        self.lang = key_dict.get('lang', 'zh')
        self.timeout = timeout
        self._token_lock = threading.Lock()
        self._access_token = None
        self._token_expires_at = 0

    def _refresh_token(self):
        data = {
            "grant_type": "client_credentials",
            "client_id": self.key_dict['api_key'],
            "client_secret": self.key_dict['secret_key']
        }
        response = requests.post(
            self.TOKEN_URL,
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError(
                "Baidu token request failed: {}".format(
                    token_data.get("error_description")
                    or token_data.get("error")
                    or "missing access_token"
                )
            )
        try:
            expires_in = float(token_data.get("expires_in", 2592000))
        except (TypeError, ValueError):
            expires_in = 2592000
        self._access_token = access_token
        self._token_expires_at = (
            time.monotonic()
            + max(0, expires_in - self.TOKEN_EXPIRY_GRACE_SECONDS)
        )

    def _get_token(self):
        if (
            self._access_token
            and time.monotonic() < self._token_expires_at
        ):
            return self._access_token
        with self._token_lock:
            if (
                not self._access_token
                or time.monotonic() >= self._token_expires_at
            ):
                self._refresh_token()
            return self._access_token

    def recognize(self, file, lang=""):
        if not lang:
            lang = self.lang
        if hasattr(file, 'read'):
            pass
        elif not isinstance(file, str):
            return [
                "ERROR!",
                "File must be a path string or a file object in `rb` mode."
            ]
        if lang.lower() not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        audio = pydub.AudioSegment.from_file(
            file).set_frame_rate(16000).set_channels(1)
        with BytesIO() as f:
            audio.export(f, format="s16le", codec="pcm_s16le")
            headers = {
                "Content-Type": "audio/pcm;rate=16000"
            }
            params = {
                "cuid": "catbaron.voice_recog",
                "token": self._get_token(),
                "dev_pid": self.languages[lang],
            }
            r = requests.post(
                self.API_URL,
                params=params,
                headers=headers,
                data=f,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return ["ERROR!", r.status_code, r.content]
            rjson = r.json()
            if rjson['err_no'] == 0:
                return rjson['result']
            else:
                return ["ERROR!", rjson['err_msg']]
