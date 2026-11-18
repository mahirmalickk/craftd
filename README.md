# Craftd

A personal Minecraft launcher in the spirit of Prism and MultiMC. Its main feature is **Carry Over**:
Craftd detects the mods you use in one instance and finds the matching build of each one for another
instance, such as going from 26.2 to 26.3.

**Craftd 1.0** covers instances, the mod manager, the Modrinth browser, and Carry Over. Launching the game
(Microsoft login, Java and game files) is planned for v2. Until then you link your Prism or MultiMC instances,
manage their mods in Craftd, and keep launching them from Prism or MultiMC.

## Just want to use it? (Windows)

1. Download `Craftd-windows.zip` from the [latest release](../../releases/latest) and extract it anywhere,
   e.g. `Documents\Craftd`.
2. Double-click `Craftd\Craftd.exe`. No Python needed. Keep it next to its `_internal` folder.
   If Windows SmartScreen says "Windows protected your PC", click **More info → Run anyway** (Craftd isn't
   code-signed).
3. Click **Import from Prism…** (found automatically) or **Import from MultiMC…** (choose its `instances` folder),
   and link your instances.

You need Prism Launcher or MultiMC to play, and an internet connection for Modrinth. To update Craftd, delete the
old `Craftd` folder and extract the new zip in its place: your instances and settings live in `%APPDATA%\Craftd`,
so they stay.

The rest of this README is for running Craftd from source.

---

## Setup on Windows (one time)

**1. Unzip to a permanent folder**
Right-click `craftd.zip` → **Extract All…** → extract to `C:\Users\<you>\Projects`.
✅ *Checkpoint:* `C:\Users\<you>\Projects\craftd` contains `craftd`, `tests`, `README.md`, `requirements.txt`, `Craftd.bat`.

**2. Check Python (needs 3.11+)**
Open **Terminal** (Start → type "Terminal") and run `py --version`.
If it isn't 3.11+ or isn't found, install the latest Python from python.org and tick **"Add python.exe to PATH"** on the first installer screen, then reopen Terminal.
✅ *Checkpoint:* `Python 3.11.x` or higher.

**3. Create the environment and install dependencies**
```powershell
cd $HOME\Projects\craftd
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
✅ *Checkpoint:* ends with `Successfully installed ...`, no red `ERROR`.

**4. (Optional) Run the tests:** `.venv\Scripts\python -m pytest -q` → `94 passed`.

**5. Start Craftd:** `.venv\Scripts\python -m craftd` — afterwards just double-click `Craftd.bat`.
If SmartScreen warns, click **More info → Run anyway**.
✅ *Checkpoint:* a dark window titled **Craftd** opens.

Data lives in `%APPDATA%\Craftd`; Prism instances are found in `%APPDATA%\PrismLauncher\instances`.

## Building Craftd.exe (Windows)

This packages Craftd with PyInstaller so testers can run it without installing Python. It's a one-folder app:
`Craftd.exe` plus an `_internal` folder that holds Python, Qt, the fonts and the logo.

**1. Install the build tools (once, after the Windows setup above)**
```powershell
.venv\Scripts\python -m pip install -r requirements-build.txt
```

**2. Build:** double-click `build_exe.bat` (or run it in Terminal). It takes a minute or two.
✅ *Checkpoint:* it ends with `Done: dist\Craftd\Craftd.exe and dist\Craftd-windows.zip`.

**3. Share `dist\Craftd-windows.zip`.** Testers extract it and double-click `Craftd\Craftd.exe`. Keep `Craftd.exe` next
to its `_internal` folder, because it won't start on its own. The exe isn't code-signed, so SmartScreen may warn:
**More info → Run anyway**.

The exe uses the same data folder (`%APPDATA%\Craftd`) as `python -m craftd`, so instances and settings are shared.
`build\` and `dist\` are build output and can be deleted at any time.

## Setup on macOS (one time)

**1. Put the folder somewhere permanent**
Unzip `craftd.zip` into something like `~/Projects/craftd`. (Renamed from Blockn? Delete the old `blockn` folder; any Blockn data in Application Support moves over automatically on first launch.)
✅ *Checkpoint:* the folder has `craftd/`, `tests/`, `README.md` and `Craftd.command` in it.

**2. Check your Python version (it must be 3.11 or newer)**
```bash
python3 --version
```
If it's older than 3.11, or the command isn't found, run `brew install python@3.12` or get the installer from python.org.
✅ *Checkpoint:* the output reads `Python 3.11.x` or higher.

**3. Create a virtual environment and install the dependencies**
```bash
cd ~/Projects/craftd
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
✅ *Checkpoint:* your prompt starts with `(.venv)`, and `python -c "import PySide6; print('ok')"` prints `ok`.

