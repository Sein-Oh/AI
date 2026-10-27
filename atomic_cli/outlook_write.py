"""
outlook_write.py - Native Outlook COM Mail Composer, Reply & Forward Engine.
Preserves 100% original conversation history via Outlook's native Reply/Forward methods.
Safely displays draft window on screen by default (Human-in-the-Loop); only sends if --send is explicitly given.
"""
import sys
import os
import argparse
import re
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

def _prepend_to_html_body(html: str, prefix_html: str) -> str:
    """HTML 본문의 <body> 태그 바로 뒤에 새 내용을 삽입합니다 (<html> 앞에 붙여 문서 구조가 깨지는 문제 방지)."""
    if not prefix_html:
        return html
    m = re.search(r"<body[^>]*>", html or "", re.IGNORECASE)
    if m:
        return html[:m.end()] + prefix_html + html[m.end():]
    return prefix_html + (html or "")

def _parse_send_flag(value: Any) -> bool:
    """명시적인 참 값(True, "true", "1", "yes")만 발송 요청으로 인정합니다. ("false" 문자열 등이 참으로 처리되는 사고 방지)"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return False

def _load_default_signature(mail_item) -> None:
    """Inspector를 미리 생성하면 Outlook이 사용자 기본 서명을 본문에 채워 넣습니다 (창은 표시되지 않음)."""
    try:
        _ = mail_item.GetInspector
    except Exception:
        pass

def _finalize(mail_item, send: bool, kind: str, to_desc: str, attached: List[str]) -> Dict[str, Any]:
    """기본은 화면 표시(사용자가 직접 [보내기] 클릭). send=True(명시적 요청)일 때만 수신자 확인 후 발송합니다."""
    subject = mail_item.Subject
    extra = {"to": to_desc, "subject": subject, "attached": attached, "sent": False}

    if send:
        unresolved = []
        try:
            recipients = mail_item.Recipients
            if recipients.Count == 0:
                unresolved.append("(수신자 없음)")
            elif not recipients.ResolveAll():
                for i in range(1, recipients.Count + 1):
                    if not recipients.Item(i).Resolved:
                        unresolved.append(recipients.Item(i).Name)
        except Exception as e:
            unresolved.append(f"(수신자 확인 실패: {e})")

        if unresolved:
            # 주소가 확인되지 않은 메일은 자동 발송하지 않고 사용자 확인 창으로 전환
            mail_item.Display()
            extra["unresolved_recipients"] = unresolved
            return format_response(
                status="partial",
                module="outlook_write",
                action=kind,
                preview=f"Recipient check failed ({', '.join(unresolved)}). Draft displayed on screen instead of sending.",
                agent_directive="STOP_RETRY: 수신자 주소를 확인할 수 없어 발송하지 않고 작성 창만 띄웠습니다. 사용자에게 수신자 확인을 요청하세요.",
                extra=extra
            )

        mail_item.Send()
        extra["sent"] = True
        return format_response(
            status="ok",
            module="outlook_write",
            action=kind,
            preview=f"Sent {kind} mail to '{to_desc}' with subject '{subject}'. Attachments: {len(attached)}",
            agent_directive="VERIFIED: 사용자의 명시적 발송 요청에 따라 메일을 발송했습니다.",
            extra=extra
        )

    mail_item.Display()
    return format_response(
        status="ok",
        module="outlook_write",
        action=kind,
        preview=f"Displayed {kind} mail draft to '{to_desc}' with subject '{subject}' on screen.",
        agent_directive="VERIFIED: 메일 작성 창을 화면에 띄웠습니다. 발송은 사용자가 직접 [보내기]를 눌러야 합니다. 대신 발송하지 마세요.",
        extra=extra
    )

def action_new(app, to: str, cc: str, subject: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """Creates a brand new email. Displays window on screen by default."""
    mail = app.CreateItem(0)  # 0 = olMailItem
    _load_default_signature(mail)
    if to:
        mail.To = to
    if cc:
        mail.CC = cc
    if subject:
        mail.Subject = subject
    if body:
        # Body 대입은 사용자 서명을 지우므로 HTML 본문(서명 포함) 앞에 삽입
        mail.HTMLBody = _prepend_to_html_body(mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(mail, attach)
    return _finalize(mail, send, "new", to, attached)

def _get_target_item(app, ns, entry_id: Optional[str]):
    if entry_id:
        return ns.GetItemFromID(entry_id)
    target_item, _source = get_current_active_item(app)
    return target_item

def action_reply(app, ns, entry_id: Optional[str], reply_all: bool, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Replies to the active or specified email.
    Uses Outlook's native Reply() / ReplyAll() to preserve 100% of original history, headers and formatting.
    """
    target_item = _get_target_item(app, ns, entry_id)
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
    _load_default_signature(reply_mail)

    # Prepend new message above original history
    if body:
        reply_mail.HTMLBody = _prepend_to_html_body(reply_mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(reply_mail, attach)
    return _finalize(reply_mail, send, "reply", reply_mail.To, attached)

def action_forward(app, ns, entry_id: Optional[str], to: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Forwards the active or specified email.
    Uses Outlook's native Forward() to preserve complete original email thread.
    """
    target_item = _get_target_item(app, ns, entry_id)
    if not target_item:
        return format_response(
            status="no_match",
            module="outlook_write",
            action="forward",
            preview="No active email found to forward. Specify --id <entry_id>.",
            agent_directive="STOP_RETRY: No active email found."
        )

    fwd_mail = target_item.Forward()
    _load_default_signature(fwd_mail)
    if to:
        fwd_mail.To = to

    if body:
        fwd_mail.HTMLBody = _prepend_to_html_body(fwd_mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(fwd_mail, attach)
    return _finalize(fwd_mail, send, "forward", to, attached)

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """에이전트/레시피 호출용 실행기.

    params["send"]는 사용자가 '보내줘', '바로 발송' 등 발송을 명시적으로 요청한 경우에만 true로 지정합니다.
    생략하면 작성 창만 화면에 띄우고 사용자가 직접 [보내기]를 누릅니다.
    """
    action = params.get("action", "new")
    try:
        app = app or get_outlook_app()
        ns = get_mapi_namespace(app)

        send_flag = _parse_send_flag(params.get("send", False))
        attach_files = params.get("attach", "") or ""
        body_text = params.get("body", "") or ""

        if action == "new":
            return action_new(app, params.get("to", "") or "", params.get("cc", "") or "", params.get("subject", "") or "", body_text, attach_files, send_flag)
        elif action == "reply":
            return action_reply(app, ns, params.get("id"), _parse_send_flag(params.get("reply_all", False)), body_text, attach_files, send_flag)
        elif action == "forward":
            return action_forward(app, ns, params.get("id"), params.get("to", "") or "", body_text, attach_files, send_flag)
        return format_response(status="error", module="outlook_write", action=action, preview=f"Unknown action: {action}",
                               agent_directive="STOP_RETRY: action은 new, reply, forward 중 하나여야 합니다.")
    except Exception as e:
        return format_response(
            status="error",
            module="outlook_write",
            action=action,
            preview=f"Outlook Compose Error: {e}",
            agent_directive="STOP_RETRY: Check Outlook status or attachment existence."
        )

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
    parser.add_argument("--send", action="store_true",
                        help="사용자가 명시적으로 요청한 경우에만 사용: 화면 표시 대신 수신자 확인 후 즉시 발송 (기본: 작성 창만 표시)")

    args = parser.parse_args()

    params = {
        "action": args.action,
        "id": args.id,
        "to": args.to,
        "cc": args.cc,
        "subject": args.subject,
        "body": args.body,
        "attach": args.attach,
        "reply_all": args.reply_all,
        "send": args.send,
    }
    res = execute(None, None, params)
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
