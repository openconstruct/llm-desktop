import os
from pathlib import Path


def normalize_file_picker_result(result) -> tuple[list[str], list[dict]]:
    """
    Normalize Flet FilePicker results across versions.

    Returns:
      (paths, error_docs)

    - `paths`: list of filesystem paths we can read.
    - `error_docs`: document-shaped dicts for items where we could not derive a readable path.
    """
    file_items = getattr(result, "files", None) or []
    paths: list[str] = []
    error_docs: list[dict] = []

    def add_error_doc(name: str | None, size: int | None, msg: str) -> None:
        error_docs.append(
            {
                "name": name or "Unknown file",
                "path": "",
                "size": int(size or 0),
                "type": Path(name or "").suffix.lower(),
                "content": "",
                "error": msg,
            }
        )

    if file_items:
        for item in file_items:
            if isinstance(item, str):
                if item:
                    paths.append(item)
                continue

            path = getattr(item, "path", None)
            if isinstance(path, str) and path:
                paths.append(path)
                continue


            name = getattr(item, "name", None)
            if isinstance(name, str) and name and os.path.exists(name):
                paths.append(name)
                continue

            add_error_doc(
                name if isinstance(name, str) else None,
                getattr(item, "size", 0),
                "File picker did not provide a readable path.",
            )
    else:

        path = getattr(result, "path", None)
        if isinstance(path, str) and path:
            paths.append(path)


    seen: set[str] = set()
    uniq_paths: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        uniq_paths.append(p)

    return uniq_paths, error_docs

