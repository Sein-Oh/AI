"""
outlook_write.py - Native Outlook COM Mail Composer, Reply & Forward Engine.
Preserves 100% original conversation history via Outlook's native Reply/Forward methods.
Safely displays draft window on screen by default (Human-in-the-Loop); only sends if --send is explicitly given.
"""
import sys
import os
import argparse
import json
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response
from _outlook_guard import get_outlook_app, get_mapi_namespace, get_current_active_item
from _config import resolve_data_path, get_data_dir

def _attach_files_to_item(mail_item, attach_arg: Optional[str]) -> List[str]:
    """Resolves and attaches files using data_dir path resolver."""
    attached = []
    if not attach_arg:
        return attached

    # Split comma-separated files
    files = [f.strip() for f in attach_arg.split(",") if f.strip()]
    for f in files:
        resolved = resolve_data_path(f)
        if os.path.exists(resolved):
            mail_item.Attachments.Add(resolved)
            attached.append(os.path.basename(resolved))
        else:
            raise FileNotFoundError(f"Attachment file not found: {resolved}")
    return attached

def _format_html_body_prefix(plain_text: str) -> str:
    """Wraps user text in clean styled HTML div to prepend above original history."""
    if not plain_text:
        return ""
    html_lines = plain_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return (
        f"<div style='font-family: \"Malgun Gothic\", \"Segoe UI\", sans-serif; font-size: 10pt; color: #111;'>"
        f"{html_lines}"
        f"</div><br>"
    )

