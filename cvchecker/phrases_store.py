import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cvchecker.names import name_parts
from cvchecker.prepare import TOKEN, normalize

DEFAULT_PATH = Path.home() / "cvapp" / "data" / "learned_phrases.json"
MIN_WORDS, MAX_WORDS, MAX_PER_CV = 3, 15, 5
FILE_NAME_NOISE = {"cv", "resume", "curriculum", "vitae", "final", "draft", "copy", "new", "updated", "version"}
COMMON_WORDS = {"i", "a", "an", "the", "and", "of", "in", "my", "am", "to", "is", "at", "for", "on", "with"}


class StoreError(Exception):
    pass


def phrase_key(phrase: str) -> str:
    return " ".join(normalize(m.group()) for m in TOKEN.finditer(phrase))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Phrases:
    learned: list[dict] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    warning: str = ""

    @property
    def keys(self) -> set[str]:
        return {p["key"] for p in self.learned} | {p["key"] for p in self.ignored}


class PhraseStore:
    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else DEFAULT_PATH
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _read(self) -> Phrases:
        if not self.path.exists():
            return Phrases()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("learned", []), list) \
                    or not isinstance(data.get("ignored", []), list):
                raise ValueError("unexpected structure")
            return Phrases(list(data.get("learned", [])), list(data.get("ignored", [])))
        except (ValueError, OSError):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            kept = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            try:
                os.replace(self.path, kept)
            except OSError:
                kept = self.path
            return Phrases(warning=f"The learned phrases file couldn't be read. It was kept as {kept.name} "
                                   "and the app is using the built-in phrases.")

    @contextmanager
    def _locked(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with open(self.lock_path, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as e:
            raise StoreError(f"Couldn't save the learned phrases file ({e.strerror or e}).") from e

    def _write(self, phrases: Phrases):
        data = {"version": 1, "learned": phrases.learned, "ignored": phrases.ignored}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".learned_phrases.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self) -> Phrases:
        return self._read()

    def _change(self, apply):
        with self._locked():
            phrases = self._read()  # a corrupt file is moved aside here, so saving starts a fresh one
            apply(phrases)
            try:
                self._write(phrases)
            except OSError as e:
                raise StoreError(f"Couldn't save the learned phrases file ({e.strerror or e}).") from e

    def add(self, phrase: str, email: str):
        key = phrase_key(phrase)

        def apply(p):
            p.ignored = [x for x in p.ignored if x["key"] != key]
            if key not in {x["key"] for x in p.learned}:
                p.learned.append({"phrase": phrase, "key": key, "added_by": email,
                                  "added_at": _now(), "source": "claude"})
        self._change(apply)

    def ignore(self, phrase: str, email: str):
        key = phrase_key(phrase)

        def apply(p):
            if key not in {x["key"] for x in p.ignored}:
                p.ignored.append({"phrase": phrase, "key": key, "ignored_by": email, "ignored_at": _now()})
        self._change(apply)

    def remove(self, key: str):
        def apply(p):
            p.learned = [x for x in p.learned if x["key"] != key]
        self._change(apply)


def name_words(doc, file_name: str) -> set[str]:
    """Words that may be the student's name: the first few words of the CV and the file name."""
    stem = file_name.rsplit(".", 1)[0]
    return (set(doc.tokens[:3]) | (set(name_parts(stem)) - FILE_NAME_NOISE)) - COMMON_WORDS


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def validate_suggestions(review, doc, file_name: str, known_keys: set[str]) -> list[tuple[str, str]]:
    """Claude's common-phrase suggestions for one CV that pass every safety check, as (phrase, key)."""
    stock = []
    for item in review.items:
        verdict = review.verdicts.get(item["id"], ("",))[0]
        if verdict == "template_or_stock":
            stock.append([normalize(m.group()) for m in TOKEN.finditer(item["passage"])])
    names = name_words(doc, file_name)
    out, seen = [], set()
    for phrase in review.common_phrases:
        words = phrase_key(phrase).split()
        key = " ".join(words)
        if not (MIN_WORDS <= len(words) <= MAX_WORDS):
            continue
        if any(ch.isdigit() for ch in phrase) or "@" in phrase:
            continue
        if not any(_contains(passage, words) for passage in stock):
            continue
        if not _contains(doc.tokens, words):
            continue
        if names & set(words):
            continue
        if key in known_keys or key in seen:
            continue
        seen.add(key)
        out.append((phrase.strip(), key))
        if len(out) == MAX_PER_CV:
            break
    return out
