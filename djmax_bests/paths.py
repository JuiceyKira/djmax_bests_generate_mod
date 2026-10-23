"""Filesystem layout: bundled assets vs. writable state.

In a source checkout everything stays where it always was (covers/cache inside the package,
records/output at the project root). Frozen into an exe with PyInstaller, the code and the
read-only assets live in the temporary bundle (``sys._MEIPASS``) that is thrown away when the
process exits, so everything the program writes must live beside the executable instead:

    DJMAX-Bests.exe
    settings.ini
    data/          account.txt, cache/, covers/, records/
    output/        generated images (beside data/, not inside it)

``state_path()`` picks the right location per mode.
"""
import os
import sys

#: True when running from a PyInstaller executable.
FROZEN = bool(getattr(sys, "frozen", False))

#: Directory holding the bundled read-only assets (the package tree in both modes).
BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _exe_dir() -> str:
    """Folder the user actually sees: the exe's folder when frozen, the project root otherwise."""
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app_dir() -> str:
    override = os.environ.get("DJMAX_DATA_DIR")
    if override:
        return os.path.abspath(override)
    if FROZEN:
        # Account and caches live in one folder next to the exe:
        #   DJMAX-Bests.exe / data / {account.txt, cache, covers, records}
        return os.path.join(_exe_dir(), "data")
    return _exe_dir()


#: Folder the user sees (exe folder / project root).
EXE_DIR = _exe_dir()
#: Writable state root: ./data beside the exe, the project root in a source checkout.
APP_DIR = _app_dir()
#: Generated images sit beside data/ (exe folder / project root), never inside data/.
OUTPUT_DIR = os.path.join(EXE_DIR, "output")
ACCOUNT_FILE = os.path.join(APP_DIR, "account.txt")
CONFIG_FILE = os.path.join(EXE_DIR, "settings.ini")


def state_path(name: str, dev_default: str | None = None) -> str:
    """A writable state directory.

    Frozen (or with DJMAX_DATA_DIR set): ``<APP_DIR>/<name>``. In a source checkout the
    historical layout is kept by returning ``dev_default`` when one is given.
    """
    if FROZEN or os.environ.get("DJMAX_DATA_DIR"):
        return os.path.join(APP_DIR, name)
    if dev_default is None:
        return os.path.join(APP_DIR, name)
    return dev_default


def ensure_app_dirs() -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def seed_covers() -> int:
    """First run of the frozen app: place the bundled placeholder jacket in covers/.

    Only `dummy.jpg` ships inside the exe; every real jacket is downloaded by the first refresh
    (api_handler.prefetch_covers) or on demand. Returns 1 when the placeholder was copied.
    """
    if not FROZEN:
        return 0
    source = os.path.join(BUNDLE_DIR, "djmax_bests", "covers", "dummy.jpg")
    if not os.path.exists(source):
        return 0
    target_dir = os.path.join(APP_DIR, "covers")
    target = os.path.join(target_dir, "dummy.jpg")
    if os.path.exists(target):
        return 0

    import shutil
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(source, target)
    return 1
