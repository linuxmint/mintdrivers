#! /usr/bin/python3
# -*- coding=utf-8 -*-

import gettext
import os, sys
import apt
import subprocess
from gi.repository import GObject, Gdk, Gtk, Gio
from UbuntuDrivers import detect
from aptdaemon import client
from aptdaemon.errors import NotAuthorizedError, TransactionFailed
import re

gettext.install("mintdrivers", "/usr/share/linuxmint/locale")

# i18n for menu item
menuName = _("Driver Manager")
menuComment = _("Manage the drivers for your devices")

class Application():

  def __init__(self):
            
    self.builder = Gtk.Builder()    
    self.builder.add_from_file("/usr/lib/linuxmint/mintDrivers/main.ui")
    self.builder.connect_signals(self)
    for o in self.builder.get_objects():
        if issubclass(type(o), Gtk.Buildable):
            name = Gtk.Buildable.get_name(o)
            setattr(self, name, o)
        else:
            print("can not get name for object '%s'" % o)

    self.window_main.show()

    self.window_main.set_title(_("Driver Manager"))

    self.window_main.connect("delete_event", Gtk.main_quit)

    self.apt_cache = apt.Cache()
    self.apt_client = client.AptClient()

    self.init_drivers()
    self.show_drivers()       
  
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

  def on_driver_changes_finish(self, transaction, exit_state):
    self.progress_bar.set_visible(False)
    self.clear_changes()
    self.apt_cache = apt.Cache()
    self.set_driver_action_status()
    self.update_label_and_icons_from_status()
    self.button_driver_revert.set_visible(True)
    self.button_driver_apply.set_visible(True)
    self.button_driver_cancel.set_visible(False)
    self.scrolled_window_drivers.set_sensitive(True)

  def on_driver_changes_error(self, transaction, error_code, error_details):
    self.on_driver_changes_revert()
    self.set_driver_action_status()
    self.update_label_and_icons_from_status()
    self.button_driver_revert.set_visible(True)
    self.button_driver_apply.set_visible(True)
    self.button_driver_cancel.set_visible(False)
    self.scrolled_window_drivers.set_sensitive(True)

  def on_driver_changes_cancellable_changed(self, transaction, cancellable):
    self.button_driver_cancel.set_sensitive(cancellable)

  def on_driver_changes_apply(self, button):

    installs = []
    removals = []

    for pkg in self.driver_changes:
      if pkg.is_installed:
        removals.append(pkg.shortname)
      else:
        installs.append(pkg.shortname)

    try:
      self.transaction = self.apt_client.commit_packages(install=installs, remove=removals,
                                                         reinstall=[], purge=[], upgrade=[], downgrade=[])
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
    subprocess.call(['/usr/lib/indicator-session/gtk-logout-helper', '--shutdown'])

  def clear_changes(self):
    self.orig_selection = {}
    self.driver_changes = []

  def init_drivers(self):
    """Additional Drivers tab"""

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

    self.progress_bar = Gtk.ProgressBar()
    self.box_driver_action.pack_end(self.progress_bar, False, False, 0)
    self.progress_bar.set_visible(False)

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
    self.ui_building = False

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
                                                  'builtin': True/False
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
        if driver_status == 'recommended':        
          description = ("<b>%s <small><span foreground='#58822B'>(%s)</span></small></b>\n<small><span foreground='#3c3c3c'>%s</span></small> %s\n<small><span foreground='#3c3c3c'>%s</span></small>") % (pkg.shortname, _("recommended"), _("Version"), pkg.candidate.version, pkg.candidate.summary)
        else:
          description = ("<b>%s</b>\n<small><span foreground='#3c3c3c'>%s</span></small> %s\n<small><span foreground='#3c3c3c'>%s</span></small>") % (pkg.shortname, _("Version"), pkg.candidate.version, pkg.candidate.summary)
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
                                                                   'builtin': builtin})

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
    icon = "generic"    
    if "nvidia" in vendor.lower():
      icon = "nvidia"
    elif "Radeon" in vendor:
      icon = "ati"
    elif "broadcom" in vendor.lower():
      icon = "broadcom"
    elif "virtualbox" in vendor.lower():
      icon = "virtualbox"    
    return ("/usr/lib/linuxmint/mintDrivers/icons/%s.png" % icon)
    

  def show_drivers(self):
    self.ui_building = True
    self.dynamic_device_status = {}
    for device in sorted(self.devices.keys()):
      (overall_status, icon, drivers) = self.gather_device_data(self.devices[device])
      brand_icon = Gtk.Image()
      brand_icon.set_valign(Gtk.Align.START)
      brand_icon.set_halign(Gtk.Align.CENTER)
      brand_icon.set_from_file(self.get_device_icon(self.devices[device]))
      driver_status = Gtk.Image()
      driver_status.set_valign(Gtk.Align.START)
      driver_status.set_halign(Gtk.Align.CENTER)      
      driver_status.set_from_icon_name(icon, Gtk.IconSize.MENU)
      device_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
      device_box.pack_start(brand_icon, False, False, 6)
      device_detail = Gtk.Box(spacing=6, orientation=Gtk.Orientation.VERTICAL)
      device_box.pack_start(device_detail, True, True, 0)      
      widget = Gtk.Label("{}: {}".format(self.devices[device].get('vendor', _('Unknown')), self.devices[device].get('model', _('Unknown'))))
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
        for driver in drivers[section]:
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
          if section in ('manually_install', 'no_driver') or ('builtin' in drivers[section][driver] and drivers[section][driver]['builtin']):
            radio_button.connect("toggled", self.on_driver_selection_changed, device)
          else:
            radio_button.connect("toggled", self.on_driver_selection_changed, device, driver)
          if drivers['manually_installed'] and section != 'manually_installed':
            radio_button.set_sensitive(False)

      self.box_driver_detail.pack_start(device_box, False, False, 6)

    self.ui_building = False
    self.box_driver_detail.show_all()
    self.set_driver_action_status()

  def update_label_and_icons_from_status(self):
    '''Update the current label and icon, computing the new device status'''

    for device in self.devices:
      (overall_status, icon, drivers) = self.gather_device_data(self.devices[device])
      (driver_status, widget) = self.dynamic_device_status[device]

      driver_status.set_from_icon_name(icon, Gtk.IconSize.MENU)
      widget.set_label("<small>{}</small>".format(overall_status))


  def set_driver_action_status(self):
    # Update the label in case we end up having some kind of proprietary driver in use.
    if (os.path.exists('/var/run/reboot-required')):
      self.label_driver_action.set_label(_("You need to restart the computer to complete the driver changes."))
      self.button_driver_restart.set_visible(True)
      self.window_main.set_urgency_hint(True)
      return

    self.nonfree_drivers = 0
    for device in self.devices:
      for pkg_name in self.devices[device]['drivers']:
        pkg = self.apt_cache[pkg_name]
        if not self.devices[device]['drivers'][pkg_name]['free'] and pkg.is_installed:
          self.nonfree_drivers = self.nonfree_drivers + 1

    if self.nonfree_drivers > 0:
      self.label_driver_action.set_label(gettext.ngettext (
                                                "%(count)d proprietary driver in use.",
                                                "%(count)d proprietary drivers in use.", 
                                                self.nonfree_drivers)
                                                % { 'count': self.nonfree_drivers})
    else:
      self.label_driver_action.set_label(_("No proprietary drivers are in use."))

if __name__ == "__main__":
    if os.getuid() != 0:
        os.execvp("gksu", ("", " ".join(sys.argv)))
    else:
        Application()
        Gtk.main()
