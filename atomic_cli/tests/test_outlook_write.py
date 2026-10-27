import outlook_write as ow


class FakeRecipient:
    def __init__(self, name, resolved):
        self.Name = name
        self.Resolved = resolved


class FakeRecipients:
    def __init__(self, items):
        self._items = items

    @property
    def Count(self):
        return len(self._items)

    def Item(self, i):
        return self._items[i - 1]

    def ResolveAll(self):
        return all(r.Resolved for r in self._items)


class FakeMail:
    def __init__(self, recipients):
        self.Subject = "제목"
        self.Recipients = FakeRecipients(recipients)
        self.sent = False
        self.displayed = False

    def Send(self):
        self.sent = True

    def Display(self):
        self.displayed = True


def test_send_flag_requires_explicit_true():
    assert ow._parse_send_flag(True) is True
    assert ow._parse_send_flag("true") is True
    assert ow._parse_send_flag("false") is False
    assert ow._parse_send_flag("") is False
    assert ow._parse_send_flag(None) is False


def test_default_displays_and_does_not_send():
    mail = FakeMail([FakeRecipient("a@x.com", True)])
    res = ow._finalize(mail, send=False, kind="new", to_desc="a@x.com", attached=[])
    assert mail.displayed and not mail.sent
    assert res["sent"] is False


def test_explicit_send_sends_when_recipients_resolve():
    mail = FakeMail([FakeRecipient("a@x.com", True)])
    res = ow._finalize(mail, send=True, kind="new", to_desc="a@x.com", attached=[])
    assert mail.sent and res["status"] == "ok" and res["sent"] is True


def test_explicit_send_falls_back_to_display_on_unresolved_recipient():
    mail = FakeMail([FakeRecipient("오타주소", False)])
    res = ow._finalize(mail, send=True, kind="new", to_desc="오타주소", attached=[])
    assert not mail.sent and mail.displayed
    assert res["status"] == "partial"
    assert res["unresolved_recipients"] == ["오타주소"]


def test_explicit_send_without_recipients_is_not_sent():
    mail = FakeMail([])
    res = ow._finalize(mail, send=True, kind="new", to_desc="", attached=[])
    assert not mail.sent and res["status"] == "partial"


def test_prepend_goes_inside_body():
    html = "<html><head></head><body lang=KO><p>서명</p></body></html>"
    out = ow._prepend_to_html_body(html, "<div>새 내용</div>")
    assert out.index("<div>새 내용</div>") > out.index("<body lang=KO>")
    assert out.index("<div>새 내용</div>") < out.index("<p>서명</p>")
