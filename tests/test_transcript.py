import io
import json
from types import SimpleNamespace

import docx
import pytest

from cvchecker import transcript as tr
from cvchecker.cvdraft import PLACEHOLDER, build_docx, cv_text, draft_cv
from cvchecker.names import MATCH, MISMATCH, NOT_SAID, PARTIAL, check_names

VTT = """WEBVTT

1a2b/10-0
00:00:02.000 --> 00:00:06.000
<v Ms Rivera>Good morning everyone, thanks for joining.</v>

1a2b/11-0
00:14:30.000 --> 00:14:35.000
<v Ms Rivera>Welcome. Could you tell me your full name please?</v>

1a2b/12-0
00:14:36.000 --> 00:14:44.500
<v Aisha Khan>Yes, my name is Aisha Khan. My email is aisha.k@example.com and my number is 07700 900123.</v>

1a2b/13-0
00:14:45.000 --> 00:15:20.000
<v Aisha Khan>I worked at a corner shop on Saturdays and built a spreadsheet to track stock.</v>

1a2b/14-0
00:27:10.000 --> 00:27:15.000
<v Ms Rivera>Thanks Aisha. Next is Bilal.</v>

1a2b/15-0
00:27:20.000 --> 00:27:30.000
<v Bilal Ahmed>Hi, I'm Bilal Ahmed and I repair laptops.</v>
"""


def _docx(paragraphs):
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_vtt_speakers_times_and_text():
    lines = tr.parse_text(VTT)
    assert [ln.speaker for ln in lines[:3]] == ["Ms Rivera", "Ms Rivera", "Aisha Khan"]
    assert lines[2].start == 14 * 60 + 36
    assert "corner shop" in lines[3].text


def test_teams_docx_with_name_and_time_headers():
    data = _docx(["Ms Rivera   0:03", "Tell me about yourself.", "Aisha Khan   0:09",
                  "I love robotics.", "I also run a coding club."])
    lines = tr.load("meeting.docx", data)
    assert [(ln.speaker, ln.start) for ln in lines] == [("Ms Rivera", 3), ("Aisha Khan", 9)]
    assert lines[1].text == "I love robotics. I also run a coding club."


def test_sentence_ending_in_a_time_is_not_a_new_speaker():
    lines = tr.parse_text("Aisha Khan   0:09\nI started work at the shop for 2:30\nMs Rivera 0:20\nGreat.")
    assert [ln.speaker for ln in lines] == ["Aisha Khan", "Ms Rivera"]


def test_vtt_style_text_inside_docx():
    data = _docx(["00:00:05.000 --> 00:00:09.000", "Aisha Khan", "I volunteer at a food bank.", ""])
    lines = tr.load("old.docx", data)
    assert lines[0].speaker == "Aisha Khan" and "food bank" in lines[0].text


@pytest.mark.parametrize("value,seconds", [("14:30", 870), ("1:02:03", 3723), ("00:14:30.500", 870.5)])
def test_parse_time(value, seconds):
    assert tr.parse_time(value) == seconds


def test_bad_time_is_rejected():
    with pytest.raises(ValueError):
        tr.parse_time("half past two")


def test_window_keeps_one_students_part_and_labels_roles():
    lines = tr.parse_text(VTT)
    interviewer = tr.likely_interviewer(lines)
    assert interviewer == "Ms Rivera"
    part = tr.window(lines, tr.parse_time("14:30"), tr.parse_time("27:00"))
    text = tr.labelled(part, {interviewer})
    assert "INTERVIEWER: Welcome" in text and "STUDENT: I worked at a corner shop" in text
    assert "Bilal" not in text and "Good morning" not in text
    assert "Ms Rivera" not in text and "Aisha Khan CV" not in text


def test_shared_room_account_counts_as_the_student():
    lines = tr.parse_text(VTT.replace("<v Aisha Khan>", "<v Meeting Room 3>"))
    part = tr.window(lines, 870, 1620)
    assert "STUDENT: Yes, my name is Aisha Khan" in tr.labelled(part, {"Ms Rivera"})


def test_redact_and_restore_contact_details():
    text, mapping = tr.redact("Email aisha.k@example.com or call 07700 900123 at [0:14:36], again aisha.k@example.com")
    assert "@" not in text and "07700" not in text
    assert "[0:14:36]" in text
    assert text.count("[EMAIL_1]") == 2 and "[PHONE_1]" in text
    restored = tr.restore({"email": "[EMAIL_1]", "list": ["call [PHONE_1]"]}, mapping)
    assert restored == {"email": "aisha.k@example.com", "list": ["call 07700 900123"]}


@pytest.mark.parametrize("entered,said,result", [
    ("Aisha Khan", "aisha khan", MATCH),
    ("Aisha Khan", "Khan, Aisha", MATCH),
    ("Zoë Brown", "Zoe Brown", MATCH),
    ("Aisha Khan", "Aisha Noor Khan", PARTIAL),
    ("Aisha Khan", "Ayesha Kahn", MISMATCH),
    ("Aisha Khan", "Bilal Ahmed", MISMATCH),
    ("Aisha Khan", "", NOT_SAID),
])
def test_name_check(entered, said, result):
    assert check_names(entered, said).result == result


