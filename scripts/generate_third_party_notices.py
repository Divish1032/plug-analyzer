#!/usr/bin/env python3
"""Generate a deterministic license inventory for bundled runtime dependencies.

The inventory walks the installed dependency closure of ``plug-analyzer``. Extras
requested by a dependency (for example ``nd2[legacy]``) are carried into marker
evaluation so their runtime packages are not silently omitted.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
import re
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from collections.abc import Iterable


LICENSE_FILE_RE = re.compile(
    r"^(licen[cs]e|copying|copyright|notice|authors?)(\..*)?$", re.IGNORECASE
)


class NoticeError(RuntimeError):
    """Raised when an accurate installed dependency inventory cannot be made."""


def _installed_distributions() -> dict[str, metadata.Distribution]:
    installed: dict[str, metadata.Distribution] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            installed[canonicalize_name(name)] = distribution
    return installed


def _marker_applies(requirement: Requirement, active_extras: set[str]) -> bool:
    if requirement.marker is None:
        return True
    # Evaluate once without an extra and once for every active extra. This is
    # how metadata such as ``dependency; extra == 'legacy'`` is included.
    return any(
        requirement.marker.evaluate({"extra": extra}) for extra in ["", *sorted(active_extras)]
    )


def runtime_closure(root_name: str) -> list[metadata.Distribution]:
    installed = _installed_distributions()
    canonical_root = canonicalize_name(root_name)
    if canonical_root not in installed:
        raise NoticeError(
            f"distribution {root_name!r} is not installed; sync the project .venv first"
        )

    extras_by_name: dict[str, set[str]] = {canonical_root: set()}
    pending: deque[str] = deque([canonical_root])
    processed_extras: dict[str, frozenset[str]] = {}

    while pending:
        name = pending.popleft()
        active_extras = extras_by_name[name]
        snapshot = frozenset(active_extras)
        if processed_extras.get(name) == snapshot:
            continue
        processed_extras[name] = snapshot
        distribution = installed[name]

        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if not _marker_applies(requirement, active_extras):
                continue
            dependency_name = canonicalize_name(requirement.name)
            if dependency_name not in installed:
                raise NoticeError(
                    f"required runtime distribution {requirement.name!r} is not installed"
                )
            dependency_extras = extras_by_name.setdefault(dependency_name, set())
            before = frozenset(dependency_extras)
            dependency_extras.update(requirement.extras)
            if dependency_name not in processed_extras or before != dependency_extras:
                pending.append(dependency_name)

    return sorted(
        (distribution for name, distribution in installed.items() if name in extras_by_name),
        key=lambda distribution: canonicalize_name(distribution.metadata["Name"]),
    )


def _project_urls(distribution: metadata.Distribution) -> list[str]:
    values: list[str] = []
    for entry in distribution.metadata.get_all("Project-URL") or ():
        _, separator, url = entry.partition(",")
        value = url.strip() if separator else entry.strip()
        if value:
            values.append(value)
    homepage = (distribution.metadata.get("Home-page") or "").strip()
    if homepage:
        values.append(homepage)
    return list(dict.fromkeys(values))


def _license_files(distribution: metadata.Distribution) -> Iterable[tuple[str, str]]:
    seen: set[str] = set()
    for package_path in sorted(distribution.files or (), key=str):
        if not LICENSE_FILE_RE.match(Path(str(package_path)).name):
            continue
        resolved = Path(distribution.locate_file(package_path))
        if not resolved.is_file():
            continue
        logical_name = str(package_path).replace(os.sep, "/")
        if logical_name in seen:
            continue
        try:
            contents = resolved.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise NoticeError(f"could not read license file for {distribution}: {exc}") from exc
        if contents:
            seen.add(logical_name)
            yield logical_name, contents


def _indented(text: str) -> str:
    return "\n".join(f"    {line}" if line else "" for line in text.splitlines())


def render_notices(root_name: str) -> str:
    distributions = runtime_closure(root_name)
    root_canonical = canonicalize_name(root_name)
    lines = [
        "# Third-party notices",
        "",
        "This inventory was generated from the installed, locked runtime dependency closure.",
        "It is supplied for internal prototype distribution and does not replace legal review.",
        "Build-only and test-only tools are intentionally excluded unless they are also runtime",
        "dependencies. Package license texts are reproduced below when installed metadata provides",
        "them.",
        "",
    ]

    for distribution in distributions:
        name = distribution.metadata["Name"]
        if canonicalize_name(name) == root_canonical:
            continue
        version = distribution.version
        expression = (distribution.metadata.get("License-Expression") or "").strip()
        legacy_license = (distribution.metadata.get("License") or "").strip()
        urls = _project_urls(distribution)
        files = list(_license_files(distribution))

        lines.extend([f"## {name} {version}", ""])
        if expression:
            lines.append(f"License expression: `{expression}`")
        elif legacy_license and "\n" not in legacy_license and len(legacy_license) < 200:
            lines.append(f"License metadata: `{legacy_license}`")
        else:
            lines.append("License expression: not declared in installed core metadata")
        if urls:
            lines.append(f"Project: {urls[0]}")
        lines.append("")

        if legacy_license and ("\n" in legacy_license or len(legacy_license) >= 200):
            lines.extend(["Installed license metadata:", "", _indented(legacy_license), ""])
        if files:
            for logical_name, contents in files:
                lines.extend(
                    [
                        f"Installed license file: `{logical_name}`",
                        "",
                        _indented(contents),
                        "",
                    ]
                )
        elif not legacy_license:
            lines.extend(
                [
                    "No license text was present in the installed wheel metadata. Resolve this",
                    "entry during release/legal review before external distribution.",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-distribution", default="plug-analyzer")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        notices = render_notices(args.root_distribution)
        _atomic_write(args.output.resolve(), notices)
    except NoticeError as exc:
        print(f"notice generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote third-party notices: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
