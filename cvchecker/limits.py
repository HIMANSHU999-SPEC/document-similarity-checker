MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 600
MAX_TOTAL_MB = 500  # uploads are held in memory; the server has 2 GB


def upload_problem(files) -> str:
    """Why a set of uploads can't be checked, or "" if it can."""
    if len(files) > MAX_FILES:
        return f"{len(files)} files uploaded. The limit is {MAX_FILES} per check."
    total_mb = sum(f.size for f in files) / (1024 * 1024)
    if total_mb > MAX_TOTAL_MB:
        return (f"These files add up to {total_mb:.0f} MB. The limit is {MAX_TOTAL_MB} MB per check, so the server "
                "doesn't run out of memory. Split the batch, or remove very large scanned files.")
    return ""
