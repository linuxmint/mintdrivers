import gettext
import locale
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

    test_mode = len(argv) > 1 and argv[1] == "test"
    # Plasma reads per-application settings while QApplication is constructed.
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationVersion(VERSION)
    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication(argv)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setWindowIcon(QIcon.fromTheme(APP_NAME, QIcon(str(ICON_PATH))))

    window = MainWindow(test_mode=test_mode)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