**4. (Optional) Run the test suite**
```bash
pytest -q
```
✅ *Checkpoint:* `94 passed`. The tests use a fake Modrinth, so they don't need internet.

**5. Start Craftd**
```bash
python -m craftd
```
After this first run you can double-click `Craftd.command` in Finder instead. If macOS blocks it,
right-click it, choose **Open**, and if that doesn't work, run `chmod +x Craftd.command` once.
✅ *Checkpoint:* a dark window titled **Craftd** opens, with **+ New Instance** at the bottom left.

---

## Using Carry Over (the 26.2 → 26.3 example)

1. **Import your existing instances.** Click **Import from Prism…**. Craftd finds Prism's instances folder on its own
   (`%APPDATA%\PrismLauncher\instances` on Windows). Tick your 26.2 instance and click **Link Selected**.
   **Using MultiMC?** Click **Import from MultiMC…** instead. MultiMC runs from wherever you unzipped it, so choose its
   `instances` folder once (in MultiMC: **Folders → View Instance Folder**); Craftd remembers it in
   **Settings → General**. MultiMC instances work exactly like Prism ones and are labeled "MultiMC".
   Linked instances stay where they are. Craftd only adds or removes files in their `mods` folder, and
   **Unlink** never deletes anything.
2. **Make the new instance.** For now, create it in Prism (an empty 26.3 Fabric instance) and import it the same way,
   so you can launch it from Prism. You can also use **+ New Instance** in Craftd, but Craftd can't launch it until v2.
   In the New Instance dialog, Craftd **pre-selects the best source on its own**: same loader, closest older
   Minecraft version, and it has mods.
3. **Review.** Open the 26.3 instance's **Carry Over** tab. Detection runs as soon as the tab opens. Each mod is marked:
   | Status | Meaning | Default |
   |---|---|---|
   | **Ready** | Modrinth has a build for 26.3 + your loader | ticked |
   | **No build yet** | The mod exists, but nothing for 26.3 yet | ticked → goes on the **waitlist** |
| **Not for NeoForge** (etc.) | The mod isn't made for this loader at all | not offered, never waitlisted |
   | **Not on Modrinth** | Craftd can't verify the jar (e.g. CurseForge-only) | unticked; enable "Also copy jars…" to copy it as-is |
   | **Already installed** | Already in 26.3 | hidden (tick "Show already installed") |
4. **Carry Over Selected.** Craftd downloads each file, checks its SHA-1 checksum, and pulls in any
   **required dependencies** that are missing (YACL needing Fabric API, for example).
5. **Waitlist.** Every time Craftd starts, it rechecks waitlisted mods. When a 26.3 build of YACL comes out,
   the instance shows "● 1 ready" and the Carry Over tab offers **Install Now**.

Source options: one instance, or **All my other instances** to merge your mods from every instance into one list.

### Bringing packs and settings too
Under the mod list, **Also bring from <source>** offers the rest of what makes an instance feel like yours:

| Option | What's copied | Default |
|---|---|---|
| **Packs** | `resourcepacks` and `shaderpacks`. Use **Choose Packs…** to pick individual ones | ticked, except ones it already has (“already copied”) |
| **Mod settings** | the `config` folder | ticked if it has new files (“3 new of 40 files”) |
| **Options & keybinds** | `options.txt` (graphics, controls, selected packs) | ticked only if the new instance has none yet* |
| **Server list** | `servers.dat` | ticked only if the new instance has none yet |
| **Replace what's already there** | overwrite settings the new instance already has | off |

\*Not ticked if the source is a **newer** Minecraft version, because older versions can misread newer option files.

Nothing is ever lost. Packs the new instance already has are left alone. With **Replace** off, Craftd only fills in
missing config files and skips `options.txt` / `servers.dat` if they exist. With **Replace** on, Craftd first copies
what it's about to overwrite to `config.craftd-backup-<date>` (or `options.txt.craftd-backup-<date>`). You can carry
packs and settings even with no mods ticked. With **All my other instances**, they come from the newest one.
Change what's ticked by default in **Settings → Carry Over**.

### Command line (same engine)
```bash
python -m craftd.cli list
python -m craftd.cli link-prism                       # link every Prism instance found
python -m craftd.cli detect "Fabric 26.3"             # auto-picks the source
python -m craftd.cli carry  "Fabric 26.3" --from "Survival 26.2"
python -m craftd.cli waitlist "Fabric 26.3" --install
```

---

## Adding mods from Modrinth

On an instance's **Mods** tab, click **Add from Modrinth…**:
- The badge at the top (e.g. **26.3 · NeoForge**) shows what you're browsing for. Only mods with a build for that
  Minecraft version and loader appear.
