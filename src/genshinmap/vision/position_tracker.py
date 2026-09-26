"""ЭТАП 3: определение позиции игрока по мини-карте.

Идея: мини-карта (кружок в левом верхнем углу экрана) — это кусок той же карты
Тейвата, в центре которого стоит игрок. Матчим этот кусок против уменьшенной
копии карты (референса) и получаем мировые координаты игрока.

Как устроено:
  - Референс собирается из v2-тайлов HoYoLAB (зум REF_ZOOM, 1/2 полного
    размера) и кешируется в assets/maps/<id>/ref_<версия>_z<n>.png.
  - Глобальный поиск в два шага: грубо (референс /2) набираем кандидатов,
    затем каждого проверяем точно на полном референсе. Однозначность = отрыв
    лучшего кандидата от второго (в пустыне/море всё «похоже» — не доверяем).
  - Пока игрок отслеживается — только локальный поиск вокруг прошлой позиции
    (миллисекунды вместо секунд).
  - Масштаб мини-карты (сколько мировых единиц в пикселе мини-карты при
    высоте экрана 1080) заранее неизвестен: при первом захвате перебираем
    диапазон и запоминаем лучший (`scale`), дальше ищем только с ним.
  - Мини-карта Genshin всегда ориентирована на север (крутится только конус
    камеры), так что перебирать углы не нужно.

Никакого чтения памяти игры — только пиксели экрана.
"""
from __future__ import annotations

import concurrent.futures as cf
import math
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REF_ZOOM = -1               # зум тайлов для референса (1/2 полного размера)
COARSE_FACTOR = 0.5         # грубый поиск — на референсе, уменьшенном вдвое (1/4)
INNER_FRAC = 0.70           # берём вписанный в круг квадрат (без рамки мини-карты)
BASE_HEIGHT = 1080          # масштаб мини-карты нормируем к высоте экрана 1080
# Масштаб мини-карты Genshin (мировых единиц на пиксель @1080p) — измерен на
# живой игре (Мондштадт, мини-карта ~210 px). Перебор нужен только для калибровки.
DEFAULT_SCALE = 1.66
# Диапазон перебора масштаба: узкий вокруг реального — слишком мелкие масштабы
# дают крошечный шаблон, который «совпадает» с чем угодно.
SCALE_SWEEP = tuple(round(0.45 * 1.13 ** i, 3) for i in range(16))   # 0.45 … ~2.8
# Игра меняет приближение мини-карты: обычно 1.66, в городах (столица Снежной и
# т.п.) — сильно приближена (~0.575). Эти масштабы пробуем всегда (быстро);
# широкий перебор — только если ни один не подошёл (раз в SWEEP_EVERY неудач).
KNOWN_SCALES = (DEFAULT_SCALE, 0.575)
# Запасной поиск по ФОРМЕ ВОДЫ: неразведанные места мини-карта рисует однотонным
# силуэтом (нет деталей), плюс яркий конус камеры — по яркости не находится, а
# береговая линия видна всегда. Маска воды карты — зум -2 (1/4), кеш water_*.png.
WATER_ZOOM = -2
WATER_OK = 0.5            # порог совпадения масок воды
WATER_MARGIN = 0.08       # и отрыв от второго места — строже, чем по яркости
WATER_FRAC = (0.05, 0.85)  # доля воды на мини-карте: меньше/больше — сравнивать нечего
SWEEP_EVERY = 5
SCALE_SWITCH = 0.15       # найденный масштаб отличается больше — переключаемся на него
PEAKS_SWEEP = 4             # кандидатов с каждого масштаба, пока масштаб неизвестен
                            # (проверяются все: 13 масштабов x 4 = 52 окна, это быстро)
PEAKS_KNOWN = 30            # кандидатов, когда масштаб уже откалиброван
MAX_CANDIDATES = 30         # сколько кандидатов проверять точным поиском (дёшево)
ARROW_FRAC = 0.09           # радиус стрелки игрока (доля стороны квадрата) — замазываем
LOCAL_OK = 0.45             # порог уверенности для локального трекинга
CALIBRATE_OK = 0.55         # с какого score доверяем найденному масштабу
MIN_MARGIN = 0.05           # отрыв лучшего кандидата от второго (иначе место
                            # неоднозначно: пустыня, море, снег — везде «похоже»)
