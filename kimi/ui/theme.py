"""Design tokens and the Qt style sheet for Kimi's storybook look.

Colours are role-based tokens with a light ("Daylight") and dark
("Lantern night") palette. Type sizes come from a modular scale
(base 11pt, ratio 1.25) and are expressed in points so they follow the
Windows display scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    name: str
    window: str
    surface: str
    surface_alt: str
    sidebar: str
    ink: str
    ink_muted: str
    outline: str
    accent: str
    accent_hover: str
    text_on_accent: str
    accent_soft: str
    danger: str
    text_on_danger: str
    warning: str
    success: str
    info: str
    hunger: str
    energy: str
    curiosity: str
    happiness: str
    social: str
    paper: str
    paper_ink: str


DAYLIGHT = Tokens(
    name="light",
    window="#efe6d2", surface="#fbf6ea", surface_alt="#f3ead6", sidebar="#e7dbc0",
    ink="#3a2e24", ink_muted="#6b5c4c", outline="#d6c6a4",
    accent="#3f6e4e", accent_hover="#335c40", text_on_accent="#ffffff", accent_soft="#dce8d3",
    danger="#a83b2a", text_on_danger="#ffffff", warning="#9a6a12", success="#3f7a4a", info="#3f628f",
    hunger="#c9803a", energy="#c9a22e", curiosity="#5f86b3", happiness="#cc6a85", social="#74924f",
    paper="#fffaf0", paper_ink="#3d3127",
)

LANTERN_NIGHT = Tokens(
    name="dark",
    window="#1e1b21", surface="#28242b", surface_alt="#312c34", sidebar="#231f26",
    ink="#efe6d6", ink_muted="#b8ab99", outline="#463f4b",
    accent="#8fc29a", accent_hover="#a5d1ae", text_on_accent="#17251b", accent_soft="#2f4135",
    danger="#e3735f", text_on_danger="#1e1210", warning="#e2b553", success="#8fc29a", info="#9ab6dc",
    hunger="#e09a55", energy="#e2c45a", curiosity="#86a9d4", happiness="#e28aa3", social="#9dbb72",
    paper="#2f2a30", paper_ink="#efe4d2",
)

# Modular type scale (points): base 11, ratio 1.25 (major third).
TYPE = {"caption": 9.0, "body": 11.0, "reading": 12.0, "h2": 13.75, "h1": 17.0, "display": 21.5}

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", "Sans Serif"]
HEADING_FAMILIES = ["Georgia", "Cambria", "Noto Serif", "DejaVu Serif", "Serif"]
DIARY_FAMILIES = ["Segoe Print", "Ink Free", "Georgia", "Noto Serif", "Serif"]

_current: Tokens = DAYLIGHT


def tokens() -> Tokens:
    return _current


def font(role: str = "body", families: list[str] | None = None, weight: QFont.Weight | None = None,
         italic: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(families or (HEADING_FAMILIES if role in ("h1", "display") else UI_FAMILIES))
    f.setPointSizeF(TYPE.get(role, TYPE["body"]))
    if weight is not None:
        f.setWeight(weight)
    f.setItalic(italic)
    return f


def heading_font(role: str = "h1") -> QFont:
    return font(role, HEADING_FAMILIES, QFont.Weight.Medium)


def system_prefers_dark() -> bool:
    try:
        from PySide6.QtCore import Qt

        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001 - older Qt
        return False


def resolve(mode: str) -> Tokens:
    if mode == "dark":
        return LANTERN_NIGHT
    if mode == "light":
        return DAYLIGHT
    return LANTERN_NIGHT if system_prefers_dark() else DAYLIGHT


ICONS = Path(__file__).resolve().parent / "icons"


def stylesheet(t: Tokens) -> str:
    body, cap, h2 = TYPE["body"], TYPE["caption"], TYPE["h2"]
    up, down = (ICONS / "spin-up.svg").as_posix(), (ICONS / "spin-down.svg").as_posix()
    return f"""
    QWidget {{ color: {t.ink}; }}
    QMainWindow, QDialog, #Page {{ background: {t.window}; }}
    QToolTip {{ background: {t.surface}; color: {t.ink}; border: 1px solid {t.outline}; padding: 4px 6px; }}

    #Header {{ background: {t.surface}; border-bottom: 1px solid {t.outline}; }}
    #Sidebar {{ background: {t.sidebar}; border: none; border-right: 1px solid {t.outline}; outline: 0; padding: 8px 6px; }}
    #Sidebar::item {{ padding: 10px 14px; margin: 2px 4px; border-radius: 8px; color: {t.ink}; }}
    #Sidebar::item:hover {{ background: {t.surface_alt}; }}
    #Sidebar::item:selected {{ background: {t.accent_soft}; color: {t.ink}; font-weight: 600; }}
    #Sidebar:focus {{ border-right: 2px solid {t.accent}; }}

    #Card {{ background: {t.surface}; border: 1px solid {t.outline}; border-radius: 12px; }}
    #CardTitle {{ font-size: {h2}pt; font-weight: 600; color: {t.ink}; }}
    #Muted, QLabel[muted="true"] {{ color: {t.ink_muted}; }}
    #Caption {{ color: {t.ink_muted}; font-size: {cap}pt; }}
    #Banner {{ background: {t.accent_soft}; border: 1px solid {t.accent}; border-radius: 10px; }}
    #DangerBanner {{ background: {t.surface}; border: 2px solid {t.danger}; border-radius: 10px; }}

    QPushButton {{ background: {t.surface_alt}; color: {t.ink}; border: 1px solid {t.outline};
                   border-radius: 8px; padding: 6px 14px; min-height: 22px; }}
    QPushButton:hover {{ border-color: {t.accent}; }}
    QPushButton:focus {{ border: 2px solid {t.accent}; }}
    QPushButton:disabled {{ color: {t.ink_muted}; background: {t.surface}; border-color: {t.outline}; }}
    QPushButton:checked {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
    QPushButton[role="primary"] {{ background: {t.accent}; color: {t.text_on_accent}; border: 1px solid {t.accent}; font-weight: 600; }}
    QPushButton[role="primary"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[role="primary"]:focus {{ border: 2px solid {t.ink}; }}
    QPushButton[role="primary"]:disabled {{ background: {t.outline}; color: {t.ink_muted}; border-color: {t.outline}; }}
    QPushButton[role="danger"] {{ background: {t.danger}; color: {t.text_on_danger}; border: 1px solid {t.danger}; font-weight: 600; }}
    QPushButton[role="danger"]:focus {{ border: 2px solid {t.ink}; }}
    QPushButton[role="link"] {{ background: transparent; border: none; color: {t.accent}; padding: 2px 4px; text-decoration: underline; }}

    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t.surface}; color: {t.ink}; border: 1px solid {t.outline}; border-radius: 6px; padding: 4px 8px;
        selection-background-color: {t.accent}; selection-color: {t.text_on_accent}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 2px solid {t.accent}; }}
    /* Number boxes: styled up/down arrows. (Hiding the buttons under a stylesheet makes Qt
       squeeze the text field to 1 pixel wide, so the value becomes invisible.) */
    QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; width: 20px; border: none; background: transparent; margin-right: 2px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::down-button:hover {{ background: {t.accent_soft}; border-radius: 4px; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 6px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 6px; }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,
    QDoubleSpinBox::down-arrow:disabled {{ image: none; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.ink}; selection-background-color: {t.accent_soft}; selection-color: {t.ink}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox:focus {{ color: {t.accent}; }}

    QTextBrowser {{ background: {t.surface}; border: 1px solid {t.outline}; border-radius: 10px; padding: 6px; }}
    QTextBrowser#Paper {{ background: {t.paper}; color: {t.paper_ink}; border: 1px solid {t.outline}; padding: 18px 26px; }}

    QTreeWidget, QTableWidget, QListWidget {{ background: {t.surface}; alternate-background-color: {t.surface_alt};
        border: 1px solid {t.outline}; border-radius: 8px; outline: 0; }}
    QTreeWidget::item {{ padding: 4px 2px; }}
    QListWidget::item {{ padding: 6px 8px; }}
    QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.ink}; }}
    QTreeWidget:focus, QTableWidget:focus, QListWidget:focus {{ border: 2px solid {t.accent}; }}
    QHeaderView::section {{ background: {t.surface_alt}; color: {t.ink_muted}; border: none; border-bottom: 1px solid {t.outline};
        padding: 5px 8px; font-weight: 600; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; color: {t.ink_muted}; padding: 7px 14px; margin-right: 4px;
        border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.ink}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}
    QTabBar::tab:focus {{ color: {t.accent}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.outline}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.outline}; border-radius: 4px; min-width: 30px; }}
    QProgressBar {{ background: {t.surface_alt}; border: 1px solid {t.outline}; border-radius: 5px; height: 8px; text-align: center; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
    """


def apply_theme(app: QApplication, mode: str) -> Tokens:
    global _current
    _current = resolve(mode)
    t = _current
    app.setStyle("Fusion")
    app.setFont(font("body"))
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.window))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.ink))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface_alt))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.ink))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.surface_alt))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.ink))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.text_on_accent))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.ink_muted))
    pal.setColor(QPalette.ColorRole.Link, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.ink))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
    return t