- Search, sort (Relevance, Most downloaded, Most followed, Recently updated, Newest), and filter with the category chips.
  Mods you already have are hidden. Untick **Hide installed** to see them.
- Click **+ Add** on any card to queue it. Click a card to see its description and pick a specific version
  (the recommended one is the newest stable release).
- **Install N mods** installs the queue plus anything those mods require.

## Editing an instance

Right-click an instance in the sidebar → **Edit Instance…** to change its name, Minecraft version, loader
(Vanilla, Fabric, Quilt, NeoForge, Forge) or loader version, e.g. turn **26.3 Vanilla** into **26.3 Fabric**.

- Loader versions come from the launcher's own version list (Prism's for Prism and Craftd instances, MultiMC's
  for MultiMC ones), so they're named exactly the way that launcher expects. The recommended build (or newest
  stable) is picked for you.
- For Prism/MultiMC instances, Craftd edits the launcher's own `mmc-pack.json` (the file it changes when you edit
  an instance there) and saves a backup next to it first (`mmc-pack.json.craftd-backup-<date>`). Close
  Prism/MultiMC before saving: Craftd checks and asks, since an open launcher can overwrite the change.
- Mods aren't touched. Switching between loader families (e.g. Fabric → NeoForge) or Minecraft versions shows a
  warning first; afterwards, the compatibility check marks mods that won't load, and Carry Over or **Check for
  Updates** gets the right builds.

The right-click menu will get more options over time.

## Settings

Click **⚙ Settings** at the bottom of the sidebar. Pages are listed on the left, like Prism's settings:

| Page | What's there |
|---|---|
| **General** | Check the waitlist when Craftd starts · Prism's instances folder (for portable Prism or a moved folder; used by **Import from Prism…**) · MultiMC's instances folder (used by **Import from MultiMC…**) · Open Craftd's data folder |
| **Appearance** | Match Windows (default; "Match system" on macOS), Light (styled after the block of iron) or Dark (the block of netherite) · Text size Default or Large. Previews instantly |
| **Mods** | Stable builds first (recommended) or newest even if beta · Install required dependencies automatically · Hide installed mods in **Add from Modrinth** |
| **Carry Over** | What the Carry Over tab ticks by default: jars not on Modrinth, packs, mod settings, options & server list |
| **Storage** | What the cache holds and how big it is · **Clear Cache** (instances, mods, settings and waitlists are never touched) |
| **Network** | Proxy: system settings (default), none, or an HTTP proxy · request timeout · **Test Connection**. Only Craftd's own Modrinth downloads use these |
| **About** | Version, credits and the font license |

**Save** applies everything; **Cancel** reverts (including the live theme preview). Clearing the cache happens right
away. Settings are saved to `settings.json` in Craftd's data folder; files from older versions load fine.

### Font
Craftd uses **[Monocraft](https://github.com/IdreesInc/Monocraft)** by Idrees Hassan, a Minecraft-style pixel font
(`craftd/fonts/monocraft/`, the official no-ligatures file, unmodified). It's drawn on a 9-pixel grid, so Craftd sizes
text at 18px / 36px (or 27px / 45px on Large) with smoothing off to keep it crisp, and uses only its Regular
weight (no bold). The few symbols Monocraft doesn't have (`⚠ ✓ ⚙ ↗ ▣`) come from `craftd/fonts/craftd-pixel-extras.ttf`,
drawn for Craftd on the same grid (rebuild with `python tools/make_pixel_extras.py`).

> **License:** Monocraft is under the **SIL Open Font License 1.1** (`craftd/fonts/monocraft/OFL.txt`), which allows
> bundling it with Craftd, including in a public repo, as long as the license file travels with it.

**Logo:** Craftd's official logo is `craftd/assets/craftd-logo-16.png`, a 16×16 pixel C·d mark with a grass
block inside. It's the window and taskbar icon, the sidebar logo and the About page logo. The icon files
(`craftd.png`, 256×256, and `craftd.ico`, 16–256 px, for Windows and `Craftd.exe`) are built from it at
whole-number sizes so every pixel stays sharp. After editing the logo, rebuild them with
`.venv\Scripts\python tools\make_icon.py`. Colors live in `craftd/gui/theme.py` (`PALETTES`).

## Staying crash-free

- **Loader version:** for linked Prism instances Craftd shows the exact loader (e.g. *NeoForge 26.3.0.110*) next to
  the Minecraft version.
- **Compatibility check:** every time the Mods tab loads, Craftd reads the rules each mod declares in its own files
  (`fabric.mod.json`, `quilt.mod.json`, `neoforge.mods.toml`, `mods.toml`, including mods bundled inside other mods):
  required mods, Minecraft and loader version ranges, and versions it breaks with. Problems show as a yellow bar
  (**Show Problems** lists each one with what to do), and the affected mods are marked ⚠ in red.
- **Picks a build that fits:** when Craftd downloads a mod whose file says it won't run on your loader version, it
  tries other builds of the same mod (stable first) and installs one that fits, then tells you which it picked.
- **Crash Help tab:** reads the newest crash report (or `latest.log` when Fabric/NeoForge refused to start) and explains
  it: mods that conflict, missing or wrong-version dependencies, mods built for another loader version (failed mixin
  hooks), out of memory, wrong Java. A ● on the tab means there's a crash you haven't looked at.
- **Waitlisted:** mods already on the waitlist show as *Waitlisted* in Carry Over instead of being offered again.

Limits: mods that don't declare their rules (Sodium 0.9.2 didn't) can't be checked ahead of time. The Crash Help tab
explains those after the fact.

