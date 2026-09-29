"""Фоновое отслеживание позиции игрока по мини-карте.

Работает в отдельном потоке: глобальный поиск по карте занимает секунды, и в
GUI-потоке он подвешивал бы окно. Наружу — сигналы Qt (доставляются в главный
поток автоматически).

Цикл: скриншот области мини-карты -> PositionTracker.locate -> сигнал
`position`. Пока игрок отслеживается, каждый шаг — локальный поиск (мс).
При смене карты референс собирается/подгружается в этом же потоке.
"""
from __future__ import annotations

import concurrent.futures as cf
import math
import re
import threading
import time
from pathlib import Path

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from genshinmap.backend.game.process_watcher import (
    game_window_rect,
    is_genshin_foreground,
    is_genshin_running,
)
from genshinmap.backend.vision.debug_recorder import DebugRecorder
from genshinmap.backend.vision.layout import ANCHORS, ui_scale
from genshinmap.backend.vision.layout import region_from_frac as _layout_region
from genshinmap.backend.vision.minimap_check import MinimapCheck
from genshinmap.backend.vision.position_tracker import (
    Position,
    PositionTracker,
    ensure_reference,
    ensure_water_reference,
    reference_path,
    water_reference_path,
)
from genshinmap.backend.vision.prompt_detector import PromptDetector, parse_prompt_lines

# Прыжок позиции дальше JUMP_UNITS от недавней (за JUMP_MEMORY_S) принимаем только
# после JUMP_CONFIRM подряд совпадающих (в пределах JUMP_AGREE) результатов.
UID_FRAC = {"left": 0.84, "top": 0.955, "width": 0.16, "height": 0.045}
UID_EVERY_S = 30.0
JUMP_UNITS = 150
JUMP_MEMORY_S = 30.0
JUMP_CONFIRM = 3
JUMP_AGREE = 40
SLOW_RESULT_MAX_AGE = 15.0   # результат фонового поиска по кадру старше — не используем


def region_from_frac(frac: dict, rect: dict, key: str = "minimap") -> dict[str, int]:
    """Доли эталонной раскладки -> пиксельная область в окне игры rect
    (привязка к краю — по виду элемента, см. layout.ANCHORS)."""
    return _layout_region(frac, rect, ANCHORS.get(key, "lt"))


def classify_scene(gray: np.ndarray) -> str:
    """Уменьшенный серый кадр игры без мини-карты -> loading | cutscene | menu."""
    g = gray.astype(np.float32)
    if g.std() < 7:
        return "loading"                    # однотонный экран (чёрный/белый)
    h = g.shape[0]
    top, bot, mid = g[: int(h * 0.09)], g[int(h * 0.91):], g[int(h * 0.2): int(h * 0.8)]
    if max(top.mean(), bot.mean()) < 14 and max(top.std(), bot.std()) < 8 and mid.mean() > 25:
        return "cutscene"                   # чёрные полосы сверху и снизу
    return "menu"


def game_rect(sct) -> dict:
    """Окно игры на экране; нет окна — первый монитор (как раньше)."""
    return game_window_rect() or sct.monitors[1]


def ui_height(rect: dict) -> float:
    """Высота «эталонного» экрана в пикселях окна: мини-карта масштабируется по ней."""
    return 1080.0 * ui_scale(rect["width"], rect["height"])


def ocr_upscale(ui_s: float) -> float:
    """Мелкий шрифт (окно меньше 1080p) OCR читает хуже — увеличиваем сильнее."""
    return 1.5 / min(1.0, max(0.5, ui_s))


