This is essentially the upstream part of Software Properties GTK which handles drivers management, stripped out of the rest of the application and turned into a standalone tool.

This addresses the short-term need for a functional driver manager in Mint 15 and allows us to replace software-properties with mintsources.

Long term we'll see where this goes, whether it's worth continuing with it or whether it gets ditched :)

## Driver backend migration

Driver discovery, NVIDIA policy, driver classification, and read-only APT metadata
queries live in `usr/lib/linuxmint/mintdrivers/backend/`. The GTK frontend remains
the reference UI during the migration and is responsible for translations,
presentation, and the existing PackageKit/GLib install workflow. The backend
models do not import GTK or XApp, so a future Qt frontend can consume them
without changing driver detection.
