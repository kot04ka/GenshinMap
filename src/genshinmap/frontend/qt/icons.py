"""Векторные иконки (контурные, в стиле Lucide: 24×24, линия 2 px) для окон Qt.

Эмодзи вместо иконок выглядят по-разному в разных шрифтах и не красятся под
тему — поэтому кнопки используют эти SVG. Те же рисунки для страницы карты —
в web/js/icons.js.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from genshinmap.frontend.theme import C

# Содержимое <svg> для каждой иконки
PATHS: dict[str, str] = {
    "locate": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/>'
              '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2'
            'M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/>',
    "overlay": '<path d="M21 9V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10c0 1.1.9 2 2 2h4"/>'
               '<rect x="12" y="13" width="10" height="7" rx="2"/>',
    "pin": '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16'
           'a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7'
           'a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    "undo": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0'
                'l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51'
                'a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08'
                'a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18'
                'a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39'
                'a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09'
                'a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25'
                'a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "save": '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5'
            'a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
            '<path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
               '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>'
                '<path d="M12 15V3"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6'
              'a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5'
              'a1 1 0 0 1 1 1z"/>',
    "gem": '<path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13-3-6"/><path d="M2 9h20"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>'
             '<path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/>'
              '<path d="M12 3v12"/>',
    "import": '<path d="M12 3v12"/><path d="m8 11 4 4 4-4"/>'
              '<path d="M8 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4"/>',
    "maximize": '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>',
    "move": '<path d="M12 2v20"/><path d="m15 19-3 3-3-3"/><path d="m19 9 3 3-3 3"/><path d="M2 12h20"/>'
            '<path d="m5 9-3 3 3 3"/><path d="m9 5 3-3 3 3"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
              '<circle cx="12" cy="13" r="3"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4'
              'a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "chest": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4'
             'A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0'
             ' 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0'
                ' 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0'
                ' 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>'
                '<path d="M20 3v4M22 5h-4"/>',
    "navigate": '<path d="M3 11 22 2 13 21 11 13 3 11z"/>',
    "portal": '<circle cx="12" cy="12" r="10"/><path d="M12 6a6 6 0 1 0 6 6"/><path d="M12 10a2 2 0 1 0 2 2"/>',
    "cave": '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
    "pin-map": '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10'
               'a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
    "circle": '<circle cx="12" cy="12" r="9"/>',
    "circle-check": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/>'
                '<path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M18 13h.01M8 15h8"/>',
    "map": '<path d="M14.1 4.4a2 2 0 0 0-1.3-.1L9 5.3a2 2 0 0 1-1.3-.1L4.4 3.9A1 1 0 0 0 3 4.8v13.1'
           'a1 1 0 0 0 .6.9l4.1 1.8a2 2 0 0 0 1.3.1l3.8-1a2 2 0 0 1 1.3.1l3.3 1.3a1 1 0 0 0 1.4-.9'
           'V6.1a1 1 0 0 0-.6-.9z"/><path d="M15 5.8v15"/><path d="M9 3.2v15"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
             '<path d="M2 12h20"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94'
              'l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "list-check": '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/>'
                  '<path d="M13 12h8"/><path d="M13 18h8"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
}

# Страницы настроек -> иконка
SETTINGS_ICONS = {"Поверх игры": "target", "Авто-отметка": "list-check", "Горячие клавиши": "keyboard",
                  "Мини-окно и карта": "map", "Язык": "globe", "Дополнительно": "wrench"}


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, px: int) -> QPixmap:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
           f'{PATHS[name]}</svg>')
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, px, px))
    p.end()
    return pm


def icon(name: str, color: str | None = None, checked_color: str | None = None) -> QIcon:
    """QIcon из SVG. checked_color — цвет во включённом состоянии (для переключателей)."""
    ic = QIcon()
    base = color or C["text_dim"]
    for px in (16, 20, 32, 40):          # чёткость на экранах с масштабом 125–200 %
        ic.addPixmap(_pixmap(name, base, px), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(_pixmap(name, checked_color or base, px), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_pixmap(name, "#4A5570", px), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic
