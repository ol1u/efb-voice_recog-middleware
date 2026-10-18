# coding: utf-8
import logging
import mimetypes
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional
from os import PathLike
from pathlib import Path

import yaml

from ehforwarderbot import coordinator, Middleware, Message, MsgType
from ehforwarderbot.utils import get_config_path
from . import __version__ as version
from .engines.baidu import BaiduSpeech
from .engines.azure import AzureSpeech
from .engines.iflytek import IFlyTekSpeech
from .engines.tencent import TencentSpeech


class VoiceRecogMiddleware(Middleware):
    """
    Middleware - Voice recognize middleware
    Convert voice mesage to text message.
    Author: Catbaron <https://github.com/catbaron>,
            Eana Hufwe <https://1a23.com>
    """

    middleware_id: str = "catbaron.voice_recog"
    middleware_name: str = "Voice Recognition Middleware"
    __version__ = version.__version__
    logger: logging.Logger = logging.getLogger(
        "plugins.%s.VoiceRecogMiddleware" % middleware_id)

    REQUEST_TIMEOUT = 20

    def __init__(self, instance_id: str = None):
        Middleware.__init__(self, instance_id)
        self.config: Dict[str, Any] = self.load_config()
        self.voice_engines: List = []
        engines = self.config.get("speech_api", {})
        for name, engine_config in engines.items():
            if not isinstance(engine_config, dict):
                raise RuntimeError(
                    'Configuration for "{}" must be a mapping.'.format(name)
                )

        self.request_timeout = self._timeout_from_config(
            self.config.get("request_timeout"),
            self.REQUEST_TIMEOUT,
        )

        if self._enabled(engines, "baidu"):
            self.voice_engines.append(
                BaiduSpeech(
                    engines["baidu"],
                    timeout=self._engine_timeout(engines, "baidu"),
                )
            )
        if self._enabled(engines, "azure"):
            self.voice_engines.append(
                AzureSpeech(
                    engines["azure"],
                    timeout=self._engine_timeout(engines, "azure"),
                )
            )
        if self._enabled(engines, "iflytek"):
            self.voice_engines.append(
                IFlyTekSpeech(
                    engines["iflytek"],
                    timeout=self._engine_timeout(engines, "iflytek"),
                )
            )
        if self._enabled(engines, "tencent"):
            self.voice_engines.append(
                TencentSpeech(
                    engines["tencent"],
                    timeout=self._engine_timeout(engines, "tencent"),
                )
            )

    @staticmethod
    def _enabled(engines: Dict[str, Any], name: str) -> bool:
        config = engines.get(name)
        return (
            isinstance(config, dict)
            and config.get("enabled", True) is not False
        )

    @staticmethod
    def _timeout_from_config(value: Any, default: float) -> float:
        if isinstance(value, bool):
            return default
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return default
        return timeout if timeout > 0 else default

    def _engine_timeout(self, engines: Dict[str, Any], name: str) -> float:
        return self._timeout_from_config(
            engines[name].get("request_timeout"),
            self.request_timeout,
        )

    def load_config(self) -> Dict[str, Any]:
        config_path: Path = get_config_path(self.middleware_id)
        if not config_path.exists():
            raise FileNotFoundError("The configure file does not exist!")
        with config_path.open("r") as f:
            data = yaml.load(f, Loader=yaml.SafeLoader)
            if not isinstance(data, dict) or not data:
                raise RuntimeError("Load configure file failed!")
            if not isinstance(data.get("speech_api"), dict):
                raise RuntimeError('"speech_api" must be a mapping.')
            return data

    def recognize(self, file: PathLike) -> List[str]:
        """
        Recognize the audio file to text.
        :param file: An audio file. It should be FILE object in 'rb'
            mode or string of path to the audio file.
        """
        if not self.voice_engines:
            return []

        with ThreadPoolExecutor(max_workers=len(self.voice_engines)) as exe:
            futures = {
                exe.submit(e.recognize, file): (e.engine_name, e.lang)
                for e in self.voice_engines
            }
            results = []
            for future in as_completed(futures):
                engine_name, lang = futures[future]
                try:
                    parts = future.result()
                    if not parts:
                        continue
                    data = "; ".join(str(part) for part in parts)
                    # Cloud engines report expected errors as list results
                    # rather than exceptions. Keep that detail in logs without
                    # leaking it into the chat text.
                    if parts[0] == "ERROR!":
                        if data:
                            self.logger.warning(
                                "Voice recognition failed with %s: %s",
                                engine_name,
                                data,
                            )
                        raise RuntimeError(data or "Unknown error")
                    if not data.strip():
                        continue
                    if len(data) > 1000:
                        data = data[:1000] + " ..."
                    if len(self.voice_engines) == 1:
                        results.append(data.rstrip("。"))
                    else:
                        results.append(f"{engine_name} ({lang}): {data}")
                except Exception as exc:
                    self.logger.warning(
                        "Voice recognition failed with %s: %s",
                        engine_name,
                        exc,
                    )
                    results.append(f"{engine_name} ({lang}): 识别失败")
            return results

    @staticmethod
    def sent_by_master(message: Message) -> bool:
        master = getattr(coordinator, "master", None)
        return master is not None and message.deliver_to is not master

    def process_message(self, message: Message) -> Optional[Message]:
        """
        Process a message with middleware
        Args:
            message (:obj:`.Message`): Message object to process
        Returns:
            Optional[:obj:`.Message`]: Processed message or None if discarded.
        """
        # Only process messages sent by a slave channel.
        if self.sent_by_master(message):
            return message

        if message.type != MsgType.Voice:
            return message

        if not self.voice_engines:
            return message

        audio = None
        message_file_position = None
        try:
            if not message.file:
                return message
            with suppress(OSError, ValueError):
                message_file_position = message.file.tell()

            # pydub requires a path. Copy the stream and keep this temporary
            # file alive until all recognition threads have finished.
            suffix = mimetypes.guess_extension(message.mime or "") or ""
            audio = NamedTemporaryFile(suffix=suffix)
            shutil.copyfileobj(message.file, audio)
            audio.flush()
            result_text = "\n".join(self.recognize(audio.name))
        except Exception:
            self.logger.exception(
                "Failed to prepare or recognize voice content."
            )
            result_text = "Failed to recognize voice content."
        finally:
            if audio is not None:
                audio.close()
            if message.file is not None:
                try:
                    message.file.seek(message_file_position or 0)
                except (OSError, ValueError):
                    pass

        if message.text:
            message.text = f"{message.text}\n{result_text}"
        else:
            message.text = result_text
        message.text = message.text[:4000]

        return message