DRAFT = {
    "name_as_said": "Aisha Khan", "email": "[EMAIL_1]", "phone": "[PHONE_1]",
    "profile": {"text": "I enjoy fixing problems with data.", "evidence": "I built a spreadsheet"},
    "skills": [{"text": "Excel spreadsheets", "evidence": "built a spreadsheet"}],
    "experience": [{"role": "Sales Assistant", "organisation": "Corner Shop", "dates": "2024",
                    "points": ["Built a stock-tracking spreadsheet"], "evidence": "I worked at a corner shop"}],
    "education": [{"qualification": "Level 3 Diploma", "institution": "LAAT", "dates": "2023 to 2025",
                   "evidence": "I study at LAAT"}],
    "achievements": [], "interests": [{"text": "Robotics club", "evidence": "I love robotics"}],
    "missing": ["When did you start at the shop?"],
}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(DRAFT))],
                               usage=SimpleNamespace(input_tokens=5000, output_tokens=1500))


def test_draft_request_uses_medium_effort_and_sends_no_contact_details():
    lines = tr.parse_text(VTT)
    text, mapping = tr.redact(tr.labelled(tr.window(lines, 870, 1620), {"Ms Rivera"}))
    client = FakeClient()
    data, usage = draft_cv(client, text)
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5" and call["output_config"]["effort"] == "medium"
    sent = call["messages"][0]["content"]
    assert "@" not in sent and "07700" not in sent and "[EMAIL_1]" in sent
    assert tr.restore(data, mapping)["email"] == "aisha.k@example.com"


def _doc_text(data):
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


def test_build_docx_contains_the_cv():
    text = _doc_text(build_docx("Aisha Khan", tr.restore(DRAFT, {"[EMAIL_1]": "a@x.com", "[PHONE_1]": "0770"})))
    assert text.splitlines()[0] == "Aisha Khan"
    assert "a@x.com | 0770" in text
    assert "Sales Assistant – Corner Shop, 2024" in text
    assert "Robotics club" in text


def test_build_docx_fills_the_template_placeholder():
    template = _docx(["LAAT letterhead", PLACEHOLDER, "Footer text"])
    data = build_docx("Aisha Khan", DRAFT, template, note="Name check overridden: nickname")
    lines = _doc_text(data).splitlines()
    assert lines[0] == "LAAT letterhead" and lines[-1] == "Footer text"
    assert PLACEHOLDER not in "\n".join(lines) and "Aisha Khan" in lines
    assert docx.Document(io.BytesIO(data)).core_properties.comments.startswith("Name check overridden")


def test_cv_text_covers_every_section():
    body = cv_text(DRAFT)
    for part in ("I enjoy fixing problems", "Excel", "Corner Shop", "Level 3 Diploma", "Robotics"):
        assert part in body


def test_blank_entries_added_by_staff_are_left_out_of_the_cv():
    draft = dict(DRAFT, experience=DRAFT["experience"] + [{"role": "", "organisation": "", "dates": "", "points": [],
                                                          "evidence": "Added by staff"}],
                 education=[{"qualification": "", "institution": "", "dates": "", "evidence": ""}])
    text = _doc_text(build_docx("Aisha Khan", draft))
    assert "Education" not in text
    assert text.count("Sales Assistant") == 1


from cvchecker.cvdraft import CV_MARKER, UPDATE_SYSTEM
from cvchecker.names import matching_cvs

EXISTING_CV = ("Aisha Khan\naisha.k@example.com | 07700 900123\nProfile\nI like IT.\nWork Experience\n"
               "Sales Assistant, Corner Shop, 2023\nServed customers at the till.")


def test_matching_cvs_finds_the_student_by_file_name_or_first_line():
    names = ["Bilal Ahmed CV.pdf", "cv_final.docx", "Aisha Khan - CV (2).pdf"]
    texts = ["Bilal Ahmed\n...", "Aisha Khan\nProfile", "Someone\n..."]
    assert matching_cvs("Aisha Khan", names, texts) == [1, 2]
    assert matching_cvs("Khan, Aisha", names, texts) == [1, 2]
    assert matching_cvs("Chen Li", names, texts) == []


def test_update_sends_cv_and_transcript_without_contact_details():
    lines = tr.parse_text(VTT)
    labelled = tr.labelled(tr.window(lines, 870, 1620), {"Ms Rivera"})
    combined, mapping = tr.redact(labelled + CV_MARKER + EXISTING_CV)
    sent_transcript, sent_cv = combined.split(CV_MARKER, 1)
    client = FakeClient()
    data, _ = draft_cv(client, sent_transcript, sent_cv)
    call = client.calls[0]
    assert call["system"] == UPDATE_SYSTEM
    payload = json.loads(call["messages"][0]["content"])
    assert set(payload) == {"existing_cv", "transcript"}
    assert "Served customers at the till" in payload["existing_cv"] and "corner shop" in payload["transcript"]
    sent = call["messages"][0]["content"]
    assert "@" not in sent and "07700" not in sent
    assert sent_cv.count("[EMAIL_1]") == 1 and sent_transcript.count("[EMAIL_1]") == 1
    assert data["conflicts"] == []


def test_new_cv_requests_still_use_the_original_prompt():
    client = FakeClient()
    draft_cv(client, "[0:01] STUDENT: hello")
    assert client.calls[0]["system"] != UPDATE_SYSTEM
    assert json.loads(client.calls[0]["messages"][0]["content"]) == {"transcript": "[0:01] STUDENT: hello"}
