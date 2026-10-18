import io
import unittest
from unittest.mock import patch

from ehforwarderbot import MsgType

from efb_voice_recog_middleware import VoiceRecogMiddleware
from efb_voice_recog_middleware.engines.baidu import BaiduSpeech


class FakeMaster:
    pass


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.content = b""
        self.text = ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class FakeEngine:
    engine_name = "Fake"
    lang = "zh"

    def __init__(self):
        self.calls = 0

    def recognize(self, file):
        self.calls += 1
        return ["识别结果。"]


class EmptyEngine(FakeEngine):
    def recognize(self, file):
        self.calls += 1
        return []


class ErrorEngine(FakeEngine):
    def recognize(self, file):
        self.calls += 1
        return ["ERROR!", "Invalid language."]


class FakeMessage:
    def __init__(self, audio):
        self.type = MsgType.Voice
        self.text = ""
        self.mime = "audio/ogg"
        self.file = io.BytesIO(audio)
        self.deliver_to = FakeMaster()


def build_middleware(engine):
    middleware = VoiceRecogMiddleware.__new__(VoiceRecogMiddleware)
    middleware.voice_engines = [engine]
    return middleware


class MiddlewareTests(unittest.TestCase):
    def test_enabled_flag_keeps_existing_configs_compatible(self):
        self.assertTrue(
            VoiceRecogMiddleware._enabled({"azure": {}}, "azure")
        )
        self.assertFalse(
            VoiceRecogMiddleware._enabled(
                {"azure": {"enabled": False}},
                "azure",
            )
        )
        self.assertFalse(
            VoiceRecogMiddleware._enabled({}, "azure")
        )

    def test_timeout_precedence(self):
        self.assertEqual(
            VoiceRecogMiddleware._timeout_from_config("15", 20),
            15,
        )
        self.assertEqual(
            VoiceRecogMiddleware._timeout_from_config(None, 20),
            20,
        )
        self.assertEqual(
            VoiceRecogMiddleware._timeout_from_config(0, 20),
            20,
        )
        self.assertEqual(
            VoiceRecogMiddleware._timeout_from_config(True, 20),
            20,
        )

    def test_single_engine_keeps_original_output(self):
        middleware = build_middleware(FakeEngine())
        self.assertEqual(middleware.recognize("voice.ogg"), ["识别结果"])

    def test_recognition_uses_fresh_temp_file(self):
        engine = FakeEngine()
        message = FakeMessage(b"voice")
        middleware = build_middleware(engine)

        with patch.object(
            VoiceRecogMiddleware,
            "sent_by_master",
            staticmethod(lambda message: False),
        ):
            result = middleware.process_message(message)

        self.assertIs(result, message)
        self.assertEqual(message.text, "识别结果")
        self.assertEqual(engine.calls, 1)

    def test_empty_engine_result_does_not_add_noise(self):
        engine = EmptyEngine()
        middleware = build_middleware(engine)
        self.assertEqual(middleware.recognize("voice.ogg"), [])

    def test_engine_error_result_is_not_presented_as_text(self):
        engine = ErrorEngine()
        middleware = build_middleware(engine)
        result = middleware.recognize("voice.ogg")

        self.assertEqual(result, ["Fake (zh): 识别失败"])
        self.assertNotIn("Invalid language.", repr(result))

    def test_baidu_token_is_refreshed_after_expiry(self):
        engine = BaiduSpeech(
            {
                "api_key": "key",
                "secret_key": "secret",
                "lang": "zh",
            },
            timeout=1,
        )
        responses = [
            FakeResponse(
                {
                    "access_token": "first",
                    "expires_in": 0,
                }
            ),
            FakeResponse(
                {
                    "access_token": "second",
                    "expires_in": 3600,
                }
            ),
        ]
        with patch(
            "efb_voice_recog_middleware.engines.baidu.requests.post",
            side_effect=responses,
        ) as post:
            self.assertEqual(engine._get_token(), "first")
            self.assertEqual(engine._get_token(), "second")

        self.assertEqual(post.call_count, 2)
        self.assertNotIn("first", repr(engine.__dict__))

    def test_baidu_token_is_shared_within_instance(self):
        engine = BaiduSpeech(
            {
                "api_key": "key",
                "secret_key": "secret",
                "lang": "zh",
            },
            timeout=1,
        )
        response = FakeResponse(
            {
                "access_token": "token",
                "expires_in": 3600,
            }
        )
        with patch(
            "efb_voice_recog_middleware.engines.baidu.requests.post",
            return_value=response,
        ) as post:
            self.assertEqual(engine._get_token(), "token")
            self.assertEqual(engine._get_token(), "token")

        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
