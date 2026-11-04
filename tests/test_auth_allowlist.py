from cvchecker.auth import email_allowed

DOMAINS = ["laat.ac.uk"]
EMAILS = ["himanshu@laat.ac.uk", "Bhavishya.Chilea@laat.ac.uk"]


def test_listed_email_allowed_any_case():
    assert email_allowed("himanshu@laat.ac.uk", DOMAINS, EMAILS)
    assert email_allowed("HIMANSHU@LAAT.AC.UK", DOMAINS, EMAILS)
    assert email_allowed("bhavishya.chilea@laat.ac.uk", DOMAINS, EMAILS)


def test_unlisted_email_blocked_even_on_domain():
    assert not email_allowed("someone.else@laat.ac.uk", DOMAINS, EMAILS)
    assert not email_allowed("himanshu@gmail.com", DOMAINS, EMAILS)
    assert not email_allowed("", DOMAINS, EMAILS)


def test_no_list_falls_back_to_domain():
    assert email_allowed("anyone@laat.ac.uk", DOMAINS, None)
    assert email_allowed("anyone@laat.ac.uk", DOMAINS, [])
    assert not email_allowed("anyone@gmail.com", DOMAINS, [])
