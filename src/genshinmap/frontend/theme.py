"""Цвета и размеры интерфейса — единый источник для окон Qt.

Те же значения продублированы переменными в web/css/map.css (:root) — меняя
цвет здесь, поменяй его и там. Контраст текста: text/text_dim/text_mut не ниже
4.5:1 на surface (правило WCAG для обычного текста).
"""
from __future__ import annotations

C = {
    "bg": "#0B1120",            # фон окна / под картой
    "surface": "#111A2B",       # панели
    "surface_2": "#0D1524",     # поля ввода, списки
    "raised": "#18233A",        # кнопки
    "raised_hover": "#1F2D4A",
    "line": "#2A3854",          # рамки
    "line_soft": "#1B2740",     # разделители
    "text": "#E6ECF6",
    "text_dim": "#A9B6CD",      # второстепенный текст
    "text_mut": "#8595B0",      # подписи, подсказки (≈5:1 на surface)
    "accent": "#5AA2FF",        # интерактивное: фокус, выбранное
    "accent_strong": "#2F6FE0", # залитое выбранное (белый текст ≈4.9:1)
    "gold": "#E8B84A",          # цель, игрок, акцент бренда
    "good": "#3FB950",          # собрано / включено
    "good_bg": "#16301F",
    "good_text": "#C9F5C0",
    "warn": "#D29922",
    "danger": "#F0616D",
    "danger_bg": "#3A1F26",
}

RADIUS = 8        # кнопки, поля
RADIUS_CARD = 10  # карточки-разделы
BTN_H = 34        # минимальная высота кнопки в окне (≥32 по правилам для оверлеев)


def qss() -> str:
    """Общий стиль Qt для главного окна и диалогов."""
    c = C
    return f"""
QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']};
    font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['line']};
    padding: 5px 8px; border-radius: 6px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {c['surface']}; padding: 9px 14px;
    border-bottom: 1px solid {c['line_soft']}; color: {c['text_dim']}; font-weight: 600; }}
QLabel {{ color: {c['text_dim']}; background: transparent; }}
QLabel#section {{ color: {c['text_mut']}; font-size: 12px; font-weight: 700;
    letter-spacing: .5px; padding-top: 4px; }}
QLabel#hint {{ color: {c['text_mut']}; font-size: 12px; }}
QLabel#title {{ color: {c['text']}; font-size: 14px; font-weight: 700; }}
QLabel#posStatus {{ color: {c['text_dim']}; font-size: 12px; }}
QLabel#warnBox {{ color: #FFE2A3; background: rgba(210,153,34,.12);
    border: 1px solid rgba(210,153,34,.45); border-radius: 8px; padding: 7px 9px; font-size: 12px; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['line_soft']};
    border-radius: {RADIUS_CARD}px; }}
QFrame#card QLabel {{ background: transparent; }}
QComboBox {{ background: {c['surface_2']}; border: 1px solid {c['line']}; border-radius: {RADIUS}px;
    padding: 6px 10px; color: {c['text']}; min-height: 22px; }}
QComboBox:hover, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']};
    selection-background-color: {c['accent_strong']}; border: 1px solid {c['line']}; outline: none; }}
QPushButton {{ background: {c['raised']}; border: 1px solid {c['line']}; border-radius: {RADIUS}px;
    padding: 7px 12px; color: {c['text']}; font-weight: 600; min-height: {BTN_H - 16}px; }}
QPushButton:hover {{ background: {c['raised_hover']}; border-color: {c['accent']}; }}
QPushButton:focus {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['surface_2']}; }}
QPushButton:checked {{ background: {c['good_bg']}; border-color: {c['good']}; color: {c['good_text']}; }}
QPushButton:disabled {{ color: #5B6780; border-color: {c['line_soft']}; background: {c['surface']}; }}
QPushButton#primary {{ background: {c['accent_strong']}; border-color: {c['accent']}; color: #FFFFFF; }}
QPushButton#primary:hover {{ background: #3A7BEB; }}
QPushButton#primary:checked {{ background: {c['good_bg']}; border-color: {c['good']}; color: {c['good_text']}; }}
QPushButton#flat {{ background: transparent; border: 1px solid transparent; color: {c['text_dim']};
    padding: 5px 8px; font-weight: 600; }}
QPushButton#flat:hover {{ background: {c['raised']}; border-color: {c['line']}; color: {c['text']}; }}
QPushButton#flat:disabled {{ color: #4A5570; background: transparent; border-color: transparent; }}
QPushButton#update {{ background: {c['good_bg']}; border-color: {c['good']}; color: {c['good_text']}; }}
QPushButton::menu-indicator {{ subcontrol-position: right center; right: 8px; width: 8px; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['line']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['raised_hover']}; }}
QMenu::separator {{ height: 1px; background: {c['line_soft']}; margin: 4px 6px; }}
QListWidget {{ background: {c['surface_2']}; border: 1px solid {c['line_soft']};
    border-radius: {RADIUS}px; padding: 4px; outline: none; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 6px; color: {c['text_dim']}; }}
QListWidget::item:hover {{ background: {c['raised']}; color: {c['text']}; }}
QListWidget::item:selected {{ background: {c['raised_hover']}; color: {c['text']}; }}
QStatusBar {{ background: {c['surface']}; color: {c['text_dim']}; border-top: 1px solid {c['line_soft']}; }}
QStatusBar::item {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #3F5686; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
    {{ height: 0; width: 0; background: transparent; }}
QGroupBox {{ border: 1px solid {c['line_soft']}; border-radius: {RADIUS_CARD}px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {c['text_dim']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{ background: {c['surface_2']};
    border: 1px solid {c['line']}; border-radius: {RADIUS}px; padding: 5px 8px; color: {c['text']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c['accent']}; }}
QCheckBox {{ spacing: 8px; color: {c['text']}; background: transparent; }}
QCheckBox:disabled {{ color: #5B6780; }}
"""
