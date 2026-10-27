"""
outlook_read.py - Native Outlook COM Mail Reader & High-Speed Search Engine.
Operates 100% in the background without disturbing user screen.
Supports current active mail capture, built-in Outlook search, folder tree,
and automatic attachment downloading to atomic-cli/data/.
"""
import sys
import os
import argparse
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response
from _outlook_guard import get_outlook_app, get_mapi_namespace, resolve_folder, get_current_active_item
from _config import get_data_dir

def _item_to_summary(item) -> Dict[str, Any]:
    """Extracts clean serializable metadata from an Outlook MailItem."""
    entry_id = getattr(item, "EntryID", "")
    subject = getattr(item, "Subject", "(No Subject)")
    sender = getattr(item, "SenderName", "")
    sender_email = getattr(item, "SenderEmailAddress", "")
    try:
        received = str(item.ReceivedTime)
    except Exception:
        received = ""
    unread = bool(getattr(item, "UnRead", False))
    has_attach = bool(getattr(item, "Attachments", None) and item.Attachments.Count > 0)
    attach_count = item.Attachments.Count if has_attach else 0

    return {
        "id": entry_id,
        "subject": subject,
        "sender": f"{sender} <{sender_email}>" if sender_email else sender,
        "received": received,
        "unread": unread,
        "attachments_count": attach_count
    }

def action_current(app, ns, summarize: bool=False) -> Dict[str, Any]:
    """Captures the mail currently open or selected by the user."""
    item, source = get_current_active_item(app)
    if not item:
        return format_response(
            status="no_match",
            module="outlook_read",
            action="current",
            preview="No mail is currently open in a window or selected in the Outlook list.",
            agent_directive="STOP_RETRY: User has not selected any email in Outlook."
        )

    summary = _item_to_summary(item)
    summary["source"] = source
    body_full = getattr(item, "Body", "")
    body_snippet = body_full[:500]
    summary["body_preview"] = body_snippet.replace("\r\n", " ").strip()

    if summarize:
        # 간단 요약: 제목 + 발신자 + 수신자 + 첫 300자
        to_addr = getattr(item, "To", "")
        cc_addr = getattr(item, "CC", "")
        summary["summary"] = {
            "subject": summary["subject"],
            "from": summary["sender"],
            "to": to_addr,
            "cc": cc_addr,
            "received": summary["received"],
            "body_head": body_full[:300].replace("\r\n", " ").strip()
        }
        preview_msg = f"Captured {source} mail and summarized: '{summary['subject']}' from {summary['sender']}"
    else:
        preview_msg = f"Captured {source} mail: '{summary['subject']}' from {summary['sender']}"

    return format_response(
        status="ok",
        module="outlook_read",
        action="current",
        preview=preview_msg,
        agent_directive="VERIFIED: Active mail captured. Ready for reply or inspection.",
        extra={"mail": summary}
    )

def action_list(ns, folder_name: str, unread_only: bool, limit: int) -> Dict[str, Any]:
    """Lists recent emails from specified folder in background."""
    folder = resolve_folder(ns, folder_name)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)  # Descending order (newest first)

    if unread_only:
        items = items.Restrict("[UnRead] = True")

    results = []
    count = 0
    for item in items:
        if count >= limit:
            break
        # Only process mail items (MessageClass = IPM.Note)
        if getattr(item, "Class", 0) == 43:  # olMail
            results.append(_item_to_summary(item))
            count += 1

    return format_response(
        status="ok",
        module="outlook_read",
        action="list",
        preview=f"Fetched {len(results)} mails from folder '{folder.Name}' (Unread only: {unread_only})",
        agent_directive="VERIFIED: Mail list retrieved successfully.",
        extra={"folder": folder.Name, "count": len(results), "mails": results}
    )

