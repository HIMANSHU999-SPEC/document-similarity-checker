from types import SimpleNamespace

from cvchecker.limits import MAX_FILES, MAX_TOTAL_MB, upload_problem

MB = 1024 * 1024


def _files(n, size_mb=0.2):
    return [SimpleNamespace(size=int(size_mb * MB)) for _ in range(n)]


def test_up_to_600_files_are_accepted():
    assert MAX_FILES == 600
    assert upload_problem(_files(600)) == ""


def test_more_than_600_files_are_refused():
    assert "601 files uploaded. The limit is 600" in upload_problem(_files(601))


def test_total_size_is_capped():
    assert upload_problem(_files(30, 15)) == ""
    message = upload_problem(_files(30, 20))
    assert f"The limit is {MAX_TOTAL_MB} MB per check" in message and "600 MB" in message
