# SPDX-License-Identifier: GPL-2.0-or-later
"""Mainuan Gestao de Drivers application identity and resource locations."""
from pathlib import Path

APP_NAME = "mainuan-gestao-drivers"
APP_ID = "org.mainuan.GestaoDrivers"
DISPLAY_NAME = "Gestão de Drivers"
ORGANIZATION = "Mainuan"
__version__ = "1.0~rc1"
VERSION = __version__

SHARE_DIR = Path(__file__).resolve().parents[4] / "share"
DATA_DIR = SHARE_DIR / "mainuan" / APP_NAME
LOCALE_DIR = SHARE_DIR / "locale"
ICON_PATH = SHARE_DIR / "icons/hicolor/scalable/apps" / (APP_NAME + ".svg")
