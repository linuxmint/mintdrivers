#! /usr/bin/python3
# -*- coding=utf-8 -*-

import gettext
import locale
import os
import sys
import apt
import subprocess
import gi
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
gi.require_version("PackageKitGlib", "1.0")
from gi.repository import GdkPixbuf, Gtk, XApp, Gio, GLib
from gi.repository import PackageKitGlib as packagekit
from UbuntuDrivers import detect
import psutil
import re
import urllib
import threading

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
        self.builder.get_object("button_mount_media").connect("clicked", self.on_mount_media_button)
        self.builder.get_object("button_offline").connect("clicked", self.check_internet_or_live_media)

        self.progress_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self.box_driver_action.pack_end(self.progress_bar, True, True, 0)
        self.progress_bar.set_visible(False)

        self.needs_restart = False
        self.live_mode = False

        self.show_page("refresh_page")

        with open('/proc/cmdline') as f:
            cmdline = f.read()
            if ("boot=casper" in cmdline) or ("boot=live" in cmdline):
                print ("Live mode detected")
                self.live_mode = True
                self.update_cache()
            else:
                self.check_internet_or_live_media()

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

        # it thinks it's a PkClientError but it's really PkErrorEnum
        # the GError code is set to 0xFF + code
        real_code = error.code
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
        self.cleanup_live_media()
        Gtk.main_quit()

    def cleanup_live_media(self):
        subprocess.call(["sudo", "mintdrivers-remove-live-media"])

    def check_connectivity(self, reference):
        try:
            urllib.request.urlopen(reference, timeout=10)
            return True
        except:
            return False

    @idle
    def check_internet_or_live_media(self, widget=None):
        self.show_page("refresh_page")
        print ("Checking Internet connectivity...")
        try:
            urllib.request.urlopen("http://archive.ubuntu.com", timeout=10)
            # We're online
            print ("  --> Computer is online")
            self.update_cache()
            return
        except:
            print ("  --> Computer is offline")

        # We're offline, let's look for a live media
        print ("Checking for a live media...")
        mount_point = None
        partitions = psutil.disk_partitions()
        for p in partitions:
            if p.fstype == "iso9660":
                mount_point = p.mountpoint
                print ("  --> Found: %s at %s" % (p.device, p.mountpoint))
                break

        if mount_point is None:
            # Offline and no live media, show the offline page
            print ("  --> None found.")
            self.show_page("offline_page")
            return

        # We're offline but an ISO was detected
        # Let's make sure it's mounted as a repository
        if os.path.exists("/media/mintdrivers/README.diskdefines"):
            print ("  --> Mounted in /media/mintdrivers")
            self.update_cache()
        else:
            print ("  --> Not mounted in /media/mintdrivers")
            self.show_page("media_page")

    def on_mount_media_button(self, button):
        print("Mounting live media")
        self.show_page("refresh_page")
        self.mount_live_media()

    @_async
    def mount_live_media(self):
        subprocess.call(["/usr/bin/pkexec", "mintdrivers-add-live-media"])
        self.check_internet_or_live_media()

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
        results = None
        errors = False
        try:
            results = self.pk_task.generic_finish(result)
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
            self.needs_restart = (not errors)
            self.progress_bar.set_visible(False)
            self.apt_cache = apt.Cache()
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

        for pkg in self.driver_changes:
            if pkg.is_installed:
                removals.append(self.get_package_id(pkg.installed))
                # The main NVIDIA package is only a metapackage.
                # We need to collect its dependencies, so that
                # we can uninstall the driver properly.
                if 'nvidia' in pkg.shortname:
                    for dep in self.get_dependencies(self.apt_cache, pkg.shortname, 'nvidia'):
                        dep_pkg = self.apt_cache[dep]
                        if dep_pkg.is_installed:
                            removals.append(self.get_package_id(dep_pkg.installed))
            else:
                installs.append(self.get_package_id(pkg.candidate))

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
        self.cleanup_live_media()
        subprocess.call(['systemctl', 'reboot'])

    def clear_changes(self):
        self.orig_selection = {}
        self.driver_changes = []

    def on_driver_selection_changed(self, button, modalias, pkg_name=None):
        if self.ui_building:
            return

        pkg = None
        try:
            if pkg_name:
                pkg = self.apt_cache[pkg_name]
        except KeyError:
            pass

        if button.get_active():
            if pkg in self.driver_changes:
                self.driver_changes.remove(pkg)

            if (pkg is not None
                    and modalias in self.orig_selection
                    and button is not self.orig_selection[modalias]):
                self.driver_changes.append(pkg)
        else:
            if pkg in self.driver_changes:
                self.driver_changes.remove(pkg)

            # for revert; to re-activate the original radio buttons.
            if modalias not in self.orig_selection:
                self.orig_selection[modalias] = button

            if (pkg is not None
                    and pkg not in self.driver_changes
                    and pkg.is_installed):
                self.driver_changes.append(pkg)

        self.button_driver_revert.set_sensitive(bool(self.driver_changes))
        self.button_driver_apply.set_sensitive(bool(self.driver_changes))


    def get_package_id(self, ver):
        """ Return the PackageKit package id """
        assert isinstance(ver, apt.package.Version)
        return "%s;%s;%s;" % (ver.package.shortname, ver.version, ver.package.architecture())

    @staticmethod
    def get_dependencies(apt_cache, package_name, pattern=None):
        """ Get the package dependencies, which can be filtered out by a pattern """
        dependencies = []
        for or_group in apt_cache[package_name].candidate.dependencies:
          for dep in or_group:
            if dep.rawtype in ["Depends", "PreDepends"]:
              dependencies.append(dep.name)
        if pattern:
          dependencies = [ x for x in dependencies if x.find(pattern) != -1 ]
        return dependencies

    def gather_device_data(self, device):
        """Get various device data used to build the GUI.

          return a tuple of (overall_status string, icon, drivers dict).
          the drivers dict is using this form:
            {"recommended/alternative": {pkg_name: {
                                                      'selected': True/False
                                                      'description': 'description'
                                                      'builtin': True/False,
                                                      'free': True/False
                                                    }
                                         }}
             "manually_installed": {"manual": {'selected': True, 'description': description_string}}
             "no_driver": {"no_driver": {'selected': True/False, 'description': description_string}}

             Please note that either manually_installed and no_driver are set to None if not applicable
             (no_driver isn't present if there are builtins)
        """

        possible_overall_status = {
            'recommended': (_("This device is using the recommended driver."), "recommended-driver"),
            'alternative': (_("This device is using an alternative driver."), "other-driver"),
            'manually_installed': (_("This device is using a manually-installed driver."), "other-driver"),
            'no_driver': (_("This device is not working."), "disable-device")
        }

        returned_drivers = {'recommended': {}, 'alternative': {}, 'manually_installed': {}, 'no_driver': {}}
        have_builtin = False
        one_selected = False
        try:
            if device['manual_install']:
                returned_drivers['manually_installed'] = {True: {'selected': True,
                                                                 'description': _("Continue using a manually installed driver")}}
        except KeyError:
            pass

        # -open nvidia drivers are recommended now over normal ones. Go thru the list and get the version of the recommended one,
        # then we can flag the non-'open' one instead.
        new_recommended = None
        for pkg_driver_name in device['drivers']:
            current_driver = device['drivers'][pkg_driver_name]
            try:
                if current_driver['recommended'] and current_driver['from_distro']:
                    driver_status = 'recommended'
                    if pkg_driver_name.endswith("-open"):
                        new_recommended = pkg_driver_name.replace("-open", "")
            except KeyError:
                pass

        for pkg_driver_name in device['drivers']:
            current_driver = device['drivers'][pkg_driver_name]

            # get general status
            driver_status = 'alternative'
            try:
                if (current_driver['recommended'] and current_driver['from_distro']) or pkg_driver_name == new_recommended:
                    driver_status = 'recommended'
            except KeyError:
                pass

            builtin = False
            try:
                if current_driver['builtin']:
                    builtin = True
                    have_builtin = True
            except KeyError:
                pass

            try:
                pkg = self.apt_cache[pkg_driver_name]
                installed = pkg.is_installed
                if installed:
                    version = pkg.installed.version
                    summary = pkg.installed.summary
                else:
                    version = pkg.candidate.version
                    summary = pkg.candidate.summary
                description_line1 = "<b>%s</b>" % pkg.shortname
                description_line2 = "<small>%s</small> %s" % (_("Version"), version)
                description_line3 = "<small>%s</small>" % summary
                if driver_status == 'recommended':
                    description_line1 = "%s <b><small><span foreground='#58822B'>(%s)</span></small></b>" % (description_line1, _("recommended"))
                if current_driver['free'] and pkg.shortname != "bcmwl-kernel-source" and (not pkg.shortname.startswith("nvidia-")):
                    description_line1 = "%s <b><small><span foreground='#717bbd'>(%s)</span></small></b>" % (description_line1, _("open-source"))
                if pkg.shortname.startswith("firmware-b43"):
                    # B43 requires a connection to the Internet
                    description_line1 = "%s <b><small><span foreground='#9f5258'>(%s)</span></small></b>" % (description_line1, _("requires a connection to the Internet"))
                description = "%s\n%s\n%s" % (description_line1, description_line2, description_line3)
            except KeyError:
                print("WARNING: a driver ({}) doesn't have any available package associated: {}".format(pkg_driver_name, current_driver))
                continue

            selected = False
            if not builtin and not returned_drivers['manually_installed']:
                selected = installed
                if installed:
                    selected = True
                    one_selected = True

            returned_drivers[driver_status].setdefault(pkg_driver_name, {'selected': selected,
                                                                         'description': description,
                                                                         'builtin': builtin,
                                                                         'free': current_driver['free']})

        # adjust making the needed addition
        if not have_builtin:
            selected = False
            if not one_selected:
                selected = True
            returned_drivers["no_driver"] = {True: {'selected': selected,
                                                    'description': _("Do not use the device")}}
        else:
            # we have a builtin and no selection: builtin is the selected one then
            if not one_selected:
                for section in ('recommended', 'alternative'):
                    for pkg_name in returned_drivers[section]:
                        if returned_drivers[section][pkg_name]['builtin']:
                            returned_drivers[section][pkg_name]['selected'] = True

        # compute overall status
        for section in returned_drivers:
            for keys in returned_drivers[section]:
                if returned_drivers[section][keys]['selected']:
                    (overall_status, icon) = possible_overall_status[section]

        return overall_status, icon, returned_drivers

    def get_device_icon(self, device):
        vendor = device.get('vendor', _('Unknown'))
        model = device.get('model', _('Unknown'))
        icon = "generic"
        if "nvidia" in vendor.lower():
            icon = "nvidia"
        elif "radeon" in vendor.lower() or "radeon" in model.lower() or "Advanced Micro Devices" in vendor or "AMD" in vendor or "ATI" in vendor:
            icon = "ati"
        elif "broadcom" in vendor.lower():
            icon = "broadcom"
        elif "virtualbox" in vendor.lower() or "virtualbox" in model.lower():
            icon = "virtualbox"

        if "intel-microcode" in device['drivers']:
            icon = "intel"
        elif "amd64-microcode" in device['drivers']:
            icon = "amd"

        return GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/linuxmint/mintdrivers/icons/%s.svg" % icon, 48, -1)

    def get_cpu_name(self):
        with open("/proc/cpuinfo") as cpuinfo:
            for line in cpuinfo:
                if "model name" in line:
                    return re.sub( ".*model name.*:", "", line, 1).strip()
        return _("Processor")

    @_async
    def get_drivers_async(self):
        self.apt_cache = apt.Cache()
        self.devices = detect.system_device_drivers()
        if self.test_mode:
            dummy_device = {
                'modalias': '',
                'vendor': 'Linux Mint', 'model': 'Dummy Test Device',
                'drivers': {
                    'mint-dev-pkg': {'free': False, 'from_distro': True, 'recommended': True},
                    'mint-dev-pkg-debconf': {'free': False, 'from_distro': True, 'recommended': False},
                    'linux-generic': {'free': True, 'builtin': True, 'from_distro': True, 'recommended': False}}
                }
            self.devices['dummy'] = dummy_device
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
        if len(self.devices) != 0:
            for device in sorted(self.devices.keys()):
                (overall_status, icon, drivers) = self.gather_device_data(self.devices[device])
                is_cpu = False
                if "intel-microcode" in self.devices[device]['drivers'] or "amd64-microcode" in self.devices[device]['drivers']:
                    is_cpu = True
                    overall_status = _("Processor microcode")
                brand_icon = Gtk.Image()
                brand_icon.set_valign(Gtk.Align.START)
                brand_icon.set_halign(Gtk.Align.CENTER)
                brand_icon.set_from_pixbuf(self.get_device_icon(self.devices[device]))
                driver_status = Gtk.Image()
                driver_status.set_valign(Gtk.Align.START)
                driver_status.set_halign(Gtk.Align.CENTER)
                driver_status.set_from_icon_name(icon, Gtk.IconSize.MENU)
                device_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
                device_box.pack_start(brand_icon, False, False, 6)
                device_detail = Gtk.Box(spacing=6, orientation=Gtk.Orientation.VERTICAL)
                device_box.pack_start(device_detail, True, True, 0)
                model_name = self.devices[device].get('model', None)
                vendor_name = self.devices[device].get('vendor', None)
                if is_cpu:
                    device_name = self.get_cpu_name()
                elif vendor_name is None and model_name is None:
                    device_name = _("Unknown")
                elif vendor_name is None:
                    device_name = model_name
                elif model_name is None:
                    device_name = vendor_name
                else:
                    device_name = "%s: %s" % (vendor_name, model_name)
                if "vmware" in device_name.lower() or "virtualbox" in device_name.lower():
                    print ("Ignoring device %s" % device_name)
                    continue
                if drivers["manually_installed"]:
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
                self.dynamic_device_status[device] = (driver_status, widget)

                option_group = None
                # define the order of introspection
                for section in ('recommended', 'alternative', 'manually_installed', 'no_driver'):
                    for driver in sorted(drivers[section], key=lambda x: self.sort_string(drivers[section], x), reverse=True):
                        if str(driver).startswith("nvidia-driver") and str(driver).endswith(("-server", "-open")):
                            print("Ignoring server or open NVIDIA driver: ", driver)
                            continue
                        radio_button = Gtk.RadioButton.new(None)
                        label = Gtk.Label()
                        label.set_markup(drivers[section][driver]['description'])
                        radio_button.add(label)
                        if option_group:
                            radio_button.join_group(option_group)
                        else:
                            option_group = radio_button
                        device_detail.pack_start(radio_button, True, False, 0)
                        radio_button.set_active(drivers[section][driver]['selected'])

                        if section == 'no_driver':
                            self.no_drv.append(radio_button)
                            if is_cpu:
                                label.set_markup(_("Do not update the CPU microcode"))
                        if section in ('manually_install', 'no_driver') or ('builtin' in drivers[section][driver] and drivers[section][driver]['builtin']):
                            radio_button.connect("toggled", self.on_driver_selection_changed, device)
                        else:
                            radio_button.connect("toggled", self.on_driver_selection_changed, device, driver)
                        if drivers['manually_installed'] and section != 'manually_installed' and "firmware" not in str(driver):
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

    def sort_string(self, drivers, x):
        value = x
        try:
            value = "%s %s" % (not drivers[x]['free'], value)
        except:
            pass #best effort (some driver options don't have a 'free' flag, and that's alright)
        return value

    def update_label_and_icons_from_status(self):
        """Update the current label and icon, computing the new device status"""

        for device in self.devices:
            if device in self.dynamic_device_status.keys():
                (overall_status, icon, drivers) = self.gather_device_data(self.devices[device])
                (driver_status, widget) = self.dynamic_device_status[device]
                driver_status.set_from_icon_name(icon, Gtk.IconSize.MENU)
                widget.set_label("<small>{}</small>".format(overall_status))

    def set_driver_action_status(self):
        # Update the label in case we end up having some kind of proprietary driver in use.
        if (not self.live_mode) and (os.path.exists('/var/run/reboot-required') or self.needs_restart):
            self.label_driver_action.set_label(_("You need to restart the computer to complete the driver changes."))
            self.button_driver_restart.set_visible(True)
            self.window_main.set_urgency_hint(True)
            return

        self.nonfree_drivers = 0
        for device in self.devices:
            for pkg_name in self.devices[device]['drivers']:
                pkg = self.apt_cache[pkg_name]
                if (not self.devices[device]['drivers'][pkg_name]['free'] or pkg_name == "bcmwl-kernel-source") and pkg.is_installed:
                    self.nonfree_drivers = self.nonfree_drivers + 1

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
