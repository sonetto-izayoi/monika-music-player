MONIKA MUSIC PLAYER 0.3.0 — MAS 0.12.x COMPATIBILITY FIX
=======================================================

WHAT CHANGED
- Uses a classic Ren'Py .rpy bootstrap and explicitly registers through
  store.mas_submod_utils.Submod(...), instead of relying only on header.json + .rpym.
- Adds/keeps Submod Settings, Talk topic, F7 launcher, auto-start timer and debug log.
- Finds the player folder even if its folder name has been changed.
- Checks common Python 3 installations and Python's pyw launcher.

CLEAN INSTALL (IMPORTANT)
1. Exit MAS completely.
2. Delete the entire old folder:
   DDLC/game/Submods/Monika Music Player
   Also remove any old `main.rpym` / `main.rpymc` left in that folder.
3. Extract the `Monika Music Player` folder from this ZIP into:
   DDLC/game/Submods/
4. Confirm this file exists:
   DDLC/game/Submods/Monika Music Player/main.rpy
   The folder intentionally has no header.json or main.rpym in this compatibility build.
5. Launch MAS. Wait 2–3 seconds for auto-start.

EXPECTED
- Esc > Submods > Monika Music Player
- F7 opens the player
- Talk > Ask a Question > Music Player
- The player auto-opens after MAS's room starts, unless disabled in Submod Settings.

DEBUG LOG
The classic bootstrap should create:
  DDLC/game/monika_music_player_debug.log
If it is missing, the `main.rpy` script did not run (check the actual DDLC installation folder and game/traceback.txt).
If it exists, send its complete contents if the player still does not open.

REQUIREMENTS
- Windows
- Python 3.9+ (Python 3.11 recommended)
- PySide6 installed for the same Python interpreter used to launch music_player.py
- If auto-detection picks the wrong Python, put the full path to pythonw.exe in python_path.txt.
