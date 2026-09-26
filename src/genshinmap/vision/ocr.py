"""Распознавание текста на экране встроенным OCR Windows (Windows.Media.Ocr).

Без тяжёлых моделей: движок входит в Windows, нужен только языковой пакет
(русский установлен). Используем для плашек подбора («Мора ×120» и т.п.).
"""
from __future__ import annotations

import asyncio

import cv2
import numpy as np

try:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    _HAS_OCR = True
except Exception:  # noqa: BLE001 — не Windows / нет пакетов winrt
    _HAS_OCR = False


class ScreenOcr:
    def __init__(self, lang: str = "ru") -> None:
        self.engine = None
        if _HAS_OCR:
            try:
                self.engine = OcrEngine.try_create_from_language(Language(lang))
            except Exception:  # noqa: BLE001
                self.engine = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def ready(self) -> bool:
        return self.engine is not None

    def read(self, img_bgr: np.ndarray, upscale: float = 1.5) -> list[str]:
        """Строки текста в кадре (сверху вниз). Вызывать из одного потока."""
        if not self.ready or img_bgr.size == 0:
            return []
        if upscale != 1.0:          # мелкий игровой шрифт OCR читает лучше крупнее
            img_bgr = cv2.resize(img_bgr, None, fx=upscale, fy=upscale,
                                 interpolation=cv2.INTER_CUBIC)
        bgra = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
        h, w = bgra.shape[:2]
        writer = DataWriter()
        writer.write_bytes(bytes(bgra.tobytes()))
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        result = self._loop.run_until_complete(self.engine.recognize_async(bitmap))
        return [line.text for line in result.lines]
