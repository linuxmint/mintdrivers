#! /usr/bin/python3
# -*- coding=utf-8 -*-

import gettext
import os
import sys
import apt
import subprocess
import gi
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import GdkPixbuf, Gtk, XApp
from UbuntuDrivers import detect
from aptdaemon import client
from aptdaemon.enums import ERROR_UNKNOWN
from aptdaemon.errors import NotAuthorizedError, TransactionFailed
from aptdaemon.gtk3widgets import AptErrorDialog, AptProgressDialog
import re
import urllib

# i18n
gettext.install("mintdrivers", "/usr/share/linuxmint/locale", names="ngettext")


class Application():

    def __init__(self):

        self.builder = Gtk.Builder()
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

        self.info_bar.set_no_show_all(True)

        self.progress_bar = Gtk.ProgressBar()
        self.box_driver_action.pack_end(self.progress_bar, False, False, 0)
        self.progress_bar.set_visible(False)

        self.needs_restart = False
        self.live_mode = False
        self.apt_client = client.AptClient()

        with open('/proc/cmdline') as f:
            cmdline = f.read()
            if ((not "boot=casper" in cmdline) and (not "boot=live" in cmdline)):
                print ("Post-install mode detected")
                self.info_bar_label.set_text(_("Drivers cannot be installed.\nPlease connect to the Internet or insert the Linux Mint installation DVD (or USB stick)."))
                self.check_internet_or_live_dvd()
                self.button_info_bar.connect("clicked", self.check_internet_or_live_dvd)
            else:
                print ("Live mode detected")
                self.live_mode = True
                self.info_bar.hide()
                self.update_cache()

    def update_cache(self):
        self.update_transaction = self.apt_client.update_cache()
        self.update_transaction.connect("finished", self._on_cache_update_finished)
        dia = AptProgressDialog(self.update_transaction)
        dia.set_transient_for(self.window_main)
        dia.set_modal(True)
        dia.run(close_on_finished=True, show_error=True,
                reply_handler=lambda: True,
                error_handler=self.on_error,
                )

    def on_error(self, error):
        if isinstance(error, NotAuthorizedError):
                # Silently ignore auth failures
            return
        elif not isinstance(error, TransactionFailed):
            # Catch internal errors of the client
            error = TransactionFailed(ERROR_UNKNOWN, str(error))
        dia = AptErrorDialog(error)
        dia.run()
        dia.hide()
        self.apt_cache = apt.Cache()

    def _on_cache_update_finished(self, transaction, exit_state):
        self.show_drivers()

    def quit_application(self, widget=None, event=None):
        self.clean_up_media_cdrom()
        Gtk.main_quit()

    def clean_up_media_cdrom(self):
        if os.path.exists("/media/cdrom"):
            print ("unmounting /media/cdrom...")
            os.system("umount /media/cdrom")
            print ("removing /media/cdrom...")
            os.system("rm -rf /media/cdrom")
            print ("removing cdrom repository...")
            os.system("sed -i '/deb cdrom/d' /etc/apt/sources.list")

    def check_connectivity(self, reference):
        try:
            urllib.request.urlopen(reference, timeout=10)
            return True
        except:
            return False

    def check_internet_or_live_dvd(self, widget=None):

        try:
            print ("Checking connectivity or live media...")

            # We either get drivers from the Internet of from the liveDVD
            # So check the connection to the Internet or scan for a liveDVD

            if self.check_connectivity("http://archive.ubuntu.com"):
            # We can reach the repository, everything's fine
                print ("Internet connection detected")
                self.info_bar.hide()
                self.update_cache()
                return

            # We can't reach the repository, we need the installation media
            mount_point = None
            mounted_on_media_cdrom = False

            # Find the live media
            try:
                live_medias = subprocess.check_output("find /media | grep README.diskdefines", shell=True)
                live_medias = str(live_medias, encoding='utf8').split("\n")
                for live_media in live_medias:
                    if ("README.diskdefines" in live_media):
                        mount_point = live_media.replace("/README.diskdefines", "") # This is where our live DVD is mounted
                        # Add it to apt-cdrom
                        p = subprocess.Popen(["sudo", "apt-cdrom", "-d", mount_point, "-m", "add"], stderr=subprocess.PIPE)
                        stderr = p.communicate()
                        mounted_on_media_cdrom = True
                        if 'No CD-ROM could be auto-detected or found using the default mount point' in stderr[1]:
                           mounted_on_media_cdrom = False
            except:
                pass

            if mount_point is None:
                # Not mounted..
                self.info_bar.show()
                return

            if mounted_on_media_cdrom == False:
                # Mounted, but not in the right place...
                print ("Binding mount %s to /media/cdrom" % mount_point)
                self.clean_up_media_cdrom()
                os.system("mkdir -p /media/cdrom")
                p = subprocess.Popen(["mount", "--bind", mount_point, "/media/cdrom"], stderr=subprocess.PIPE)
                stderr = p.communicate()

            # It should now be mounted to /media/cdrom, else something went wrong..
            if os.path.exists("/media/cdrom/README.diskdefines"):
                print ("Live media detected")
                self.info_bar.hide()
                self.update_cache()
            else:
                self.info_bar.show()
        except (NotAuthorizedError, TransactionFailed) as e:
            print("An error occurred: {}".format(e))
            self.info_bar.show()

    def on_driver_changes_progress(self, transaction, progress):
        #print(progress)
        self.button_driver_revert.set_visible(False)
        self.button_driver_apply.set_visible(False)
        self.button_driver_restart.set_visible(False)
        self.button_driver_cancel.set_visible(True)
        self.progress_bar.set_visible(True)
        self.progress_bar.set_visible(True)

        self.label_driver_action.set_label(_("Applying changes..."))
        self.progress_bar.set_fraction(progress / 100.0)
        XApp.set_window_progress(self.window_main, progress)

    def on_driver_changes_finish(self, transaction, exit_state):
        self.needs_restart = True
        self.progress_bar.set_visible(False)
        self.clear_changes()
        self.apt_cache = apt.Cache()
        self.set_driver_action_status()
        self.update_label_and_icons_from_status()
        self.button_driver_revert.set_visible(True)
        self.button_driver_apply.set_visible(True)
        self.button_driver_cancel.set_visible(False)
        self.scrolled_window_drivers.set_sensitive(True)
        XApp.set_window_progress(self.window_main, 0)

    def on_driver_changes_error(self, transaction, error_code, error_details):
        self.on_driver_changes_revert()
        self.set_driver_action_status()
        self.update_label_and_icons_from_status()
        self.button_driver_revert.set_visible(True)
        self.button_driver_apply.set_visible(True)
        self.button_driver_cancel.set_visible(False)
        self.scrolled_window_drivers.set_sensitive(True)
        self.on_error(transaction.error)
        XApp.set_window_progress(self.window_main, 0)

    def on_driver_changes_cancellable_changed(self, transaction, cancellable):
        self.button_driver_cancel.set_sensitive(cancellable)

    def on_driver_changes_apply(self, button):

        installs = []
        removals = []

        for pkg in self.driver_changes:
            if pkg.is_installed:
                removals.append(pkg.shortname)
                print ("Remove %s" % pkg.shortname)
            else:
                installs.append(pkg.shortname)
                print ("Install %s" % pkg.shortname)
                try:
                    for recommended in pkg.candidate.recommends:
                        recommended_name = recommended[0].name
                        if recommended_name in self.apt_cache:
                            recommended_pkg = self.apt_cache[recommended_name]
                            if recommended_pkg.is_installed:
                                print ("Skipped %s (recommended but already installed)" % recommended_name)
                            else:
                                installs.append(recommended_name)
                                print ("Install %s (recommended)" % recommended_name)
                except:
                    print ("A problem occurred, some recommended deps might not get installed")

        try:
            self.transaction = self.apt_client.commit_packages(install=installs, remove=removals,
                                                               reinstall=[], purge=[], upgrade=[], downgrade=[])
            self.transaction.set_allow_unauthenticated(True)
            self.transaction.connect("progress-changed", self.on_driver_changes_progress)
            self.transaction.connect("cancellable-changed", self.on_driver_changes_cancellable_changed)
            self.transaction.connect("finished", self.on_driver_changes_finish)
            self.transaction.connect("error", self.on_driver_changes_error)
            self.transaction.run()
            self.button_driver_revert.set_sensitive(False)
            self.button_driver_apply.set_sensitive(False)
            self.scrolled_window_drivers.set_sensitive(False)
        except (NotAuthorizedError, TransactionFailed) as e:
            print("Warning: install transaction not completed successfully: {}".format(e))

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
        self.transaction.cancel()
        self.clear_changes()

    def on_driver_restart_clicked(self, button_restart):
        self.clean_up_media_cdrom()
        subprocess.call(['reboot'])

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

    def gather_device_data(self, device):
        '''Get various device data used to build the GUI.

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
        '''

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

        for pkg_driver_name in device['drivers']:
            current_driver = device['drivers'][pkg_driver_name]

            # get general status
            driver_status = 'alternative'
            try:
                if current_driver['recommended'] and current_driver['from_distro']:
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
                description_line1 = "<b>%s</b>" % pkg.shortname
                description_line2 = "<small>%s</small> %s" % (_("Version"), pkg.candidate.version)
                description_line3 = "<small>%s</small>" % pkg.candidate.summary
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

        return (overall_status, icon, returned_drivers)

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

        return (GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/linuxmint/mintdrivers/icons/%s.svg" % icon, 48, -1))

    def get_cpu_name(self):
        with open("/proc/cpuinfo") as cpuinfo:
            for line in cpuinfo:
                if "model name" in line:
                    return re.sub( ".*model name.*:", "", line, 1).strip()
        return _("Processor")

    def show_drivers(self):
        self.apt_cache = apt.Cache()
        self.devices = detect.system_device_drivers()
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
            widget = Gtk.Label(device_name)
            widget.set_halign(Gtk.Align.START)
            device_detail.pack_start(widget, True, False, 0)
            widget = Gtk.Label("<small>{}</small>".format(overall_status))
            widget.set_halign(Gtk.Align.START)
            widget.set_use_markup(True)
            device_detail.pack_start(widget, True, False, 0)
            self.dynamic_device_status[device] = (driver_status, widget)

            option_group = None
            # define the order of introspection
            for section in ('recommended', 'alternative', 'manually_installed', 'no_driver'):
                for driver in sorted(drivers[section], key=lambda x: self.sort_string(drivers[section], x)):
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

        self.ui_building = False
        self.box_driver_detail.show_all()
        self.set_driver_action_status()

    def sort_string(self, drivers, x):
        value = drivers[x]['description']
        try:
            value = "%s %s" % (not drivers[x]['free'], value)
        except:
            pass #best effort (some driver options don't have a 'free' flag, and that's alright)
        return value

    def update_label_and_icons_from_status(self):
        '''Update the current label and icon, computing the new device status'''

        for device in self.devices:
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
            self.label_driver_action.set_label(ngettext(
                "%(count)d proprietary driver in use.",
                "%(count)d proprietary drivers in use.",
                self.nonfree_drivers)
                % {'count': self.nonfree_drivers})
        else:
            self.label_driver_action.set_label(_("No proprietary drivers are in use."))

if __name__ == "__main__":
    Application()
    Gtk.main()
