"""setup_browser_debug.py

One-time setup: adds --remote-debugging-port=9222 to the registry so your
Chromium browser always launches with the debug port open.

Locus needs this for website blocking. Run this once and you never have to
think about it again.

Supports: Vivaldi, Google Chrome, Microsoft Edge, Brave

Run as administrator:
    python setup_browser_debug.py

Or Locus will prompt you to run it automatically on first launch if it
detects website blocking isn't working.
"""

import os
import sys
import subprocess
import winreg
from typing import Optional


DEBUG_FLAG = "--remote-debugging-port=9222 --remote-allow-origins=*"

# Registry paths for each browser's command line flags
# HKEY_LOCAL_MACHINE for system-wide, HKEY_CURRENT_USER for per-user installs
BROWSER_REGISTRY = [
    {
        "name": "Vivaldi",
        "keys": [
            # Per-user install -- this is where Vivaldi actually lives on most machines
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\Vivaldi\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Vivaldi\shell\open\command"),
            # System-wide install
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
        ],
        "exe_names": ("vivaldi.exe",),
    },
    {
        "name": "Google Chrome",
        "keys": [
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\ChromeHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\ChromeHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
        ],
        "exe_names": ("chrome.exe",),
    },
    {
        "name": "Microsoft Edge",
        "keys": [
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\MSEdgeHTM\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\MSEdgeHTM\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
        ],
        "exe_names": ("msedge.exe",),
    },
    {
        "name": "Brave",
        "keys": [
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\BraveHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\BraveHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
        ],
        "exe_names": ("brave.exe",),
    },
]


def _read_reg_value(hive, path) -> Optional[str]:
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return value
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"  [warn] Could not read registry: {e}")
        return None


def _write_reg_value(hive, path, value: str) -> bool:
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
        return True
    except PermissionError:
        return False
    except Exception as e:
        print(f"  [warn] Could not write registry: {e}")
        return False


def _add_flag_to_command(command: str, flag: str) -> str:
    """Insert the debug flag into a browser launch command string.

    Registry commands look like:
        "C:\\path\\to\\browser.exe" -- %1
    We insert our flags before the --.
    """
    if flag.split()[0] in command:
        return command  # already present

    # If there's a " -- " argument separator, insert before it
    if " -- " in command:
        return command.replace(" -- ", f" {flag} -- ", 1)

    # If command ends with the exe path (no args), just append
    if command.strip().endswith('"'):
        return command.strip() + f" {flag}"

    # Otherwise append at the end
    return command.strip() + f" {flag}"


def _remove_flag_from_command(command: str, flag: str) -> str:
    """Remove the debug flag from a browser launch command string."""
    # Remove each individual part of the flag
    result = command
    for part in flag.split():
        result = result.replace(f" {part}", "")
    return result


def is_debug_port_active() -> bool:
    """Check if any browser is currently running with the debug port open."""
    try:
        import requests
        resp = requests.get("http://localhost:9222/json/version", timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def setup(remove: bool = False) -> bool:
    """Add (or remove) the debug flag from all installed Chromium browsers.

    Returns True if at least one browser was updated.
    """
    any_found = False
    any_updated = False
    needs_elevation = False

    for browser in BROWSER_REGISTRY:
        name = browser["name"]
        for hive, path in browser["keys"]:
            current = _read_reg_value(hive, path)
            if current is None:
                continue  # browser not installed via this key

            any_found = True
            hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            print(f"  Found {name} ({hive_name}): {current}")

            if remove:
                new_value = _remove_flag_from_command(current, DEBUG_FLAG)
                action = "Removing flag from"
            else:
                new_value = _add_flag_to_command(current, DEBUG_FLAG)
                action = "Adding flag to"

            if new_value == current:
                status = "already set" if not remove else "flag not present"
                print(f"  {name}: {status}, skipping")
                any_updated = True  # counts as success
                continue

            print(f"  {action} {name}...")
            if _write_reg_value(hive, path, new_value):
                print(f"  {name}: done")
                any_updated = True
            else:
                print(f"  {name}: permission denied -- need to run as administrator")
                needs_elevation = True

    if not any_found:
        print("No supported Chromium browsers found in registry.")
        print("Make sure Chrome, Vivaldi, Edge, or Brave is installed.")
        return False

    if needs_elevation and not any_updated:
        print("\nNeed administrator rights. Relaunching elevated...")
        _relaunch_as_admin()
        return False

    return any_updated


def _relaunch_as_admin():
    """Relaunch this script with UAC elevation."""
    import ctypes
    script = os.path.abspath(__file__)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}"', None, 1
    )


def _kill_browser_processes():
    """Gently close any running Chromium browsers so the new flags take effect."""
    import psutil
    targets = {"chrome.exe", "vivaldi.exe", "msedge.exe", "brave.exe"}
    found = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if proc.info["name"].lower() in targets:
                found.append(proc)
        except Exception:
            pass

    if not found:
        return

    print("\nClose your browser and reopen it for changes to take effect.")
    print("Or press Enter here to close it automatically (you will lose open tabs).")
    response = input("[Enter to close browser / Ctrl+C to skip]: ").strip()
    if response == "":
        for proc in found:
            try:
                proc.terminate()
            except Exception:
                pass
        print("Browser closed. Reopen it and website blocking will work.")


def main():
    print("Locus Browser Debug Setup")
    print("=" * 40)
    print("This adds --remote-debugging-port=9222 to your browser")
    print("so Locus can monitor and block websites.\n")

    if "--remove" in sys.argv:
        print("Removing debug port flag...\n")
        success = setup(remove=True)
        if success:
            print("\nDone. Restart your browser for changes to take effect.")
        return

    if is_debug_port_active():
        print("Debug port is already active -- website blocking should already work.")
        print("If it's not working, try restarting Locus.\n")

    print("Updating registry...\n")
    success = setup(remove=False)

    if success:
        print("\nSetup complete.")
        _kill_browser_processes()
        print("\nWebsite blocking will work the next time you open your browser.")
    else:
        print("\nSetup failed. Try running this script as administrator:")
        print("  Right-click PowerShell -> Run as administrator")
        print(f"  python {os.path.abspath(__file__)}")


if __name__ == "__main__":
    main()
