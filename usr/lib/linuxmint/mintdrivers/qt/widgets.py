import gettext
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from backend import DeviceStatus, DriverOptionType


_ = gettext.gettext


ICON_THEME_NAMES = {
    "nvidia": ("nvidia-settings", "video-display"),
    "amd": ("processor", "cpu", "video-display"),
    "ati": ("video-display",),
    "intel": ("processor", "cpu"),
    "broadcom": ("network-wireless",),
    "virtualbox": ("virtualbox", "computer"),
    "generic": ("computer",),
}


@dataclass(frozen=True)
class DriverOptionPresentation:
    title: str
    subtitle: str
    badges: tuple
    selected: bool


def device_status_text(device):
    if device.is_cpu:
        return _("Processor microcode")
    return {
        DeviceStatus.RECOMMENDED: _("This device is using the recommended driver."),
        DeviceStatus.ALTERNATIVE: _("This device is using an alternative driver."),
        DeviceStatus.MANUALLY_INSTALLED: _("This device is using a manually-installed driver."),
        DeviceStatus.NO_DRIVER: _("This device is not working."),
    }[device.status]


def driver_option_presentation(option):
    badges = []
    if option.selected:
        badges.append(_("Current"))
    if option.recommended:
        badges.append(_("Recommended"))
    if option.builtin:
        badges.append(_("Integrated into the system"))
    elif option.option_type == DriverOptionType.PACKAGE:
        badges.append(_("Open-source") if option.free else _("Proprietary"))
    if option.installed:
        badges.append(_("Installed"))
    if option.requires_internet:
        badges.append(_("Requires an Internet connection"))

    if option.option_type == DriverOptionType.MANUAL:
        return DriverOptionPresentation(
            title=_("Continue using a manually installed driver"),
            subtitle="",
            badges=tuple(badges),
            selected=option.selected,
        )
    if option.option_type == DriverOptionType.DISABLE:
        return DriverOptionPresentation(
            title=_("Do not use the device"),
            subtitle="",
            badges=tuple(badges),
            selected=option.selected,
        )

    subtitle_parts = []
    if option.version:
        subtitle_parts.append(_("Version: %s") % option.version)
    if option.summary:
        subtitle_parts.append(option.summary)
    return DriverOptionPresentation(
        title=option.package_name or _("Driver package"),
        subtitle=" - ".join(subtitle_parts),
        badges=tuple(badges),
        selected=option.selected,
    )


def _project_icon_path(icon_key):
    source_icon = Path(__file__).resolve().parents[4] / "share/linuxmint/mintdrivers/icons" / ("%s.svg" % icon_key)
    if source_icon.exists():
        return str(source_icon)
    installed_icon = Path("/usr/share/linuxmint/mintdrivers/icons") / ("%s.svg" % icon_key)
    if installed_icon.exists():
        return str(installed_icon)
    return None


def themed_icon(icon_key):
    for theme_name in ICON_THEME_NAMES.get(icon_key, ICON_THEME_NAMES["generic"]):
        icon = QIcon.fromTheme(theme_name)
        if not icon.isNull():
            return icon
    icon_path = _project_icon_path(icon_key)
    if icon_path:
        return QIcon(icon_path)
    return QIcon.fromTheme("computer")


class DeviceWidget(QFrame):
    def __init__(self, device, on_select=None, preview_only=False):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(themed_icon(device.icon_key).pixmap(48, 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon)

        details = QVBoxLayout()
        details.setSpacing(8)
        layout.addLayout(details, 1)

        title = QLabel(_device_title(device))
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        details.addWidget(title)

        status = QLabel(device_status_text(device))
        status.setWordWrap(True)
        details.addWidget(status)

        self.option_group = QButtonGroup(self)
        self._selected_button = None
        for index, option in enumerate(_sorted_options(device.drivers)):
            if index:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                details.addWidget(line)
            option_widget = DriverOptionWidget(option, selectable=on_select is not None)
            if on_select is not None:
                button = option_widget.selection_button
                self.option_group.addButton(button)
                button.setChecked(option.selected)
                button.setEnabled(option.selectable or (preview_only and option.option_type != DriverOptionType.MANUAL))
                if option.selected:
                    self._selected_button = button
                button.clicked.connect(
                    lambda checked, selected=option, radio=button: self._select(on_select, selected, radio))
            details.addWidget(option_widget)

    def _select(self, on_select, option, button):
        if on_select(option):
            self._selected_button = button
        elif self._selected_button:
            self._selected_button.setChecked(True)


class DriverOptionWidget(QWidget):
    def __init__(self, option, selectable=False):
        super().__init__()
        presentation = driver_option_presentation(option)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        marker = QRadioButton() if selectable else QLabel("●" if presentation.selected else "○")
        self.selection_button = marker if selectable else None
        if selectable:
            marker.setAccessibleName(presentation.title)
        marker.setToolTip(_("Current selection") if presentation.selected else _("Available option"))
        top.addWidget(marker)

        title = QLabel(presentation.title)
        title.setWordWrap(True)
        if presentation.selected:
            font = title.font()
            font.setBold(True)
            title.setFont(font)
        top.addWidget(title, 1)
        layout.addLayout(top)

        if presentation.subtitle:
            subtitle = QLabel(presentation.subtitle)
            subtitle.setWordWrap(True)
            subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(subtitle)

        if presentation.badges:
            badges = QVBoxLayout()
            badges.setSpacing(6)
            for text in presentation.badges:
                badges.addWidget(Badge(text))
            badges.addStretch(1)
            layout.addLayout(badges)


class Badge(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMargin(4)
        font = self.font()
        font.setBold(True)
        self.setFont(font)


def _device_title(device):
    if device.display_name == "Unknown":
        return _("Unknown")
    if device.display_name == "Processor":
        return _("Processor")
    return device.display_name


def _sorted_options(options):
    return sorted(options, key=lambda option: (
        {
            DeviceStatus.RECOMMENDED: 0,
            DeviceStatus.ALTERNATIVE: 1,
            DeviceStatus.MANUALLY_INSTALLED: 2,
            DeviceStatus.NO_DRIVER: 3,
        }[option.status],
        option.package_name or option.option_type.value,
    ))