## How detection works

1. Every jar in the source instance gets a SHA-1 fingerprint. One batched call to Modrinth's `POST /version_files`
   tells Craftd which project each file belongs to, whether Craftd, Prism, or you put it there. Results are cached
   in `cache/modrinth.json`, so rescans don't hit the network.
2. Jars are grouped by project, so `sodium-0.6.jar` (26.1) and `sodium-0.7.jar` (26.2) count as **one** mod.
3. One call to `POST /version_files/update` with the target's Minecraft version and loader returns the newest
   build of every project in a single batch. That also works across loaders (Sodium from a Fabric instance into a
   NeoForge one), and Quilt targets accept Fabric builds.
4. **Picking the build:** stable releases win over betas/alphas (a beta is only used when nothing else exists,
   and is labeled "beta"). If a mod requires one exact version of another (Iris 1.11.7 for 26.3 requires
   Sodium mc26.3-0.9.2), Craftd installs that version and marks it 📌. "Check for Updates" follows the same rules.
5. Jars Modrinth doesn't know are identified from their own metadata (`fabric.mod.json`, `quilt.mod.json`,
   `mods.toml`, `neoforge.mods.toml`), so they still show up with their real names, even offline.

## Project layout
```
craftd/
  modrinth.py     Modrinth API client (User-Agent, rate-limit handling, verified downloads)
  instances.py    Craftd instances + linked Prism instances (reads mmc-pack.json / instance.cfg)
  mods.py         Mod folder scanning, jar fingerprinting, the hash cache, jar metadata
  installer.py    Install with dependencies, update, remove, enable/disable
  sync.py         Carry Over: source suggestion, detection, waitlist  ← the core feature
  compat.py       Compatibility check: reads mod metadata, version ranges, conflicts
  crash.py        Crash Help: explains crash reports and failed starts
  extras.py       Carry Over for packs, config, options.txt and servers.dat (with backups)
  core.py         Wires everything together
  cli.py          Command line
  settings.py     Saved preferences (the Settings pages)
  fonts/          Monocraft (SIL OFL) + Craftd's pixel symbols font
  assets/         Craftd's official logo (16×16) and the icons built from it (.png, .ico)
  gui/            PySide6 window, tabs, dialogs, theme (palettes + type scale), sidebar rows, workers
tests/            Fake Modrinth + 94 tests (engine and GUI)
```
Craftd's data (instances list, settings, cache, waitlists) lives in `%APPDATA%\Craftd` on Windows and
`~/Library/Application Support/Craftd` on macOS. Set `CRAFTD_HOME` to use a different folder.

Build tooling: `build_exe.bat` + `requirements-build.txt` (PyInstaller) and `tools/craftd_exe_entry.py` (the exe's entry
point); `tools/make_icon.py` and `tools/make_pixel_extras.py` rebuild the icons and the symbols font.

## Roadmap
**1.1**
- Modrinth modpacks: browse and install whole packs
- More right-click options on instances (rename, open folders, copy, delete)

**v2**
- Launching: Microsoft account sign-in, game file and asset download, a Java runtime per version, and loader installation
- Settings pages for Java, memory (RAM) and accounts
- Instances as an icon grid, like Prism and MultiMC
- Update notifications for new Craftd versions

**Later**
- CurseForge as a second source
- An optional auto mode: carry over without asking whenever every mod is Ready
- A macOS app (`Craftd.app`); for now macOS runs from source

## License

Craftd's code is released under the [MIT License](LICENSE). See [CHANGELOG.md](CHANGELOG.md) for the version history.

Bundled third-party files keep their own licenses: the Monocraft font is under the SIL Open Font License 1.1
(`craftd/fonts/monocraft/OFL.txt`).

Craftd is a personal project. It is not an official Minecraft product and is not approved by or associated with
Mojang or Microsoft. Mod data comes from [Modrinth](https://modrinth.com).
