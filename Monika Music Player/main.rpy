# Monika Music Player - compatibility build for MAS 0.12.x / classic Submod API
# This is intentionally a .rpy script: it is loaded by Ren'Py itself and registers
# the submod through store.mas_submod_utils.Submod(...), rather than relying only
# on header.json + a dynamically-loaded .rpym module.

init -990 python:
    import os
    import sys
    import time
    import subprocess
    import glob
    import traceback

    def monika_music_player_log(message):
        try:
            log_path = os.path.join(renpy.config.gamedir, "monika_music_player_debug.log")
            handle = open(log_path, "a")
            try:
                handle.write("[MMP %s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), str(message)))
            finally:
                handle.close()
        except Exception:
            pass

    monika_music_player_log("Classic .rpy bootstrap executing; gamedir=%s" % renpy.config.gamedir)

    if not hasattr(persistent, "monika_music_player_autostart"):
        persistent.monika_music_player_autostart = True

    monika_music_player_process = None
    monika_music_player_autostart_checked = False

    def monika_music_player_root():
        """Find the Music Player folder even if the user renamed its parent folder."""
        base = os.path.join(renpy.config.gamedir, "Submods")
        preferred = os.path.join(base, "Monika Music Player")
        try:
            if os.path.isfile(os.path.join(preferred, "player", "music_player.py")):
                return preferred
            for name in os.listdir(base):
                candidate = os.path.join(base, name)
                if os.path.isfile(os.path.join(candidate, "player", "music_player.py")):
                    return candidate
        except Exception as e:
            monika_music_player_log("Could not scan Submods directory: %s" % e)
        return preferred

    def monika_music_player_find_pythonw():
        """Find a windowed Python 3 executable capable of running the Qt player."""
        root = monika_music_player_root()
        path_file = os.path.join(root, "python_path.txt")
        try:
            handle = open(path_file, "r")
            try:
                for line in handle:
                    candidate = line.strip().strip('"')
                    if candidate and not candidate.startswith("#") and os.path.isfile(candidate):
                        monika_music_player_log("Using python_path.txt: %s" % candidate)
                        return candidate
            finally:
                handle.close()
        except Exception as e:
            monika_music_player_log("Could not read python_path.txt: %s" % e)

        try:
            candidate = getattr(persistent, "monika_music_player_pythonw", "")
            if candidate and os.path.isfile(candidate):
                monika_music_player_log("Using saved Python path: %s" % candidate)
                return candidate
        except Exception:
            pass

        candidates = []
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", "C:\\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        if local:
            candidates.extend(glob.glob(os.path.join(local, "Programs", "Python", "Python*", "pythonw.exe")))
            candidates.append(os.path.join(local, "Microsoft", "WindowsApps", "pythonw.exe"))
            candidates.extend(glob.glob(os.path.join(local, "Microsoft", "WindowsApps", "PythonSoftwareFoundation.Python.*", "pythonw.exe")))
        for base in (pf, pfx86):
            candidates.extend(glob.glob(os.path.join(base, "Python*", "pythonw.exe")))
            candidates.extend(glob.glob(os.path.join(base, "WindowsApps", "PythonSoftwareFoundation.Python.*", "pythonw.exe")))

        # Registry lookup covers ordinary python.org installs when their folder is not in PATH.
        try:
            try:
                import _winreg as winreg
            except ImportError:
                import winreg
            roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
            versions = ("3.13", "3.12", "3.11", "3.10", "3.9", "3.8")
            for hive in roots:
                for version in versions:
                    for suffix in ("Software\\Python\\PythonCore\\%s\\InstallPath" % version,
                                   "Software\\WOW6432Node\\Python\\PythonCore\\%s\\InstallPath" % version):
                        try:
                            key = winreg.OpenKey(hive, suffix)
                            try:
                                install_dir = winreg.QueryValue(key, None)
                            finally:
                                winreg.CloseKey(key)
                            candidates.append(os.path.join(install_dir, "pythonw.exe"))
                        except Exception:
                            pass
        except Exception:
            pass

        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        for folder in path_entries:
            if folder:
                candidates.append(os.path.join(folder, "pythonw.exe"))
                candidates.append(os.path.join(folder, "pyw.exe"))

        seen = set()
        for candidate in candidates:
            try:
                candidate = os.path.abspath(candidate)
                normalized = os.path.normcase(candidate)
                if normalized not in seen:
                    seen.add(normalized)
                    if os.path.isfile(candidate):
                        monika_music_player_log("Found Python launcher: %s" % candidate)
                        return candidate
            except Exception:
                pass
        monika_music_player_log("ERROR: no pythonw.exe/pyw.exe found; set its full path in python_path.txt")
        return None

    def monika_music_player_launch(silent=False):
        global monika_music_player_process
        root = monika_music_player_root()
        script = os.path.join(root, "player", "music_player.py")
        monika_music_player_log("Launch requested; script=%s" % script)

        if not os.path.isfile(script):
            monika_music_player_log("ERROR: music_player.py is missing")
            if not silent:
                renpy.notify("Music Player files are missing. Reinstall the whole submod folder.")
            return

        try:
            if monika_music_player_process is not None and monika_music_player_process.poll() is None:
                if not silent:
                    renpy.notify("Monika Music Player is already running.")
                return
        except Exception:
            monika_music_player_process = None

        python_exe = monika_music_player_find_pythonw()
        if not python_exe:
            if not silent:
                renpy.notify("Python 3 windowed executable not found. Set it in python_path.txt.")
            return

        try:
            args = [python_exe]
            if os.path.basename(python_exe).lower() == "pyw.exe":
                args.append("-3")
            args.extend([script, "--mas-pid", str(os.getpid())])
            monika_music_player_log("Starting process with command=%s" % repr(args))
            monika_music_player_process = subprocess.Popen(args, cwd=os.path.join(root, "player"))
            monika_music_player_log("Popen success; pid=%s" % monika_music_player_process.pid)
            if not silent:
                renpy.notify("Opening Monika Music Player...")
        except Exception as e:
            monika_music_player_log("ERROR starting player: %s\n%s" % (e, traceback.format_exc()))
            if not silent:
                renpy.notify("Could not start Music Player. See game/monika_music_player_debug.log.")

    def monika_music_player_autostart_once():
        global monika_music_player_autostart_checked
        if monika_music_player_autostart_checked:
            return
        monika_music_player_autostart_checked = True
        enabled = getattr(persistent, "monika_music_player_autostart", True)
        monika_music_player_log("Autostart timer fired; enabled=%s" % enabled)
        if enabled:
            monika_music_player_launch(silent=False)

    def monika_music_player_toggle_autostart():
        persistent.monika_music_player_autostart = not getattr(persistent, "monika_music_player_autostart", True)
        try:
            renpy.save_persistent()
        except Exception as e:
            monika_music_player_log("Could not save autostart preference: %s" % e)
        if persistent.monika_music_player_autostart:
            renpy.notify("Music Player will open automatically when MAS starts.")
        else:
            renpy.notify("Music Player auto-open is disabled.")

    def monika_music_player_install_dependencies():
        installer = os.path.join(monika_music_player_root(), "scripts", "install_dependencies.bat")
        if os.path.isfile(installer):
            try:
                os.startfile(installer)
                monika_music_player_log("Dependency installer opened")
                return
            except Exception as e:
                monika_music_player_log("Could not open installer: %s" % e)
        renpy.notify("Setup script not found. Reinstall the complete Music Player folder.")

    # Explicit legacy Submod API registration is the key compatibility change.
    try:
        store.mas_submod_utils.Submod(
            author="Community Project",
            name="Monika Music Player",
            description="Spotify-inspired standalone player for local audio and direct online audio links. F7 opens it; it can also auto-start with MAS.",
            version="0.3.0",
            settings_pane="monika_music_player_settings_screen"
        )
        monika_music_player_log("Submod registered through mas_submod_utils.Submod")
    except Exception as e:
        monika_music_player_log("ERROR registering Submod object: %s\n%s" % (e, traceback.format_exc()))

    # Export functions for screens and labels to call explicitly from store.
    store.monika_music_player_launch = monika_music_player_launch
    store.monika_music_player_autostart_once = monika_music_player_autostart_once
    store.monika_music_player_toggle_autostart = monika_music_player_toggle_autostart
    store.monika_music_player_install_dependencies = monika_music_player_install_dependencies
    monika_music_player_log("Bootstrap functions registered in store")

init 5 python:
    try:
        if "monika_music_player_open" not in store.persistent.event_database:
            store.addEvent(
                store.Event(
                    store.persistent.event_database,
                    eventlabel="monika_music_player_open",
                    category=["music"],
                    prompt="Music Player",
                    pool=True,
                    unlocked=True
                )
            )
        monika_music_player_log("Talk topic available/registered")
    except Exception as e:
        monika_music_player_log("ERROR registering Talk topic: %s\n%s" % (e, traceback.format_exc()))

label monika_music_player_open:
    m 1eua "I made a little music player for us."
    m 3eua "You can play songs from your computer or open an online audio link."
    $ store.monika_music_player_launch(False)
    return

screen monika_music_player_settings_screen():
    vbox:
        xfill True
        spacing 10
        text "Monika Music Player" size 22
        text "F7 opens the player. Talk > Music Player is also available." size 14
        textbutton ("Auto-open when MAS starts: ON" if getattr(store.persistent, "monika_music_player_autostart", True) else "Auto-open when MAS starts: OFF") action Function(store.monika_music_player_toggle_autostart)
        textbutton "Open Music Player now" action Function(store.monika_music_player_launch, False)
        textbutton "Install/check Python + PySide6" action Function(store.monika_music_player_install_dependencies)

screen monika_music_player_key_overlay():
    timer 2.0 action Function(store.monika_music_player_autostart_once)
    key "K_F7" action Function(store.monika_music_player_launch, False)

init 5 python:
    try:
        if "monika_music_player_key_overlay" not in config.overlay_screens:
            config.overlay_screens.append("monika_music_player_key_overlay")
        monika_music_player_log("F7/autostart overlay registered")
    except Exception as e:
        monika_music_player_log("ERROR registering overlay: %s\n%s" % (e, traceback.format_exc()))