class PositionService(QObject):
    position = pyqtSignal(object)     # Position (надёжная)
    lost = pyqtSignal()               # позицию потеряли (телепорт, меню, загрузка)
    status = pyqtSignal(str)          # человекочитаемый статус для панели
    scaleCalibrated = pyqtSignal(int, float)   # map_id, масштаб мини-карты
    runningChanged = pyqtSignal(bool)
    prompts = pyqtSignal(object)      # {вид подсказки: уверенность} — каждый шаг
    icons = pyqtSignal(object)        # {point_id: 0..1} значки на мини-карте
    pickupText = pyqtSignal(object)   # строки OCR из области плашки подбора
    uidSeen = pyqtSignal(str)         # UID аккаунта (правый нижний угол игры)
    # что сейчас в игре: ok | unknown_area | loading | cutscene | menu | background | no_game
    scene = pyqtSignal(str)

    def __init__(self, interval_s: float = 0.4, require_game: bool = True) -> None:
        super().__init__()
        self.interval_s = interval_s
        self.require_game = require_game
        self.minimap_frac: dict = {}
        self.pickup_frac: dict | None = None
        self.recorder: DebugRecorder | None = None   # запись кадров для отладки
        self.prompt_frac: dict | None = None
        self.prompt_detector: PromptDetector | None = None
        self.watch: list[tuple[str, float, float]] = []   # точки, где смотреть значок
        self.read_pickup = False      # читать плашку подбора (игрок у несобранного сундука)
        self.read_prompts = False     # читать подсказки взаимодействия (игрок у сундука)
        self.game_lang = "ru"         # язык текста в игре (OCR)
        self._ocr = None              # ScreenOcr создаётся в потоке сервиса
        self._lock = threading.Lock()       # доступ к трекеру (поток сервиса + калибровка)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tracker: PositionTracker | None = None
        self._pending_map: tuple[int, dict, Path, float | None] | None = None
        self._map_id: int | None = None
        self._latest: Position | None = None
        self._latest_t = 0.0
        self.minimap_px: dict | None = None     # где мини-карта на экране (для HUD)
        self.minimap_visible = False            # видна ли сейчас мини-карта игры
        self.anchors: list[tuple[float, float]] = []   # телепорты/статуи (поиск после ТП)
        # медленный поиск (секунды) — в отдельном потоке: чтение «Получено» и подсказок
        # сундуков в это время продолжает работать
        self._slow_pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pos-slow")
        self._slow: tuple[cf.Future, float, PositionTracker] | None = None
        from genshinmap.backend.core.paths import PROJECT_ROOT

        self._minimap_check = MinimapCheck(PROJECT_ROOT / "assets" / "ui")
        self.ui_s = 1.0                         # пикселей окна на пиксель раскладки 1080p

    # ---------- управление ----------
    def set_map(self, map_id: int, meta: dict, assets_dir: Path, scale: float | None) -> None:
        """Сменить карту (трекер пересоберётся в фоновом потоке при следующем шаге)."""
        with self._lock:
            self._pending_map = (map_id, meta, assets_dir, scale)
            self._tracker = None
            self._latest = None

    def start(self) -> None:
        if self.running:
            return
        # свой флаг остановки на каждый запуск: старый поток (если ещё досчитывает
        # глобальный поиск) не «оживёт» от нового start()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        name="position", daemon=True)
        self._thread.start()
        self.runningChanged.emit(True)

    def stop(self) -> None:
        self._stop.set()
        self._thread = None
        self.runningChanged.emit(False)
        self.status.emit("Отслеживание выключено")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def latest(self, max_age: float = 2.5) -> Position | None:
        """Последняя надёжная позиция, если она свежая."""
        if self._latest and time.monotonic() - self._latest_t <= max_age:
            return self._latest
        return None

    # ---------- разовый поиск (для окна калибровки) ----------
    def ensure_tracker(self) -> PositionTracker | None:
        """Собрать трекер текущей карты синхронно (вызывать не из GUI-потока)."""
        self._maybe_rebuild()
        return self._tracker

    def locate_image(self, minimap_bgr_or_gray: np.ndarray, screen_h: int,
                     scale: float | None = None) -> Position | None:
        """Найти позицию по готовому кадру мини-карты (без учёта прошлой позиции).

        Сначала с известным масштабом; если не вышло — перебор масштаба.
        """
        pos = self._locate_once(minimap_bgr_or_gray, screen_h, scale)
        if scale is not None and (pos is None or not pos.reliable):
            swept = self._locate_once(minimap_bgr_or_gray, screen_h, None)
            if swept is not None and (pos is None or swept.score > pos.score):
                pos = swept
        return pos

    def _locate_once(self, minimap_bgr_or_gray: np.ndarray, screen_h: int,
                     scale: float | None) -> Position | None:
        tr = self.ensure_tracker()
        if tr is None:
            return None
        img = minimap_bgr_or_gray
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        with self._lock:
            saved = (tr.scale, tr.last)
            tr.scale, tr.last = scale, None   # честный глобальный поиск (с калибровкой масштаба)
            try:
                return tr.locate(img, screen_h)
            finally:
                tr.scale, tr.last = saved

    # ---------- поток ----------
    def _maybe_rebuild(self) -> None:
        with self._lock:
            pending, self._pending_map = self._pending_map, None
        if pending is None:
            return
        map_id, meta, assets_dir, scale = pending
        ref = reference_path(meta, assets_dir)
        try:
            if not ref.exists():
                self.status.emit("Готовлю карту для позиции (разово)…")
                ensure_reference(meta, ref, progress=lambda d, n: self.status.emit(
                    f"Готовлю карту для позиции: {d}/{n} тайлов"))
            tracker = PositionTracker(meta, ref, scale=scale)
            tracker.set_anchors(self.anchors)
            water = water_reference_path(meta, assets_dir)
            if not water.exists():
                self.status.emit("Готовлю маску воды (разово)…")
                ensure_water_reference(meta, water, progress=lambda d, n: self.status.emit(
                    f"Готовлю маску воды: {d}/{n} тайлов"))
            tracker.set_water(water)
        except Exception as e:  # noqa: BLE001 — нет сети/битый кеш: не роняем приложение
            self.status.emit(f"Не удалось подготовить карту: {e}")
            return
        with self._lock:
            if self._pending_map is None:    # пока строили, карту не сменили
                self._tracker, self._map_id = tracker, map_id

    def _run(self, stop: threading.Event) -> None:
        sct = mss.mss()                       # mss — по экземпляру на поток
        game_checked, game_ok = 0.0, True
        fails = 0
        had_pos = False
        self.status.emit("Запуск отслеживания…")
        while not stop.is_set():
            self._maybe_rebuild()
            tr = self._tracker
            if tr is None:
                stop.wait(0.5)
                continue
            now = time.monotonic()
            if self.require_game and now - game_checked > 3.0:
                game_checked, game_ok = now, is_genshin_running()
                if not game_ok:
                    self.status.emit("Жду запуска Genshin…")
            if not game_ok:
                self._set_scene("no_game")
                stop.wait(1.0)
                continue
            try:
                mon = game_rect(sct)
                region = region_from_frac(self.minimap_frac, mon, "minimap")
                self.minimap_px, self.ui_s = region, ui_scale(mon["width"], mon["height"])
                ui_h = ui_height(mon)
                shot = np.array(sct.grab(region))
                gray = cv2.cvtColor(shot, cv2.COLOR_BGRA2GRAY)
                bgr = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
                scale_before = tr.scale
                # мини-карты нет (меню, загрузка, большая карта, окно поверх игры) —
                # позицию не ищем, текст не читаем, кадры не пишем
                visible = self._minimap_check.visible(bgr)
                self.minimap_visible = visible
                pos = None
                if visible:
                    pos = self._locate(tr, gray, ui_h, bgr)
                    self._check_prompts(sct, mon)
                    self._read_pickup(sct, mon)
                    self._record(sct, mon, shot, pos)
                else:
                    self._detect_scene(sct, mon)
                self._read_uid(sct, mon)
            except Exception as e:  # noqa: BLE001 — сбой захвата не должен ронять поток
                self.status.emit(f"Ошибка захвата: {e}")
                stop.wait(1.0)
                continue
            # эксклюзивный полноэкранный режим часто захватывается чёрным
            black = float(gray.std()) < 3.0 and float(gray.mean()) < 12.0

            if pos is not None and pos.reliable and not self._plausible(pos, tr):
                pos = None                    # далёкий прыжок без подтверждения — не верим
            if pos is not None and pos.reliable:
                fails = 0
                had_pos = True
                self._set_scene("ok")
                self._latest, self._latest_t = pos, time.monotonic()
                if scale_before is None and tr.scale is not None and self._map_id is not None:
                    self.scaleCalibrated.emit(self._map_id, float(tr.scale))
                watch = self.watch
                if watch:
                    # значки считаем ДО сигнала позиции: окно обработает их вместе
                    scores = tr.icon_presence(gray, ui_h, pos, watch)
                    self.icons.emit(scores)
                    if self.recorder and self.recorder.active and scores:
                        self.recorder.event("icons", **{f"p{k}": v for k, v in scores.items()})
                self.position.emit(pos)
                mode = "трекинг" if pos.local else "поиск"
                self.status.emit(f"📍 {pos.x:.0f}, {pos.y:.0f} · {pos.score:.0%} · {mode}")
            else:
                fails += 1
                if self.minimap_visible and fails >= 3:
                    self._set_scene("unknown_area")     # мини-карта есть, а место не узнаётся
                if fails == 3 and had_pos:
                    had_pos = False
                    self.lost.emit()
                if fails >= 3 and black:
                    self.status.emit("Захват экрана чёрный: переключи игру в оконный или "
                                     "безрамочный режим (или это экран загрузки)")
                elif fails >= 3 and not self.minimap_visible:
                    self.status.emit("Мини-карты не видно (меню, загрузка, большая карта) — жду")
                elif fails >= 3:
                    self.status.emit("Позиция не найдена (меню, загрузка или мини-карта "
                                     "вне области — проверь калибровку)")
            stop.wait(self.interval_s if fails == 0 else self.interval_s * 2)
        sct.close()

    # ---------- что сейчас в игре ----------
    def _set_scene(self, name: str) -> None:
        if name != getattr(self, "_scene", None):
            self._scene = name
            self.scene.emit(name)

    def _detect_scene(self, sct, mon: dict) -> None:
        """Мини-карты нет: загрузка, катсцена или меню/большая карта/диалог.
        Кадр окна игры разбирается только в памяти (яркость и чёрные полосы), не
        сохраняется; не чаще раза в секунду и только когда игра активна."""
        if not self._game_foreground():
            self._set_scene("background")
            return
        now = time.monotonic()
        if now - getattr(self, "_scene_t", 0.0) < 1.0:
            return
        self._scene_t = now
        frame = np.array(sct.grab(mon))[::8, ::8, :3]
        self._set_scene(classify_scene(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))

    # ---------- поиск позиции: быстро здесь, медленно — в фоне ----------
    def set_anchors(self, points: list[tuple[float, float]]) -> None:
        self.anchors = list(points)
        tr = self._tracker
        if tr is not None:
            tr.set_anchors(self.anchors)

    def _locate(self, tr: PositionTracker, gray, ui_h: float, bgr) -> Position | None:
        with self._lock:
            sq = tr.prep(gray, ui_h)
            if sq is None:
                return None
            pos = tr.locate_fast(sq, ui_h, bgr)
        if pos is None:
            pos = self._slow_step(tr, sq, ui_h, bgr)
        if pos is not None and pos.reliable:
            with self._lock:
                tr.accept(pos)
        return pos

    def _slow_step(self, tr: PositionTracker, sq, ui_h: float, bgr) -> Position | None:
        """Забрать готовый результат фонового поиска или запустить новый."""
        job = self._slow
        if job is not None:
            fut, t0, jtr = job
            if not fut.done():
                return None                       # ещё ищет — цикл идёт дальше
            self._slow = None
            try:
                pos = fut.result()
            except Exception:  # noqa: BLE001 — сбой поиска не должен ронять поток
                pos = None
            if pos is not None and jtr is tr and time.monotonic() - t0 <= SLOW_RESULT_MAX_AGE:
                return pos
        last = tr.last
        hint = (last.x, last.y, time.monotonic() - tr.last_t) if last is not None else None
        self._slow = (self._slow_pool.submit(tr.locate_slow, sq.copy(), ui_h, bgr.copy(), hint),
                      time.monotonic(), tr)
        return None

    def _plausible(self, pos: Position, tr: PositionTracker) -> bool:
        """Далёкий прыжок от недавней позиции принимаем, только если JUMP_CONFIRM
        кадров подряд указывают в одно место (телепорт). Иначе это ложное
        совпадение (пещера: её план не совпадает с картой поверхности)."""
        now = time.monotonic()
        last, last_t = self._latest, self._latest_t
        if last is None or now - last_t > JUMP_MEMORY_S:
            self._jump = []
            return True
        if math.hypot(pos.x - last.x, pos.y - last.y) <= JUMP_UNITS:
            self._jump = []
            return True
        if pos.anchor and pos.reliable:
            self._jump = []
            return True                       # у телепорта с уверенностью — это и есть телепорт
        self._jump = [p for p in getattr(self, "_jump", [])
                      if math.hypot(p.x - pos.x, p.y - pos.y) <= JUMP_AGREE]
        self._jump.append(pos)
        if len(self._jump) >= JUMP_CONFIRM:
            self._jump = []
            return True                       # подтверждено: игрок правда там (телепорт)
        tr.last, tr.last_t = last, last_t     # трекер не «прилипает» к ложному месту
        return False

    def _game_foreground(self) -> bool:
        """Активно ли окно игры (кешируется на 0.5 с). Экран вне игры НЕ читаем
        и НЕ пишем — ни кадры, ни текст (там могут быть чаты, документы и т.п.)."""
        now = time.monotonic()
        if now - getattr(self, "_fg_t", 0.0) > 0.5:
            self._fg_t, self._fg_ok = now, is_genshin_foreground()
        return self._fg_ok

    def _read_uid(self, sct, mon: dict) -> None:
        """Раз в UID_EVERY_S читаем «UID: 123456789» в углу игры (несколько аккаунтов)."""
        now = time.monotonic()
        if now - getattr(self, "_uid_t", -UID_EVERY_S) < UID_EVERY_S or not self._game_foreground():
            return
        self._uid_t = now
        if not self._get_ocr().ready:
            return
        reg = region_from_frac(UID_FRAC, mon, "uid")
        frame = cv2.cvtColor(np.array(sct.grab(reg)), cv2.COLOR_BGRA2BGR)
        text = "".join(self._ocr.read(frame, upscale=2.0)).replace(" ", "")
        m = re.search(r"\d{9,10}", text)
        if m:
            self.uidSeen.emit(m.group(0))

    def _read_pickup(self, sct, mon: dict) -> None:
        """OCR области плашки подбора — только у сундука и только когда активна игра."""
        if not self.read_pickup or not self.pickup_frac or not self._game_foreground():
            return
        if not self._get_ocr().ready:
            return
        reg = region_from_frac(self.pickup_frac, mon, "pickup_region")
        frame = cv2.cvtColor(np.array(sct.grab(reg)), cv2.COLOR_BGRA2BGR)
        lines = self._ocr.read(frame, upscale=ocr_upscale(self.ui_s))
        self.pickupText.emit(lines)      # текст наружу только в окно, в запись — нет

    def _get_ocr(self):
        if self._ocr is None:
            from genshinmap.backend.vision.ocr import ScreenOcr
            self._ocr = ScreenOcr("en-US" if self.game_lang == "en" else "ru")
        return self._ocr

    def _check_prompts(self, sct, mon: dict) -> None:
        """Подсказки взаимодействия («F ▶ Богатый сундук») — сундук на месте/нет и
        какой именно. Эталон-картинка, если снят; иначе OCR (только у сундука)."""
        det = self.prompt_detector
        if not self.prompt_frac:
            return
        if det is None or not det.ready:
            if not self.read_prompts or not self._game_foreground() or not self._get_ocr().ready:
                return
            reg = region_from_frac(self.prompt_frac, mon, "prompt_region")
            frame = cv2.cvtColor(np.array(sct.grab(reg)), cv2.COLOR_BGRA2BGR)
            found = parse_prompt_lines(self._ocr.read(frame, upscale=ocr_upscale(self.ui_s)),
                                       self.game_lang)
            self.prompts.emit(found)          # текст наружу не уходит — только вывод
            rec = self.recorder
            if rec and rec.active:
                rec.prompt(frame, found)
            return
        rec = self.recorder
        if not det.ready and not (rec and rec.active):
            return
        reg = region_from_frac(self.prompt_frac, mon, "prompt_region")
        frame = cv2.cvtColor(np.array(sct.grab(reg)), cv2.COLOR_BGRA2BGR)
        found = det.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), ui_height(mon)) \
            if det.ready else {}
        if det.ready:
            self.prompts.emit(found)
        if rec and rec.active and self._game_foreground():
            rec.prompt(frame, found)

    def _record(self, sct, mon: dict, shot: np.ndarray, pos) -> None:
        """Если идёт запись отладки — сохранить мини-карту, плашку и (редко) экран."""
        rec = self.recorder
        if rec is None or not rec.active:
            return
        # пишем ТОЛЬКО когда активно окно игры — никаких кадров рабочего стола/чатов
        if not self._game_foreground():
            return
        rec.boost = self.read_pickup          # у сундука — чаще плашку/подсказку
        rec.minimap(cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR), pos, ui_height(mon))
        if self.pickup_frac:
            reg = region_from_frac(self.pickup_frac, mon, "pickup_region")
            rec.pickup(lambda: cv2.cvtColor(np.array(sct.grab(reg)), cv2.COLOR_BGRA2BGR))
        rec.screen(lambda: cv2.cvtColor(np.array(sct.grab(mon)), cv2.COLOR_BGRA2BGR))
