import re
import unicodedata
from dataclasses import dataclass

MATCH, PARTIAL, MISMATCH, NOT_SAID = "Match", "Partial match", "Mismatch", "Name not said"


@dataclass
class NameCheck:
    result: str
    message: str

    @property
    def can_save(self) -> bool:
        return self.result == MATCH


def name_parts(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c)).lower()
    if "," in name:
        surname, _, given = name.partition(",")
        name = f"{given} {surname}"
    return re.findall(r"[a-z]+(?:'[a-z]+)?", name.replace("-", " "))


def check_names(entered: str, said: str) -> NameCheck:
    a, b = name_parts(entered), name_parts(said)
    if not a:
        return NameCheck(MISMATCH, "Enter the student's full name.")
    if not b:
        return NameCheck(NOT_SAID, "The student's name wasn't found in this part of the recording. "
                                   "Check the times, or confirm the name yourself.")
    if sorted(a) == sorted(b):
        return NameCheck(MATCH, f"The name in the recording matches: {said}.")
    shorter, longer = (set(a), set(b)) if len(a) <= len(b) else (set(b), set(a))
    if len(shorter) >= 2 and shorter <= longer:
        return NameCheck(PARTIAL, f"Close but not identical: you entered “{entered}”, "
                                  f"the recording says “{said}”. Confirm before saving.")
    return NameCheck(MISMATCH, f"You entered “{entered}” but the recording says “{said}”. "
                               "Check the times and the name before saving.")


FILE_NAME_NOISE = {"cv", "resume", "curriculum", "vitae", "final", "draft", "copy", "new", "updated", "version"}


def matching_cvs(student: str, file_names, texts) -> list[int]:
    """Indexes of CVs whose file name or first line names this student, exact matches only."""
    wanted = sorted(name_parts(student))
    if not wanted:
        return []
    found = []
    for i, (name, text) in enumerate(zip(file_names, texts)):
        stem = [w for w in name_parts(name.rsplit(".", 1)[0]) if w not in FILE_NAME_NOISE]
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        if sorted(stem) == wanted or sorted(name_parts(first_line)) == wanted:
            found.append(i)
    return found


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