def action_search(ns, folder_name: str, query: str, sender_filter: str, limit: int) -> Dict[str, Any]:
    """Searches emails directly using Outlook's native Restrict engine (DASL/Jet)."""
    folder = resolve_folder(ns, folder_name)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)

    filter_clauses = []
    if query:
        q_clean = query.replace("'", "''")
        filter_clauses.append(f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{q_clean}%' OR \"urn:schemas:httpmail:textdescription\" LIKE '%{q_clean}%'")
    if sender_filter:
        s_clean = sender_filter.replace("'", "''")
        filter_clauses.append(f"@SQL=\"urn:schemas:httpmail:fromname\" LIKE '%{s_clean}%' OR \"urn:schemas:httpmail:fromemail\" LIKE '%{s_clean}%'")

    if filter_clauses:
        dasl_filter = " AND ".join(filter_clauses)
        try:
            items = items.Restrict(dasl_filter)
        except Exception:
            # Fallback to Jet query if complex DASL fails
            if query:
                items = items.Restrict(f"[Subject] = '{query}'")

    results = []
    count = 0
    for item in items:
        if count >= limit:
            break
        if getattr(item, "Class", 0) == 43:
            results.append(_item_to_summary(item))
            count += 1

    return format_response(
        status="ok" if results else "no_match",
        module="outlook_read",
        action="search",
        preview=f"Found {len(results)} mails matching '{query or sender_filter}' in '{folder.Name}'",
        agent_directive="VERIFIED: Outlook native search complete." if results else "STOP_RETRY: No matching emails found.",
        extra={"query": query, "folder": folder.Name, "count": len(results), "mails": results}
    )

def action_read(ns, entry_id: str, save_attach: bool) -> Dict[str, Any]:
    """Reads full content of a specific email by EntryID and saves attachments if requested."""
    try:
        item = ns.GetItemFromID(entry_id)
    except Exception as e:
        return format_response(
            status="error",
            module="outlook_read",
            action="read",
            preview=f"Mail with EntryID '{entry_id}' not found: {e}",
            agent_directive="STOP_RETRY: Invalid EntryID."
        )

    summary = _item_to_summary(item)
    summary["body"] = getattr(item, "Body", "")
    summary["to"] = getattr(item, "To", "")
    summary["cc"] = getattr(item, "CC", "")

    saved_files = []
    if save_attach and item.Attachments.Count > 0:
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        for i in range(1, item.Attachments.Count + 1):
            att = item.Attachments.Item(i)
            safe_filename = att.FileName
            dest_path = os.path.join(data_dir, safe_filename)
            att.SaveAsFile(dest_path)
            saved_files.append(safe_filename)

    summary["saved_attachments"] = saved_files

    return format_response(
        status="ok",
        module="outlook_read",
        action="read",
        preview=f"Read mail '{summary['subject']}' from {summary['sender']}. Attachments saved: {len(saved_files)}",
        agent_directive="VERIFIED: Mail content and attachments extracted.",
        extra={"mail": summary}
    )

def action_folders(ns) -> Dict[str, Any]:
    """Lists folder hierarchy and unread mail counts."""
    tree = []
    for store in ns.Folders:
        store_info = {
            "account": store.Name,
            "folders": []
        }
        for f in store.Folders:
            try:
                unread = f.UnReadItemCount
                total = f.Items.Count
            except Exception:
                unread, total = 0, 0
            store_info["folders"].append({
                "name": f.Name,
                "unread": unread,
                "total": total
            })
        tree.append(store_info)

    return format_response(
        status="ok",
        module="outlook_read",
        action="folders",
        preview=f"Discovered {len(tree)} Outlook accounts/stores with folder statistics.",
        agent_directive="VERIFIED: Folder hierarchy retrieved.",
        extra={"accounts": tree}
    )

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py recipe dispatcher compatible executor."""
    action = params.get("action", "list")
    app = app or get_outlook_app()
    ns = get_mapi_namespace(app)

    if action == "current":
        return action_current(app, ns, bool(params.get("summarize", False)))
    elif action == "list":
        return action_list(ns, params.get("folder", "inbox"), bool(params.get("unread", False)), int(params.get("limit", 10)))
    elif action == "search":
        return action_search(ns, params.get("folder", "inbox"), params.get("query", ""), params.get("from", ""), int(params.get("limit", 10)))
    elif action == "read":
        entry_id = params.get("id")
        if not entry_id:
            return format_response(status="error", module="outlook_read", action="read", preview="Missing 'id' param")
        return action_read(ns, entry_id, bool(params.get("save_attach", False)))
    elif action == "folders":
        return action_folders(ns)
    else:
        return format_response(status="error", module="outlook_read", action=action, preview=f"Unknown action: {action}")

def main():
    parser = argparse.ArgumentParser(description="Outlook Background Mail Reader & Native Search Engine")
    parser.add_argument("--action", choices=["current", "list", "search", "read", "folders"], required=True,
                        help="Action to perform: current, list, search, read, folders")
    parser.add_argument("--id", type=str, help="EntryID of the email to read")
    parser.add_argument("--folder", type=str, default="inbox", help="Folder name or alias (default: inbox)")
    parser.add_argument("--unread", action="store_true", help="Filter for unread emails only")
    parser.add_argument("--query", type=str, help="Search query string for subject/body")
    parser.add_argument("--from", dest="from_sender", type=str, help="Filter by sender name or email")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of emails to return (default: 10)")
    parser.add_argument("--save-attach", action="store_true", help="Automatically save all attachments to data_dir")
    parser.add_argument("--summarize", action="store_true", help="Summarize current selected mail")

    args = parser.parse_args()

    try:
        app = get_outlook_app()
        ns = get_mapi_namespace(app)

        if args.action == "current":
            res = action_current(app, ns, args.summarize)
        elif args.action == "list":
            res = action_list(ns, args.folder, args.unread, args.limit)
        elif args.action == "search":
            res = action_search(ns, args.folder, args.query, args.from_sender, args.limit)
        elif args.action == "read":
            if not args.id:
                emit_response(format_response(
                    status="error",
                    module="outlook_read",
                    action="read",
                    preview="--id <entry_id> is required for read action.",
                    agent_directive="STOP_RETRY: Missing --id."
                ))
                sys.exit(1)
            res = action_read(ns, args.id, args.save_attach)
        elif args.action == "folders":
            res = action_folders(ns)
        else:
            res = format_response(status="error", module="outlook_read", action=args.action, preview=f"Unknown action: {args.action}")

        emit_response(res)

    except Exception as e:
        emit_response(format_response(
            status="error",
            module="outlook_read",
            action=args.action,
            preview=f"Outlook COM Error: {str(e)}",
            agent_directive="STOP_RETRY: Verify Outlook is installed and running on Default desktop."
        ))
        sys.exit(1)

if __name__ == "__main__":
    main()
