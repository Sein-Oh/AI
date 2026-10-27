"""
_outlook_guard.py - Native Windows Outlook COM Session Guard.
Directly binds to the live Outlook instance on the user's Default desktop.
Zero mock, pure native MAPI COM automation.
"""
import sys
import os
import re
from typing import Optional, Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _com_guard import attach_user_desktop
from _office_utils import log_debug

try:
    import pythoncom
    import win32com.client
    COM_AVAILABLE = True
except ImportError:
    COM_AVAILABLE = False

# Standard Outlook Default Folders (OlDefaultFolders)
OL_FOLDER_MAP = {
    "deleted": 3,
    "outbox": 4,
    "sent": 5,
    "inbox": 6,
    "calendar": 9,
    "contacts": 10,
    "journal": 11,
    "notes": 12,
    "tasks": 13,
    "drafts": 16,
    "junk": 23
}

def get_outlook_app():
    """Binds to live Outlook.Application on the user's Default desktop."""
    if not COM_AVAILABLE:
        raise RuntimeError("pywin32 (win32com) is not installed.")
    
    # Switch to Default desktop to avoid virtual desktop isolation
    attach_user_desktop()
    
    try:
        app = win32com.client.Dispatch("Outlook.Application")
        return app
    except pythoncom.com_error as e:
        raise RuntimeError(f"Failed to connect to Outlook COM: {e}. Ensure MS Outlook is installed.")

def get_mapi_namespace(app=None):
    """Retrieves the MAPI namespace for the active Outlook session."""
    if app is None:
        app = get_outlook_app()
    ns = app.GetNamespace("MAPI")
    try:
        ns.Logon("", "", False, False)
    except pythoncom.com_error:
        pass  # Already logged on
    return ns

def resolve_folder(ns, folder_spec: Optional[str] = None):
    """
    Resolves folder by alias (inbox, sent, drafts) or path ('Account\\SubFolder').
    Defaults to Inbox (6) if omitted.
    """
    spec = (folder_spec or "").strip()
    if not spec or spec.lower() in OL_FOLDER_MAP:
        folder_id = OL_FOLDER_MAP.get(spec.lower(), OL_FOLDER_MAP["inbox"])
        return ns.GetDefaultFolder(folder_id)

    # Path traversal: e.g. "MyAccount\Projects\Work"
    parts = [p for p in re.split(r"[\\/]+", spec) if p]
    try:
        roots = {f.Name: f for f in ns.Folders}
        if parts and parts[0] in roots:
            curr = roots[parts[0]]
            parts = parts[1:]
        else:
            curr = ns.GetDefaultFolder(OL_FOLDER_MAP["inbox"])

        for part in parts:
            found = False
            for sub in curr.Folders:
                if sub.Name.lower() == part.lower():
                    curr = sub
                    found = True
                    break
            if not found:
                raise ValueError(f"Folder part '{part}' not found in path '{spec}'.")
        return curr
    except Exception as e:
        raise RuntimeError(f"Failed to resolve folder '{spec}': {e}")

def get_current_active_item(app=None):
    """
    Captures the mail item the user is currently viewing or selecting in the Outlook UI.
    1. Checks ActiveInspector (mail open in its own window)
    2. Checks ActiveExplorer.Selection (mail highlighted in main list)
    """
    if app is None:
        app = get_outlook_app()

    # 1. Open Inspector window
    try:
        insp = app.ActiveInspector()
        if insp and insp.CurrentItem:
            return insp.CurrentItem, "open_window"
    except Exception:
        pass

    # 2. Selected item in Explorer
    try:
        exp = app.ActiveExplorer()
        if exp and exp.Selection and exp.Selection.Count > 0:
            return exp.Selection.Item(1), "selected_in_list"
    except Exception:
        pass

    return None, "none"