def action_new(app, to: str, cc: str, subject: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """Creates a brand new email. Displays window on screen by default."""
    mail = app.CreateItem(0)  # 0 = olMailItem
    if to:
        mail.To = to
    if cc:
        mail.CC = cc
    if subject:
        mail.Subject = subject
    if body:
        mail.Body = body

    attached = _attach_files_to_item(mail, attach)

    if send:
        mail.Send()
        return format_response(
            status="ok",
            module="outlook_write",
            action="new_sent",
            preview=f"Sent email to '{to}' with subject '{subject}'. Attachments: {len(attached)}",
            agent_directive="VERIFIED: Email sent in background.",
            extra={"to": to, "subject": subject, "attached": attached}
        )
    else:
        mail.Display()
        return format_response(
            status="ok",
            module="outlook_write",
            action="new_display",
            preview=f"Displayed new mail draft to '{to}' with subject '{subject}' on screen.",
            agent_directive="VERIFIED: New email draft opened on user's screen. Awaiting user click on Send button.",
            extra={"to": to, "subject": subject, "attached": attached}
        )

def action_reply(app, ns, entry_id: Optional[str], reply_all: bool, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Replies to the active or specified email.
    Uses Outlook's native Reply() / ReplyAll() to preserve 100% of original history, headers and formatting.
    """
    target_item = None
    if entry_id:
        target_item = ns.GetItemFromID(entry_id)
    else:
        target_item, source = get_current_active_item(app)
        if not target_item:
            return format_response(
                status="no_match",
                module="outlook_write",
                action="reply",
                preview="No active email is currently open or selected to reply to. Specify --id <entry_id>.",
                agent_directive="STOP_RETRY: No active email found. User must select an email or provide --id."
            )

    # Use native Reply / ReplyAll to retain native headers & thread lineage
    reply_mail = target_item.ReplyAll() if reply_all else target_item.Reply()

    # Prepend new message above original history
    if body:
        prefix_html = _format_html_body_prefix(body)
        reply_mail.HTMLBody = prefix_html + reply_mail.HTMLBody

    attached = _attach_files_to_item(reply_mail, attach)

    if send:
        reply_mail.Send()
        return format_response(
            status="ok",
            module="outlook_write",
            action="reply_sent",
            preview=f"Sent native reply to '{reply_mail.To}' with subject '{reply_mail.Subject}'.",
            agent_directive="VERIFIED: Reply sent with original history intact.",
            extra={"to": reply_mail.To, "subject": reply_mail.Subject, "attached": attached}
        )
    else:
        reply_mail.Display()
        return format_response(
            status="ok",
            module="outlook_write",
            action="reply_display",
            preview=f"Displayed native reply window on screen for '{reply_mail.Subject}' with complete history intact.",
            agent_directive="VERIFIED: Reply window opened on user screen with original history preserved. Awaiting user click on Send.",
            extra={"to": reply_mail.To, "subject": reply_mail.Subject, "attached": attached}
        )

def action_forward(app, ns, entry_id: Optional[str], to: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Forwards the active or specified email.
    Uses Outlook's native Forward() to preserve complete original email thread.
    """
    target_item = None
    if entry_id:
        target_item = ns.GetItemFromID(entry_id)
    else:
        target_item, source = get_current_active_item(app)
        if not target_item:
            return format_response(
                status="no_match",
                module="outlook_write",
                action="forward",
                preview="No active email found to forward. Specify --id <entry_id>.",
                agent_directive="STOP_RETRY: No active email found."
            )

    fwd_mail = target_item.Forward()
    if to:
        fwd_mail.To = to

    if body:
        prefix_html = _format_html_body_prefix(body)
        fwd_mail.HTMLBody = prefix_html + fwd_mail.HTMLBody

    attached = _attach_files_to_item(fwd_mail, attach)

    if send:
        fwd_mail.Send()
        return format_response(
            status="ok",
            module="outlook_write",
            action="forward_sent",
            preview=f"Forwarded email to '{to}' with subject '{fwd_mail.Subject}'.",
            agent_directive="VERIFIED: Forwarded email sent.",
            extra={"to": to, "subject": fwd_mail.Subject, "attached": attached}
        )
    else:
        fwd_mail.Display()
        return format_response(
            status="ok",
            module="outlook_write",
            action="forward_display",
            preview=f"Displayed forward window on screen for '{fwd_mail.Subject}' to '{to}' with complete thread intact.",
            agent_directive="VERIFIED: Forward window opened on user screen. Awaiting user click on Send.",
            extra={"to": to, "subject": fwd_mail.Subject, "attached": attached}
        )

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py recipe dispatcher compatible executor."""
    action = params.get("action", "new")
    app = app or get_outlook_app()
    ns = get_mapi_namespace(app)

    send_flag = bool(params.get("send", False))
    attach_files = params.get("attach", "")
    body_text = params.get("body", "")

    if action == "new":
        return action_new(app, params.get("to", ""), params.get("cc", ""), params.get("subject", ""), body_text, attach_files, send_flag)
    elif action == "reply":
        return action_reply(app, ns, params.get("id"), bool(params.get("reply_all", False)), body_text, attach_files, send_flag)
    elif action == "forward":
        return action_forward(app, ns, params.get("id"), params.get("to", ""), body_text, attach_files, send_flag)
    else:
        return format_response(status="error", module="outlook_write", action=action, preview=f"Unknown action: {action}")

def main():
    parser = argparse.ArgumentParser(description="Outlook Safe Mail Composer, Reply & Forward Engine")
    parser.add_argument("--action", choices=["new", "reply", "forward"], required=True,
                        help="Action to perform: new, reply, forward")
    parser.add_argument("--id", type=str, help="EntryID of the email to reply or forward (defaults to currently active mail)")
    parser.add_argument("--to", type=str, help="Recipient email address(es)")
    parser.add_argument("--cc", type=str, help="CC recipient email address(es)")
    parser.add_argument("--subject", type=str, help="Email subject")
    parser.add_argument("--body", type=str, help="Email body text to prepend")
    parser.add_argument("--attach", type=str, help="Comma-separated filenames/paths to attach from data_dir")
    parser.add_argument("--reply-all", action="store_true", help="Reply to all recipients on reply action")
    parser.add_argument("--send", action="store_true", help="Explicitly send immediately instead of displaying draft on screen")

    args = parser.parse_args()

    try:
        app = get_outlook_app()
        ns = get_mapi_namespace(app)

        if args.action == "new":
            res = action_new(app, args.to or "", args.cc or "", args.subject or "", args.body or "", args.attach or "", args.send)
        elif args.action == "reply":
            res = action_reply(app, ns, args.id, args.reply_all, args.body or "", args.attach or "", args.send)
        elif args.action == "forward":
            res = action_forward(app, ns, args.id, args.to or "", args.body or "", args.attach or "", args.send)
        else:
            res = format_response(status="error", module="outlook_write", action=args.action, preview=f"Unknown action: {args.action}")

        emit_response(res)

    except Exception as e:
        emit_response(format_response(
            status="error",
            module="outlook_write",
            action=args.action,
            preview=f"Outlook Compose Error: {str(e)}",
            agent_directive="STOP_RETRY: Check Outlook status or attachment existence."
        ))
        sys.exit(1)

if __name__ == "__main__":
    main()
