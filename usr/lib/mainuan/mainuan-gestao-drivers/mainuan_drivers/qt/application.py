import gettext
import argparse
import locale
import logging
import sys

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow
from .. import APP_NAME, APP_ID, DISPLAY_NAME, ORGANIZATION, VERSION, ICON_PATH, LOCALE_DIR


APP = APP_NAME
LOCALE_DIR = str(LOCALE_DIR)

locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext


def run(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(prog=APP_NAME, description=DISPLAY_NAME)
    parser.add_argument("mode", nargs="?", choices=("test",))
    parser.add_argument("--debug", action="store_true", help=_("Show detailed diagnostic logs"))
    parser.add_argument("--version", action="version", version="%s %s" % (DISPLAY_NAME, VERSION))
    options = parser.parse_args(argv[1:])
    test_mode = options.mode == "test"
    logging.basicConfig(level=logging.DEBUG if options.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Plasma reads per-application settings while QApplication is constructed.
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationVersion(VERSION)
    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication([argv[0] if argv else APP_NAME])
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setWindowIcon(QIcon.fromTheme(APP_NAME, QIcon(str(ICON_PATH))))

    window = MainWindow(test_mode=test_mode)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

