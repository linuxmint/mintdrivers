import gettext
import locale
import sys

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow


APP = "mintdrivers"
LOCALE_DIR = "/usr/share/locale"

locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext


def run(argv=None):
    if argv is None:
        argv = sys.argv

    test_mode = len(argv) > 1 and argv[1] == "test"
    # Plasma reads per-application settings while QApplication is constructed.
    QCoreApplication.setApplicationName("mintdrivers-qt")
    QCoreApplication.setOrganizationName("Linux Mint")
    QGuiApplication.setDesktopFileName("mintdrivers-qt")
    app = QApplication(argv)
    app.setApplicationDisplayName(_("Driver Manager"))

    window = MainWindow(test_mode=test_mode)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

