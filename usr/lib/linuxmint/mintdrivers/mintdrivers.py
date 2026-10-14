#! /usr/bin/python3
# -*- coding=utf-8 -*-

import gettext
import locale
import os
import sys
import subprocess
import gi
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
gi.require_version("PackageKitGlib", "1.0")
from gi.repository import Gtk, XApp, Gio, GLib
from gi.repository import PackageKitGlib as packagekit
import socket
import threading
from backend import (
    DeviceStatus,
    DriverBackend,
    DriverOptionType,
)
from backend.drivers import TEST_PACKAGE_OVERRIDES, make_test_device

# Used as a decorator to run things in the background
def _async(func):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        return thread
    return wrapper

# Used as a decorator to run things in the main loop, from another thread
def idle(func):
    def wrapper(*args):
        GLib.idle_add(func, *args)
    return wrapper

APP = 'mintdrivers'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

class Application:

    def __init__(self):

        self.test_mode = False
        if len(sys.argv) > 1 and sys.argv[1] == "test":
            self.test_mode = True
            print("Test mode detected, adding a dummy device.")
        self.backend = DriverBackend(
            extra_devices={"dummy": make_test_device()} if self.test_mode else None,
            package_overrides=TEST_PACKAGE_OVERRIDES if self.test_mode else None)

        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file("/usr/share/linuxmint/mintdrivers/main.ui")
        self.builder.connect_signals(self)
        for o in self.builder.get_objects():
            if issubclass(type(o), Gtk.Buildable):
                name = Gtk.Buildable.get_name(o)
                setattr(self, name, o)
            else:
                print("can not get name for object '%s'" % o)

        self.window_main.show()

        self.window_main.set_title(_("Driver Manager"))

        self.window_main.connect("delete_event", self.quit_application)

        self.button_driver_revert = Gtk.Button(label=_("Re_vert"), use_underline=True)
        self.button_driver_revert.connect("clicked", self.on_driver_changes_revert)
        self.button_driver_apply = Gtk.Button(label=_("_Apply Changes"), use_underline=True)
        self.button_driver_apply.connect("clicked", self.on_driver_changes_apply)
        self.button_driver_cancel = Gtk.Button(label=_("_Cancel"), use_underline=True)
        self.button_driver_cancel.connect("clicked", self.on_driver_changes_cancel)
        self.button_driver_restart = Gtk.Button(label=_("_Restart..."), use_underline=True)
        self.button_driver_restart.connect("clicked", self.on_driver_restart_clicked)
        self.button_driver_revert.set_sensitive(False)
        self.button_driver_revert.set_visible(True)
        self.button_driver_apply.set_sensitive(False)
        self.button_driver_apply.set_visible(True)
        self.button_driver_cancel.set_visible(False)
        self.button_driver_restart.set_visible(False)
        self.box_driver_action.pack_end(self.button_driver_apply, False, False, 0)
        self.box_driver_action.pack_end(self.button_driver_revert, False, False, 0)
        self.box_driver_action.pack_end(self.button_driver_restart, False, False, 0)
        self.box_driver_action.pack_end(self.button_driver_cancel, False, False, 0)

        self.builder.get_object("error_button").connect("clicked", self.on_error_button)
        self.builder.get_object("button_offline").connect("clicked", self.check_internet)

        self.progress_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self.box_driver_action.pack_end(self.progress_bar, True, True, 0)
        self.progress_bar.set_visible(False)

        self.needs_restart = False
        self.needs_broadcom_reload = False
        self.live_mode = False

        self.show_page("refresh_page")

        with open('/proc/cmdline') as f:
            cmdline = f.read()
            if ("boot=casper" in cmdline) or ("boot=live" in cmdline):
                print ("Live mode detected")
                self.live_mode = True
                self.update_cache()
            else:
                self.check_internet()

    def show_page(self, page):
        if page == "refresh_page":
            self.builder.get_object("spinner").start()
        else:
            self.builder.get_object("spinner").stop()
        self.builder.get_object("stack").set_visible_child_name(page)

    def on_error_button(self, button):
        self.show_page("drivers_page")

    def update_cache(self):
        print("Updating cache")
        self.show_page("refresh_page")
        task = packagekit.Task()
        task.refresh_cache_async(True, Gio.Cancellable(), self.on_cache_update_progress, (None, ), self.on_cache_update_finished, (None, ))

    def on_error(self, error):
        # Returns False if the error was from cancelling or failing to authenticate.
        # This will bring the ui back to pre-apply state. Returning True will reset
        # entirely.

        # it thinks it's a PkClientError, but it's really PkErrorEnum
        # the GError code is set to 0xFF + code
        if error.code >= 0xFF:
            real_code = error.code - 0xFF

            if real_code == packagekit.ErrorEnum.NOT_AUTHORIZED:
                # Silently ignore auth failures or cancellation.
                return False

        self.show_page("error_page")
        self.builder.get_object("error_label").set_label(error.message)
        return True

    def on_cache_update_progress(self, progress, ptype, data=None):
        pass

    def on_cache_update_finished(self, source, result, data=None):
        print("Cache updated")
        XApp.set_window_progress(self.window_main, 0)
        self.get_drivers_async()

    def quit_application(self, widget=None, event=None):
        Gtk.main_quit()

    @idle
    def check_internet(self, widget=None):
        self.show_page("refresh_page")
        print ("Checking Internet connectivity...")
        try:
            socket.create_connection(("archive.ubuntu.com", 443), timeout=10)
            # We're online
            print ("  --> Computer is online")
            self.update_cache()
            return
        except:
            print ("  --> Computer is offline")
            self.show_page("offline_page")

    def on_driver_changes_progress(self, progress, ptype, data=None):
        self.button_driver_revert.set_visible(False)
        self.button_driver_apply.set_visible(False)
        self.button_driver_restart.set_visible(False)
        self.button_driver_cancel.set_visible(True)
        self.progress_bar.set_visible(True)
        self.progress_bar.set_visible(True)

        if progress.get_status() == packagekit.StatusEnum.DOWNLOAD:
            self.label_driver_action.set_label(_("Downloading drivers..."))
        elif progress.get_status() == packagekit.StatusEnum.INSTALL:
            self.label_driver_action.set_label(_("Installing drivers..."))
        elif progress.get_status() == packagekit.StatusEnum.REMOVE:
            self.label_driver_action.set_label(_("Removing drivers..."))
        elif progress.get_status() == packagekit.StatusEnum.CANCEL:
            self.label_driver_action.set_label(_("Cancelling..."))
        elif progress.get_status() == packagekit.StatusEnum.LOADING_CACHE:
            self.label_driver_action.set_label(_("Loading cache..."))
        else:
            self.label_driver_action.set_label("")
        if ptype == packagekit.ProgressType.PERCENTAGE:
            prog_value = progress.get_property('percentage')
            self.progress_bar.set_fraction(prog_value / 100.0)
            XApp.set_window_progress(self.window_main, prog_value)

    def on_driver_changes_finish(self, source, result, installs):
        errors = False
        try:
            self.pk_task.generic_finish(result)
        except GLib.Error as e:
            errors = True
            if self.on_error(e):
                # real failure
                self.on_driver_changes_revert()
                self.clear_changes()
            else:
                self.button_driver_revert.set_sensitive(bool(self.driver_changes))
                self.button_driver_apply.set_sensitive(bool(self.driver_changes))

        if installs is None or len(installs) == 0 or errors:
            if self.needs_broadcom_reload:
                print("Reloading Broadcom modules")
                subprocess.call(["sudo", "mintdrivers-load-broadcom-modules"])
            self.needs_restart = (not errors)
            self.progress_bar.set_visible(False)
            self.backend.refresh_package_cache()
            self.devices = self.backend.get_devices()
            self.set_driver_action_status()
            self.update_label_and_icons_from_status()
            self.button_driver_revert.set_visible(True)
            self.button_driver_apply.set_visible(True)
            self.button_driver_cancel.set_visible(False)
            self.scrolled_window_drivers.set_sensitive(True)
            XApp.set_window_progress(self.window_main, 0)
        else:
            print("Installing", installs)
            self.pk_task.install_packages_async(installs,
                    self.cancellable,  # cancellable
                    self.on_driver_changes_progress,
                    (None, ),  # progress data
                    self.on_driver_changes_finish,  # GAsyncReadyCallback
                    None  # callback data
             )

    def on_driver_changes_apply(self, button):
        self.pk_task = packagekit.Task()
        installs = []
        removals = []

        for package_name in self.driver_changes:
            if self.backend.is_package_installed(package_name):
                removals.append(self.backend.get_packagekit_id(package_name, installed=True))
                # The main NVIDIA package is only a metapackage.
                # We need to collect its dependencies, so that
                # we can uninstall the driver properly.
                if 'nvidia' in package_name:
                    removals.extend(self.backend.get_installed_nvidia_dependency_ids(package_name))
            else:
                installs.append(self.backend.get_packagekit_id(package_name, installed=False))
                if package_name == "broadcom-sta-dkms":
                    self.needs_broadcom_reload = True

        self.cancellable = Gio.Cancellable()
        try:
            if len(removals) > 0:
                try:
                    # Try to purge (Mint specific version of packagekit)
                    print("Purging", removals)
                    self.pk_task.purge_packages_async(removals,
                                False,  # allow deps
                                True,  # autoremove
                                self.cancellable,  # cancellable
                                self.on_driver_changes_progress,
                                (None, ),  # progress data
                                self.on_driver_changes_finish,  # callback ready
                                installs  # callback data
                     )
                except:
                    # If purging isn't supported, just remove
                    print("Couldn't purge! Removing", removals)
                    self.pk_task.remove_packages_async(removals,
                                False,  # allow deps
                                True,  # autoremove
                                self.cancellable,  # cancellable
                                self.on_driver_changes_progress,
                                (None, ),  # progress data
                                self.on_driver_changes_finish,  # callback ready
                                installs  # callback data
                     )
            elif len(installs) > 0:
                print("Installing", installs)
                self.pk_task.install_packages_async(installs,
                        self.cancellable,  # cancellable
                        self.on_driver_changes_progress,
                        (None, ),  # progress data
                        self.on_driver_changes_finish,  # GAsyncReadyCallback
                        None  # callback data
                 )

            self.button_driver_revert.set_sensitive(False)
            self.button_driver_apply.set_sensitive(False)
            self.scrolled_window_drivers.set_sensitive(False)
        except Exception as e:
            print("Warning: install not completed successfully: {}".format(e))

    def on_driver_changes_revert(self, button_revert=None):

        # HACK: set all the "Do not use" first; then go through the list of the
        #       actually selected drivers.
        for button in self.no_drv:
            button.set_active(True)

        for alias in self.orig_selection:
            button = self.orig_selection[alias]
            button.set_active(True)

        self.clear_changes()

        self.button_driver_revert.set_sensitive(False)
        self.button_driver_apply.set_sensitive(False)

    def on_driver_changes_cancel(self, button_cancel):
        self.cancellable.cancel()
        self.clear_changes()

    def on_driver_restart_clicked(self, button_restart):
        subprocess.call(['systemctl', 'reboot'])

    def clear_changes(self):
        self.orig_selection = {}
        self.driver_changes = []

    def on_driver_selection_changed(self, button, modalias, pkg_name=None):
        if self.ui_building:
            return

        if button.get_active():
            if pkg_name in self.driver_changes:
                self.driver_changes.remove(pkg_name)

            if (pkg_name is not None
                    and modalias in self.orig_selection
                    and button is not self.orig_selection[modalias]):
                self.driver_changes.append(pkg_name)
        else:
            if pkg_name in self.driver_changes:
                self.driver_changes.remove(pkg_name)

            # for revert; to re-activate the original radio buttons.
            if modalias not in self.orig_selection:
                self.orig_selection[modalias] = button

            if (pkg_name is not None
                    and pkg_name not in self.driver_changes
                    and self.backend.is_package_installed(pkg_name)):
                self.driver_changes.append(pkg_name)

        self.button_driver_revert.set_sensitive(bool(self.driver_changes))
        self.button_driver_apply.set_sensitive(bool(self.driver_changes))

    def get_device_icon(self, icon_key):
        from gi.repository import GdkPixbuf
        return GdkPixbuf.Pixbuf.new_from_file_at_size(
            "/usr/share/linuxmint/mintdrivers/icons/%s.svg" % icon_key, 48, -1)

    def format_driver_description(self, option):
        if option.option_type == DriverOptionType.MANUAL:
            return _("Continue using a manually installed driver")
        if option.option_type == DriverOptionType.DISABLE:
            return _("Do not use the device")

        description_line1 = "<b>%s</b>" % option.package_name
        if option.recommended:
            description_line1 = "%s <b><small><span foreground='#58822B'>(%s)</span></small></b>" % (
                description_line1, _("recommended"))
        if option.free and option.package_name != "broadcom-sta-dkms" and not option.package_name.startswith("nvidia-"):
            description_line1 = "%s <b><small><span foreground='#717bbd'>(%s)</span></small></b>" % (
                description_line1, _("open-source"))
        if option.requires_internet:
            description_line1 = "%s <b><small><span foreground='#9f5258'>(%s)</span></small></b>" % (
                description_line1, _("requires a connection to the Internet"))
        return "%s\n<small>%s</small> %s\n<small>%s</small>" % (
            description_line1, _("Version"), option.version, option.summary)

    @_async
    def get_drivers_async(self):
        self.devices = self.backend.get_devices()
        self.show_drivers()

    @idle
    def show_drivers(self):
        self.driver_changes = []
        self.orig_selection = {}
        # HACK: the case where the selection is actually "Do not use"; is a little
        #       tricky to implement because you can't check for whether a package is
        #       installed or any such thing. So let's keep a list of all the
        #       "Do not use" radios, set those active first, then iterate through
        #       orig_selection when doing a Reset.
        self.no_drv = []
        self.nonfree_drivers = 0
        self.ui_building = True
        self.dynamic_device_status = {}
        drivers_found = False
        if self.devices:
            for device in self.devices:
                device_id = device.device_id
                is_cpu = device.is_cpu
                overall_status = {
                    DeviceStatus.RECOMMENDED: _("This device is using the recommended driver."),
                    DeviceStatus.ALTERNATIVE: _("This device is using an alternative driver."),
                    DeviceStatus.MANUALLY_INSTALLED: _("This device is using a manually-installed driver."),
                    DeviceStatus.NO_DRIVER: _("This device is not working."),
                }[device.status]
                if is_cpu:
                    overall_status = _("Processor microcode")
                brand_icon = Gtk.Image()
                brand_icon.set_valign(Gtk.Align.START)
                brand_icon.set_halign(Gtk.Align.CENTER)
                brand_icon.set_from_pixbuf(self.get_device_icon(device.icon_key))
                driver_status = Gtk.Image()
                driver_status.set_valign(Gtk.Align.START)
                driver_status.set_halign(Gtk.Align.CENTER)
                status_icon = {
                    DeviceStatus.RECOMMENDED: "recommended-driver",
                    DeviceStatus.ALTERNATIVE: "other-driver",
                    DeviceStatus.MANUALLY_INSTALLED: "other-driver",
                    DeviceStatus.NO_DRIVER: "disable-device",
                }[device.status]
                driver_status.set_from_icon_name(status_icon, Gtk.IconSize.MENU)
                device_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
                device_box.pack_start(brand_icon, False, False, 6)
                device_detail = Gtk.Box(spacing=6, orientation=Gtk.Orientation.VERTICAL)
                device_box.pack_start(device_detail, True, True, 0)
                if device.display_name == "Unknown":
                    device_name = _("Unknown")
                elif device.display_name == "Processor":
                    device_name = _("Processor")
                else:
                    device_name = device.display_name
                if device.is_virtual:
                    print ("Ignoring device %s" % device_name)
                    continue
                if device.status == DeviceStatus.MANUALLY_INSTALLED:
                    print("Ignoring device: %s (manually_installed)" % device_name)
                    continue
                drivers_found = True
                widget = Gtk.Label(label=device_name)
                widget.set_halign(Gtk.Align.START)
                device_detail.pack_start(widget, True, False, 0)
                widget = Gtk.Label(label="<small>{}</small>".format(overall_status))
                widget.set_halign(Gtk.Align.START)
                widget.set_use_markup(True)
                device_detail.pack_start(widget, True, False, 0)
                self.dynamic_device_status[device_id] = (driver_status, widget)

                option_group = None
                # define the order of introspection
                for section in (DeviceStatus.RECOMMENDED, DeviceStatus.ALTERNATIVE,
                                DeviceStatus.MANUALLY_INSTALLED, DeviceStatus.NO_DRIVER):
                    options = [option for option in device.drivers if option.status == section]
                    for option in sorted(options, key=self.sort_string, reverse=True):
                        radio_button = Gtk.RadioButton.new(None)
                        label = Gtk.Label()
                        label.set_markup(self.format_driver_description(option))
                        radio_button.add(label)
                        if option_group:
                            radio_button.join_group(option_group)
                        else:
                            option_group = radio_button
                        device_detail.pack_start(radio_button, True, False, 0)
                        radio_button.set_active(option.selected)

                        if option.option_type == DriverOptionType.DISABLE:
                            self.no_drv.append(radio_button)
                            if is_cpu:
                                label.set_markup(_("Do not update the CPU microcode"))
                        if (option.package_name is None or option.builtin):
                            radio_button.connect("toggled", self.on_driver_selection_changed, device_id)
                        else:
                            radio_button.connect(
                                "toggled", self.on_driver_selection_changed, device_id, option.package_name)
                        if not option.selectable:
                            radio_button.set_sensitive(False)

                self.box_driver_detail.pack_start(device_box, False, False, 6)

        if drivers_found:
            self.show_page("drivers_page")
        else:
            self.show_page("no_drivers_page")
            print("Your computer does not need any additional drivers")

        self.ui_building = False
        self.box_driver_detail.show_all()
        self.set_driver_action_status()

    @staticmethod
    def sort_string(option):
        return "%s %s" % (not option.free, option.package_name or option.option_type.value)

    def update_label_and_icons_from_status(self):
        """Update the current label and icon, computing the new device status"""

        for device in self.devices:
            if device.device_id in self.dynamic_device_status:
                status_text = {
                    DeviceStatus.RECOMMENDED: _("This device is using the recommended driver."),
                    DeviceStatus.ALTERNATIVE: _("This device is using an alternative driver."),
                    DeviceStatus.MANUALLY_INSTALLED: _("This device is using a manually-installed driver."),
                    DeviceStatus.NO_DRIVER: _("This device is not working."),
                }[device.status]
                status_icon = {
                    DeviceStatus.RECOMMENDED: "recommended-driver",
                    DeviceStatus.ALTERNATIVE: "other-driver",
                    DeviceStatus.MANUALLY_INSTALLED: "other-driver",
                    DeviceStatus.NO_DRIVER: "disable-device",
                }[device.status]
                if device.is_cpu:
                    status_text = _("Processor microcode")
                (driver_status, widget) = self.dynamic_device_status[device.device_id]
                driver_status.set_from_icon_name(status_icon, Gtk.IconSize.MENU)
                widget.set_label("<small>{}</small>".format(status_text))

    def set_driver_action_status(self):
        # Update the label in case we end up having some kind of proprietary driver in use.
        if (not self.live_mode) and (os.path.exists('/var/run/reboot-required') or self.needs_restart):
            self.label_driver_action.set_label(_("You need to restart the computer to complete the driver changes."))
            self.button_driver_restart.set_visible(True)
            self.window_main.set_urgency_hint(True)
            return

        self.nonfree_drivers = self.backend.count_installed_proprietary_drivers()

        if self.nonfree_drivers > 0:
            self.label_driver_action.set_label(gettext.ngettext(
                "%(count)d proprietary driver in use.",
                "%(count)d proprietary drivers in use.",
                self.nonfree_drivers)
                % {'count': self.nonfree_drivers})
        else:
            self.label_driver_action.set_label(_("No proprietary drivers are in use."))

if __name__ == "__main__":
    Application()
    Gtk.main()
