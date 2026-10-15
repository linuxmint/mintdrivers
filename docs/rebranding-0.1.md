# Mainuan Gestao de Drivers 0.1

The official product name is **Gestão de Drivers**, project **Mainuan Gestão de
Drivers**, package/command `mainuan-gestao-drivers`, desktop ID
`org.mainuan.GestaoDrivers`. Qt is the official frontend. It remains read-only:
driver selection and plan preview do not invoke InstallPackages/RemovePackages.

## Baseline and Paths

The worktree was clean on branch `port/kubuntu-26.04`. Existing commit
`698b2de63634c4747e8d5ee317ce8e1075b64761` already checkpoints the previous phases,
so a duplicate checkpoint was unnecessary. Rebranding changes remain separate.

Python modules moved from `/usr/lib/linuxmint/mintdrivers/` to
`/usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/`. The official launcher
is a symlink to a script beside that package, allowing ordinary Python imports
without modifying sys.path. Backend rules and QtDBus transactions are preserved.
Only the test fixture's vendor identity changed to Mainuan.

Data moved to `/usr/share/mainuan/mainuan-gestao-drivers/`. App icons have the
resource ID `mainuan-gestao-drivers`, including both SVG and 48x48 PNG resources.
The existing generic GPL artwork is reused; no theme-specific paths are used.
The status icon is `mainuan-gestao-drivers-offline-symbolic`.

`mintdrivers`, `mintdrivers-qt`, `driver-manager` and `cinnamon-driver-manager`
are not installed. Old GTK desktop files are removed. The only visible launcher
is `org.mainuan.GestaoDrivers.desktop`, which starts Qt without a root wrapper.

`mainuan-gestao-drivers-gtk-legacy` is a temporary, menu-less GTK reference.
Its existing Broadcom helper and sudoers entry were relocated into the Mainuan
namespace, not added to the Qt architecture. GTK dependencies remain temporary.
Its existing operations are not enabled in the official Qt frontend.

## Translations and Settings

The gettext domain is `mainuan-gestao-drivers`. PO/POT names, generation tools,
source references and current Project-Id-Version metadata were migrated.
Existing translations and translator credits were retained. New Qt messages
were translated for pt_BR. Obsolete installation-media translations are historical
and are not compiled into runtime catalogs.

QSettings identity is organization `Mainuan`, application
`mainuan-gestao-drivers`; display name is `Gestão de Drivers`. Identity is set
before constructing QApplication to preserve the Plasma warning correction.

## Remaining Historical Strings

Every remaining result of `rg -n 'mintdrivers|Mint Drivers|Linux Mint|linuxmint' .`
belongs to the following groups. There are no old identifiers in official
Python modules or installed resource paths.

| Location | Classification | Reason |
| --- | --- | --- |
| README, this document, transaction documentation | HISTÓRICO / CRÉDITO | Original upstream, migration record and licensing |
| debian/changelog | HISTÓRICO / CRÉDITO | Original package names in preserved entries; new entry documents migration |
| debian/copyright | HISTÓRICO / CRÉDITO | Original project, contact and copyrights |
| PO catalog header comments and translator contact fields | HISTÓRICO / CRÉDITO | Translator provenance, original teams and license attribution |
| Obsolete `#~` PO entries | HISTÓRICO / CRÉDITO | Upstream texts, excluded from runtime MO files |
| Tests containing old identifier literals | HISTÓRICO / CRÉDITO | Negative regression assertions, not runtime dependencies |
| Manpages | HISTÓRICO / CRÉDITO | Original authors and derivation; legacy manual explicitly identifies GTK |
| Inherited .github workflows | HISTÓRICO / CRÉDITO | Upstream CI tooling references, not installed app identifiers |

The GTK legacy title uses the translated upstream Driver Manager name plus
`(GTK legacy)`. Its gettext entries are LEGADO GTK TEMPORÁRIO. Any occurrence
outside these historical, test or legacy contexts must be treated as an
ERRO DE REBRANDING.

## Packaging and Coexistence

Source and Package are `mainuan-gestao-drivers`; version is `0.1`. Older changelog
entries remain unchanged. The new entry is dated after the previous entry;
dpkg-genchanges may still warn about the deliberate version reset because the
historical 1.8.8+mainuan4 entry is preserved under the new package's changelog.

Maintainer is `Mainuan Packaging <openwebosbr@gmail.com>`, taken from the existing
Mainuan changelog entries, not from git config. Homepage/VCS point to the official
GitHub repository. GPL-2.0-or-later, Clement Lefebvre's 2013-2014 copyright and
existing file credits remain; Mainuan-created files are identified separately.

The official mintdrivers package is not installed on the development host.
Installed-file comparisons use the previous mintdrivers 1.8.8+mainuan4 archive
and the original upstream cd362b9 file tree. All paths are renamed, including
the 48x48 driver-manager icon discovered during comparison. No Conflicts,
Replaces, Breaks or Provides are needed. This is a file collision audit,
not an actual simultaneous installation test.

The local 1.8.8+mainuan1 archive is truncated and could not be inspected; it was
not modified by this work. The valid mainuan4 archive provides the comparison.

No handwritten preinst/postinst/prerm/postrm scripts are introduced. Debhelper
may generate standard icon-cache maintenance scripts. No package script changes
APT sources, driver modules, Secure Boot or dependencies. Removing the app does
not run autoremove; normal APT orphan-dependency policy remains external.

## VM Validation

The application package is not installed automatically on the host. In a VM,
with the .deb in the current directory:

```bash
sudo apt install ./mainuan-gestao-drivers_0.1_all.deb
mainuan-gestao-drivers
mainuan-gestao-drivers test
sudo apt remove mainuan-gestao-drivers
```

There is no identified file collision requiring removal of mintdrivers first.
Runtime PackageKit validation uses only CreateTransaction/Resolve and signals.
Real installation/removal authorization, Broadcom migration and MOK/Secure Boot
remain work for later releases; the beta does not enable those operations in Qt.