DISTINCT_WORLD = 80         # кандидаты ближе этого (мир. ед.) — одно и то же место
ICON_HALF_1080 = 9          # полуразмер значка на мини-карте (px при высоте 1080)
ICON_VIEW_FRAC = 0.40       # значки дальше этой доли стороны от центра — у края, не смотрим
ICON_ARROW_FRAC = 0.07      # ближе — под стрелкой игрока, не смотрим
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://act.hoyolab.com/"}


@dataclass
class Position:
    x: float          # мировые координаты (как в data/maps/<id>/points.json)
    y: float
    score: float
    scale: float = 0.0
    local: bool = False   # найдено локальным трекингом (а не глобальным поиском)
    margin: float = 1.0   # отрыв от второго кандидата (для глобального поиска)
    water: bool = False   # найдено по форме воды (запасной способ)

    @property
    def reliable(self) -> bool:
        return self.score >= LOCAL_OK and (self.local or self.margin >= MIN_MARGIN)


# ---------- референс из v2-тайлов ----------
def reference_path(meta: dict, assets_dir: Path, zoom: int = REF_ZOOM) -> Path:
    ver = str(meta.get("map_version", "v"))[:10]
    return assets_dir / f"ref_{ver}_z{abs(zoom)}.png"


def ref_offset(meta: dict, zoom: int = REF_ZOOM) -> tuple[int, int]:
    """Пиксель (в масштабе зума) левого-верхнего угла референса на полном холсте."""
    zoom = max(zoom, int(meta.get("min_zoom", zoom)))
    scale = 2.0 ** zoom
    ts = int(meta.get("tile_size", 256))
    pad = meta.get("padding", [0, 0])
    return (int(pad[0] * scale) // ts) * ts, (int(pad[1] * scale) // ts) * ts


def _tile_url(meta: dict, x: int, y: int, zoom: int) -> str:
    z = ("N" if zoom < 0 else "P") + str(abs(zoom))
    return meta["tile_url"].replace("{x}", str(x)).replace("{y}", str(y)).replace("{Z}", z)


def _fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:  # noqa: BLE001 — пустой тайл за краем карты = 404, это норма
        return None


def water_mask(bgr: np.ndarray) -> np.ndarray:
    """Маска воды (0/255) по цвету: вода на карте и мини-карте — сине-бирюзовая."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    m = ((h >= 85) & (h <= 115) & (s >= 60) & (v >= 60)).astype(np.uint8) * 255
    return cv2.medianBlur(m, 5)


def water_reference_path(meta: dict, assets_dir: Path) -> Path:
    ver = str(meta.get("map_version", "v"))[:10]
    return assets_dir / f"water_{ver}_z{abs(WATER_ZOOM)}.png"


def ensure_water_reference(meta: dict, out_path: Path, progress=None) -> Path:
    """Маска воды всей карты из цветных тайлов (один раз, дальше — кеш)."""
    return ensure_reference(meta, out_path, WATER_ZOOM, progress,
                            decode=lambda data: water_mask(
                                cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)))


def ensure_reference(meta: dict, out_path: Path, zoom: int = REF_ZOOM,
                     progress=None, decode=None) -> Path:
    """Собрать серый референс карты из v2-тайлов (один раз, дальше — кеш).

    Качаются только тайлы, покрывающие реальный контент (padding + content_size).
    Координаты референса = пиксели полного холста * 2**zoom минус ref_offset.
    """
    if out_path.exists():
        return out_path
    zoom = max(zoom, int(meta.get("min_zoom", zoom)))
    scale = 2.0 ** zoom
    ts = int(meta.get("tile_size", 256))
    W, H = meta["total_size"]
    pad = meta.get("padding", [0, 0])
    cs = meta.get("content_size", meta["total_size"])
    full_w, full_h = math.ceil(W * scale), math.ceil(H * scale)
    x0, y0 = ref_offset(meta, zoom)
    x0, y0 = x0 // ts, y0 // ts
    x1 = min(math.ceil(full_w / ts), math.ceil((pad[0] + cs[0]) * scale / ts))
    y1 = min(math.ceil(full_h / ts), math.ceil((pad[1] + cs[1]) * scale / ts))
    jobs = [(x, y) for y in range(y0, y1) for x in range(x0, x1)]

    # холст — только прямоугольник тайлов с контентом (пустые поля не храним)
    cw, ch = (x1 - x0) * ts, (y1 - y0) * ts
    canvas = np.zeros((ch, cw), dtype=np.uint8)
    done = 0
    with cf.ThreadPoolExecutor(16) as ex:
        futs = {ex.submit(_fetch, _tile_url(meta, x, y, zoom)): (x, y) for x, y in jobs}
        for fut in cf.as_completed(futs):
            x, y = futs[fut]
            data = fut.result()
            done += 1
            if progress and (done % 50 == 0 or done == len(jobs)):
                progress(done, len(jobs))
            if not data:
                continue
            tile = decode(data) if decode else \
                cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if tile is None:
                continue
            py, px = (y - y0) * ts, (x - x0) * ts
            h = min(tile.shape[0], ch - py)
            w = min(tile.shape[1], cw - px)
            if h > 0 and w > 0:
                canvas[py:py + h, px:px + w] = tile[:h, :w]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.png")     # атомарно: недокачанный файл не станет кешем
    cv2.imwrite(str(tmp), canvas)
    tmp.replace(out_path)
    return out_path


# ---------- трекер ----------
def inner_square(img: np.ndarray, frac: float = INNER_FRAC) -> np.ndarray:
    """Центральный квадрат, вписанный в круг мини-карты (рамка и углы отрезаны)."""
    h, w = img.shape[:2]
    side = int(min(h, w) * frac)
    y0, x0 = (h - side) // 2, (w - side) // 2
    return img[y0:y0 + side, x0:x0 + side]


def _peaks(res: np.ndarray, k: int, radius: int) -> list[tuple[float, tuple[int, int]]]:
    """k лучших локальных максимумов карты совпадений (с подавлением соседей)."""
    r = res.copy()
    out = []
    for _ in range(k):
        _, val, _, loc = cv2.minMaxLoc(r)
        if val <= 0:
            break
        out.append((float(val), loc))
        x, y = loc
        r[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1] = -1.0
    return out


class PositionTracker:
    """Позиция по мини-карте: кандидаты грубым поиском -> точная проверка -> трекинг."""

    def __init__(self, meta: dict, reference_path: Path, zoom: int = REF_ZOOM,
                 scale: float | None = None, water_path: Path | None = None) -> None:
        self.meta = meta
        zoom = max(zoom, int(meta.get("min_zoom", zoom)))
        self.ref_scale = 2.0 ** zoom                      # пиксель референса / пиксель холста
        self.ref_off = ref_offset(meta, zoom)             # сдвиг обрезанного референса
        self.fine = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
        if self.fine is None:
            raise FileNotFoundError(f"Нет референс-карты: {reference_path}")
        self.coarse = cv2.resize(self.fine, None, fx=COARSE_FACTOR, fy=COARSE_FACTOR,
                                 interpolation=cv2.INTER_AREA)
        self.scale = scale                                # мир. единиц на px мини-карты @1080p
        self.last: Position | None = None
        self.last_t = 0.0
        self.water = None
        if water_path is not None and Path(water_path).exists():
            self.set_water(Path(water_path))

    def set_water(self, water_path: Path) -> None:
        """Подключить маску воды карты (запасной поиск по форме береговой линии)."""
        w = cv2.imread(str(water_path), cv2.IMREAD_GRAYSCALE)
        if w is not None:
            self.water_scale = 2.0 ** WATER_ZOOM
            self.water_off = ref_offset(self.meta, WATER_ZOOM)
            self.water = w

    # --- координаты ---
    def _ref_to_world(self, rx: float, ry: float, factor: float = 1.0) -> tuple[float, float]:
        # factor < 1 — координаты на уменьшенном (coarse) референсе
        rx = rx / factor + self.ref_off[0]
        ry = ry / factor + self.ref_off[1]
        return (rx / self.ref_scale - self.meta["origin"][0],
                ry / self.ref_scale - self.meta["origin"][1])

    def _world_to_ref(self, wx: float, wy: float) -> tuple[float, float]:
        return ((wx + self.meta["origin"][0]) * self.ref_scale - self.ref_off[0],
                (wy + self.meta["origin"][1]) * self.ref_scale - self.ref_off[1])

    @staticmethod
    def _prep(minimap_gray: np.ndarray, screen_h: int) -> np.ndarray:
        """Квадрат мини-карты, приведённый к экрану высотой 1080."""
        sq = inner_square(minimap_gray)
        k = BASE_HEIGHT / max(1, screen_h)
        if abs(k - 1.0) > 0.01:
            sq = cv2.resize(sq, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        # стрелка игрока в центре — не часть карты: закрашиваем её окружением
        side = sq.shape[0]
        mask = np.zeros_like(sq)
        cv2.circle(mask, (side // 2, side // 2), max(2, int(side * ARROW_FRAC)), 255, -1)
        return cv2.inpaint(np.ascontiguousarray(sq), mask, 3, cv2.INPAINT_TELEA)

    def _tmpl(self, sq: np.ndarray, scale: float, factor: float) -> np.ndarray | None:
        side = round(sq.shape[0] * scale * self.ref_scale * factor)
        if side < 10:
            return None
        return cv2.resize(sq, (side, side), interpolation=cv2.INTER_AREA)

    def _search_window(self, sq: np.ndarray, wx: float, wy: float, radius_ref: int,
                       scales: tuple[float, ...]) -> Position | None:
        """Точный поиск в окне вокруг мировой точки (wx, wy) на полном референсе."""
        cx, cy = self._world_to_ref(wx, wy)
        best: Position | None = None
        for s in scales:
            t = self._tmpl(sq, s, 1.0)
            if t is None:
                continue
            half = radius_ref + t.shape[0] // 2 + 1
            x0 = max(0, int(cx - half)); y0 = max(0, int(cy - half))
            x1 = min(self.fine.shape[1], int(cx + half)); y1 = min(self.fine.shape[0], int(cy + half))
            win = self.fine[y0:y1, x0:x1]
            if win.shape[0] <= t.shape[0] or win.shape[1] <= t.shape[1]:
                continue
            res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if best is None or val > best.score:
                x, y = self._ref_to_world(x0 + loc[0] + t.shape[1] / 2,
                                          y0 + loc[1] + t.shape[0] / 2)
                best = Position(round(x, 1), round(y, 1), float(val), s)
        return best

    def _scales(self) -> tuple[float, ...]:
        """Текущий масштаб первым, затем остальные известные (без повторов)."""
        out = [self.scale] if self.scale else []
        for k in KNOWN_SCALES:
            if all(abs(k - s) / s > 0.05 for s in out):
                out.append(k)
        return tuple(out)

    def locate_global(self, sq: np.ndarray, sweep: bool = False) -> Position | None:
        """Поиск по всей карте.

        1) грубо: на уменьшенном референсе берём по несколько лучших пиков с
           каждого масштаба (мелкий шаблон часто ошибается — поэтому кандидаты,
           а не один максимум);
        2) точно: каждый кандидат проверяем на полном референсе в маленьком окне;
        3) отрыв лучшего кандидата от второго (в другом месте) = однозначность.
        """
        sweep = sweep or not self.scale
        scales = SCALE_SWEEP if sweep else self._scales()
        n_peaks = PEAKS_SWEEP if sweep else PEAKS_KNOWN
        # при переборе шаг масштаба 1.2 — проверяем плотнее, чтобы попасть в истинный
        fine_steps = (0.92, 0.96, 1.0, 1.04, 1.08) if sweep else (0.96, 1.0, 1.04)
        cands = []  # (грубый score, scale, wx, wy)
        for s in scales:
            t = self._tmpl(sq, s, COARSE_FACTOR)
            if t is None or t.shape[0] >= min(self.coarse.shape[:2]):
                continue
            res = cv2.matchTemplate(self.coarse, t, cv2.TM_CCOEFF_NORMED)
            # кандидаты берём с КАЖДОГО масштаба: мелкие шаблоны дают завышенные
            # грубые оценки и иначе вытеснили бы верное место из общего топа
            for val, loc in _peaks(res, n_peaks, t.shape[0] // 2):
                wx, wy = self._ref_to_world(loc[0] + t.shape[1] / 2, loc[1] + t.shape[0] / 2,
                                            COARSE_FACTOR)
                cands.append((val, s, wx, wy))
        if not cands:
            return None
        if not sweep:
            cands.sort(key=lambda c: c[0], reverse=True)
            cands = cands[:MAX_CANDIDATES]

        verified: list[Position] = []
        for _, s, wx, wy in cands:
            p = self._search_window(sq, wx, wy, 6, tuple(s * f for f in fine_steps))
            if p:
                verified.append(p)
        if not verified:
            return None
        verified.sort(key=lambda p: p.score, reverse=True)
        best = verified[0]
        other = next((p.score for p in verified[1:]
                      if math.hypot(p.x - best.x, p.y - best.y) > DISTINCT_WORLD), 0.0)
        best.margin = best.score - other
        return best

    # ---------- запасной поиск по форме воды ----------
    def _water_template(self, minimap_bgr: np.ndarray, screen_h: int) -> np.ndarray | None:
        sq = inner_square(minimap_bgr)
        k = BASE_HEIGHT / max(1, screen_h)
        if abs(k - 1.0) > 0.01:
            sq = cv2.resize(sq, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        m = water_mask(sq)
        frac = float(m.mean()) / 255.0
        if not (WATER_FRAC[0] <= frac <= WATER_FRAC[1]):
            return None                       # воды нет / одна вода — сравнивать нечего
        return m

    def _water_window(self, mask: np.ndarray, wx: float, wy: float,
                      radius_units: float) -> Position | None:
        """Трекинг по воде: поиск только в окне вокруг прошлой позиции (быстро)."""
        best = None
        cx = (wx + self.meta["origin"][0]) * self.water_scale - self.water_off[0]
        cy = (wy + self.meta["origin"][1]) * self.water_scale - self.water_off[1]
        for s in self._scales() or KNOWN_SCALES:
            side = round(mask.shape[0] * s * self.water_scale)
            if side < 12:
                continue
            t = cv2.resize(mask, (side, side), interpolation=cv2.INTER_AREA)
            half = int(radius_units * self.water_scale) + side // 2 + 1
            x0, y0 = max(0, int(cx - half)), max(0, int(cy - half))
            win = self.water[y0:int(cy + half), x0:int(cx + half)]
            if win.shape[0] <= side or win.shape[1] <= side:
                continue
            _, val, _, loc = cv2.minMaxLoc(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED))
            if best is None or val > best.score:
                rx = x0 + loc[0] + side / 2 + self.water_off[0]
                ry = y0 + loc[1] + side / 2 + self.water_off[1]
                best = Position(round(rx / self.water_scale - self.meta["origin"][0], 1),
                                round(ry / self.water_scale - self.meta["origin"][1], 1),
                                float(val), s, local=True, water=True)
        return best if best is not None and best.score >= WATER_OK else None

    def locate_water(self, minimap_bgr: np.ndarray, screen_h: int) -> Position | None:
        """Где на карте такая же береговая линия. Уверенное — только с отрывом."""
        if self.water is None:
            return None
        mask = self._water_template(minimap_bgr, screen_h)
        if mask is None:
            return None
        cands = []
        for s in self._scales() or KNOWN_SCALES:
            side = round(mask.shape[0] * s * self.water_scale)
            if side < 12 or side >= min(self.water.shape[:2]):
                continue
            t = cv2.resize(mask, (side, side), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(self.water, t, cv2.TM_CCOEFF_NORMED)
            for val, loc in _peaks(res, 6, side // 2):
                rx = loc[0] + side / 2 + self.water_off[0]
                ry = loc[1] + side / 2 + self.water_off[1]
                cands.append(Position(round(rx / self.water_scale - self.meta["origin"][0], 1),
                                      round(ry / self.water_scale - self.meta["origin"][1], 1),
                                      float(val), s, water=True))
        if not cands:
            return None
        cands.sort(key=lambda p: p.score, reverse=True)
        best = cands[0]
        other = next((p.score for p in cands[1:]
                      if math.hypot(p.x - best.x, p.y - best.y) > DISTINCT_WORLD), 0.0)
        best.margin = best.score - other
        if best.score < WATER_OK or best.margin < WATER_MARGIN:
            best.margin = min(best.margin, MIN_MARGIN - 0.01)   # не надёжно
        return best

    def locate(self, minimap_gray: np.ndarray, screen_h: int = BASE_HEIGHT,
               minimap_bgr: np.ndarray | None = None) -> Position | None:
        """Позиция игрока по кадру мини-карты (None — не удалось).

        Если игрок недавно был найден — сначала локальный поиск вокруг него
        (миллисекунды); глобальный — только если потеряли (телепорт, загрузка).
        """
        sq = self._prep(minimap_gray, screen_h)
        if sq.shape[0] < 16 or float(sq.std()) < 4.0:   # пустой/чёрный кадр (загрузка, меню)
            return None
        pos = None
        # в неразведанных местах (прошлую позицию нашли по воде) — сначала вода рядом
        if (minimap_bgr is not None and self.water is not None and self.last is not None
                and self.last.water and time.monotonic() - self.last_t < 5.0):
            mask = self._water_template(minimap_bgr, screen_h)
            if mask is not None:
                pos = self._water_window(mask, self.last.x, self.last.y, 150)
        if pos is None and self.last and self.scale and time.monotonic() - self.last_t < 3.0:
            # локально: текущий масштаб, а если нет — другие известные (вошёл в город)
            for s in self._scales():
                pos = self._search_window(sq, self.last.x, self.last.y, 60, (s,))
                if pos and pos.score >= LOCAL_OK:
                    pos.local = True
                    break
                pos = None
        if pos is None:
            # порядок по цене: яркость на известных масштабах (с) -> форма воды (доли с)
            # -> изредка широкий перебор масштабов (самое медленное)
            pos = self.locate_global(sq)
            if (pos is None or not pos.reliable) and minimap_bgr is not None:
                wpos = self.locate_water(minimap_bgr, screen_h)
                if wpos is not None and wpos.reliable:
                    pos = wpos
            if (pos is None or not pos.reliable) and self.scale:
                self._global_fails = getattr(self, "_global_fails", 0) + 1
                if self._global_fails % SWEEP_EVERY == 0:
                    swept = self.locate_global(sq, sweep=True)
                    if swept is not None and (pos is None or swept.score > pos.score):
                        pos = swept
        if pos is None:
            return None
        if pos.reliable:
            self._global_fails = 0
            self.last, self.last_t = pos, time.monotonic()
            if not self.scale and pos.score >= CALIBRATE_OK:
                self.scale = pos.scale     # масштаб найден — дальше ищем только с ним
            elif self.scale and abs(pos.scale - self.scale) / self.scale > SCALE_SWITCH:
                self.scale = pos.scale     # игра приблизила/отдалила мини-карту (город)
        return pos

    # ---------- значки на мини-карте ----------
    def icon_presence(self, minimap_gray: np.ndarray, screen_h: int, pos: Position,
                      points: list[tuple[str, float, float]]) -> dict[str, float]:
        """Есть ли на мини-карте значок в месте каждой точки: {point_id: 0..1}.

        Позиция игрока и масштаб известны, значит, известно, в каком пикселе
        мини-карты должна быть точка. Сравниваем этот кусочек мини-карты с тем
        же местом референса: значок (окулус и т.п.) — картинка сильно
        отличается от карты (≈1), значка нет — совпадает (≈0).
        Точки у края мини-карты и под стрелкой игрока пропускаем.
        """
        scale = pos.scale or self.scale
        if not scale or minimap_gray.size == 0:
            return {}
        h, w = minimap_gray.shape[:2]
        side = min(h, w)
        cx, cy = w / 2, h / 2
        units_per_px = scale * BASE_HEIGHT / max(1, screen_h)
        r = max(4, round(ICON_HALF_1080 * screen_h / BASE_HEIGHT))
        out: dict[str, float] = {}
        for pid, x, y in points:
            mx = cx + (x - pos.x) / units_per_px
            my = cy + (y - pos.y) / units_per_px
            d = math.hypot(mx - cx, my - cy)
            if d > side * ICON_VIEW_FRAC or d < side * ICON_ARROW_FRAC:
                continue
            x0, y0 = int(mx - r), int(my - r)
            patch = minimap_gray[y0:y0 + 2 * r, x0:x0 + 2 * r]
            if patch.shape != (2 * r, 2 * r):
                continue
            rx, ry = self._world_to_ref(x, y)
            half = r * units_per_px * self.ref_scale
            ref = self.fine[int(ry - half):int(ry + half), int(rx - half):int(rx + half)]
            if ref.size == 0 or min(ref.shape) < 4:
                continue
            ref = cv2.resize(ref, (2 * r, 2 * r), interpolation=cv2.INTER_AREA)
            if float(patch.std()) < 1.0 or float(ref.std()) < 1.0:
                # однотонный кусок: сравниваем яркость
                out[pid] = min(1.0, abs(float(patch.mean()) - float(ref.mean())) / 60.0)
                continue
            ncc = float(cv2.matchTemplate(patch, ref, cv2.TM_CCOEFF_NORMED)[0, 0])
            out[pid] = round(max(0.0, min(1.0, 1.0 - ncc)), 3)
        return out
