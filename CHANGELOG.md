# Changelog

All notable changes to Craftd. Newest first.

## [1.0.0] - 2026-11-18 · First full release

Craftd now comes as a regular Windows app: no Python or setup needed.

### Installing
1. Download `Craftd-windows.zip` from this release and extract it anywhere (e.g. `Documents\Craftd`).
2. Open `Craftd\Craftd.exe`. Keep it next to its `_internal` folder.
3. If Windows says "Windows protected your PC", click **More info → Run anyway** (Craftd isn't code-signed yet).
4. Click **Import from Prism…** or **Import from MultiMC…** to link your instances.

To update later, delete the old `Craftd` folder and extract the new zip in its place. Instances and settings live in
`%APPDATA%\Craftd`, so nothing is lost. You still need Prism Launcher or MultiMC to play; launching from Craftd comes in v2.

### Added
- `Craftd.exe`: a one-folder Windows app built with PyInstaller (`build_exe.bat`)
- "Match system" theme option on macOS

## [0.8.6] · Official logo
- The official Craftd logo is now the app icon, sidebar logo and About page logo

## [0.8.5] · Edit Instance
- Right-click an instance → **Edit Instance…** to change its name, Minecraft version, loader or loader version
- Works on Prism and MultiMC instances, with a backup of the launcher's file saved first
- Warns when installed mods won't fit the new loader or Minecraft version

## [0.8.4]
- Instance names and details wrap onto new lines instead of being cut off, at any window size
- Hovering any cell in the mod tables shows its full text

## [0.8.3] · MultiMC support
- **Import from MultiMC…**, with the MultiMC instances folder set in Settings → General
- MultiMC instances are labeled in the sidebar and work exactly like Prism ones

## [0.8.2] · Netherite & Iron
- Dark mode uses block of netherite colors; Light mode uses block of iron colors
- Every text color checked for readability (4.5:1 contrast)

## [0.8.1]
- All text is regular weight (no bold)

## [0.8.0] · Settings & new font
- New font: Monocraft (SIL Open Font License)
- Settings window with pages: General, Appearance, Mods, Carry Over, Storage, Network, About
- Stable-vs-beta builds, automatic dependencies, Carry Over defaults, cache cleanup, proxy and connection test
- Packs and settings already copied show as "already copied"
- New app icon

## [0.7.1]
- Changing "Copy mods from" re-detects automatically, so the mod list and packs always match

## [0.7.0] · Packs & settings
- Carry Over can bring resource packs, shader packs, mod settings, options & keybinds and the server list
- **Choose Packs…** to pick individual packs
- Nothing is overwritten unless **Replace** is on, and anything replaced is backed up first

## [0.6.1] – [0.6.2]
- Fixed false compatibility warnings from mods that bundle other mods (WorldEdit, LambDynamicLights)

## [0.6.0] · Reliability update
- Shows each instance's exact loader version
- Compatibility check: missing dependencies, version mismatches and mods made for another loader
- Crash Help tab: explains crash reports and suggests fixes
- Waitlisted label for mods with no build yet; rechecked every time Craftd starts
- Stable builds preferred over betas; exact versions that mods require are respected

## [0.1] – [0.5] · Early builds
- First version, called Blockn: link instances, detect the mods in one and find the right builds for another (Carry Over)
- Renamed to Craftd
- Light / Dark / Match Windows themes
- Add from Modrinth: a store-style browser with search, categories, sorting and a version picker
- Support for Fabric, Quilt, NeoForge and Forge
- Easier-to-see scrollbars and a resizable window that fits small screens
- Minecraft-style pixel font
