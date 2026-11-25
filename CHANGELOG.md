# Changelog

All notable changes to Craftd. Newest first.

## [1.2.0] - 2026-11-25 · Accounts (v2, step 1)

### Added
- **Sign in with Microsoft**: **Settings → Accounts → Add Account…** shows a code; click **Open Sign-In Page** (the
  code is copied for you), sign in on Microsoft's own page, and Craftd finishes signing in to Xbox Live and
  Minecraft. Craftd never sees your password. Mojang approved Craftd's app for this in November 2026
- **Settings → Accounts**: everyone signed in, with their skin's face. **Play as This Account**, **Refresh** (checks the
  sign-in still works and picks up a new name or skin) and **Remove**
- **Your face and name in the sidebar**, under Settings. Click it to switch accounts or sign in
- Clear messages for sign-in problems: no Xbox profile yet, child accounts, Xbox not available in your country,
  doesn't own Minecraft: Java Edition, hasn't picked a Minecraft name, code expired, cancelled
- Sign-ins are saved in `accounts.json`, encrypted with your Windows user account (DPAPI), so a copied file is no
  use to anyone else. Tokens are never written to `craftd.log`

Launching the game with your account comes in the next v2 steps (game files, Java, Launch button).

## [1.1.2] - 2026-11-21

### Changed
- Browse Modpacks: pick the **Minecraft** version first, then the pack **Version** for it (newest first, the newest
  full release picked for you, betas and alphas labeled). No more giant list of every build ever made
- Drop-down lists open as a short scrolling list under the box (12 items at a time) instead of filling the screen

## [1.1.1] - 2026-11-20

### Fixed
- Browse Modpacks: the right side no longer runs past the window when both Prism and MultiMC are set up (the
  **Create in** box showed Prism's whole folder path). The divider between the list and the details now drags freely,
  and everything fits at any window size
- **Create in** boxes show just "Prism" or "MultiMC"; hover an item to see its folder

## [1.1.0] - 2026-11-20 · Import from, modpacks, worlds and sharing

### Added
- **Import from**: one button that asks which launcher your instances are in. Prism is found automatically, MultiMC's
  folder is picked once and remembered, and the Official Launcher, Modrinth App and CurseForge App are marked
  *Coming soon*
- **Browse Modpacks**: search Modrinth's modpacks and install one as a new Prism or MultiMC instance
- **Share Instance** (right-click): saves a small `.mrpack` to send to a friend; mods go in as Modrinth links. Open
  one with **Import from → Modpack file (.mrpack)**
- **Worlds in Carry Over**: copy worlds to the same or a newer Minecraft version only, with each world's version and
  size shown, and a warning when the new instance is missing mods the world uses. Never ticked for you
- **Instance right-click menu**: Rename, Open Folder, Copy Instance, Share Instance, Unlink from Craftd, Delete (to
  the Recycle Bin)
- **Mod right-click menu**: Enable/Disable, Update, Change Version, View on Modrinth, Show in Folder, Copy Name,
  Remove. Works on several mods at once
- **Add File…** and drag-and-drop for `.jar` files that aren't on Modrinth (e.g. from CurseForge)
- **craftd.log** in Craftd's data folder, plus **Settings → About → Open Log Folder** for bug reports

### Changed
- **+ New Instance creates the instance inside Prism or MultiMC** (**Create in**), with the recommended loader version,
  so it can be launched right away. Instances made with it before 1.1 show a **Move to Prism/MultiMC** banner
- The sidebar has **+ New Instance**, **Browse Modpacks**, **Import from** and **Settings**

### Fixed
- Mods carried into a MultiMC instance that had never been launched went into a folder MultiMC doesn't read
  (`minecraft` instead of `.minecraft`). Craftd now follows each launcher's own folder rule
- Errors in background tasks are logged instead of printed to a console Craftd.exe doesn't have
- Instance names with commas saved by Prism are read correctly

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
