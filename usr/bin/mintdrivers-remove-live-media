#!/usr/bin/python3
import os
import sys

if os.getuid() != 0:
    print("mintdrivers-remove-live-media needs to be run as root.")
    sys.exit(1)

if os.path.exists("/media/mintdrivers"):
    os.system("umount -q /media/mintdrivers")
    os.system("rm -rf /media/mintdrivers")

os.system("rm -f /etc/apt/sources.list.d/mintdrivers.list")

print ("Live media removed from sources.")