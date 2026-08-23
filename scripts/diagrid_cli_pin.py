#!/usr/bin/env python3
"""Fetch the pinned Diagrid CLI, checksum-verified, and print its path.

The gate in check_cli_surface.py asks a real binary what commands and flags
exist. That binary has to arrive the same way every time or the gate measures
the weather, so this module is the only thing that decides which one it is.

Three deliberate choices:

`downloads.diagrid.io/cli/install.sh` is never piped to a shell. It is a public
script that honours a RELEASE_VERSION override, so it *could* be used — but it
would be remote code running unpinned in CI on every pull request, and it drops
the binary into `$PWD` as a side effect. Instead this reads the same public GCS
objects that script reads, at the URL shape it builds.

The checksum is the check, not the version string. `diagrid version` is printed
by the very binary whose provenance is in question, so it proves nothing about
what was downloaded. A sha256 mismatch here is fatal and says so.

The download is cached by content. A second run in the same CI job, or a local
run an hour later, re-verifies the cached archive rather than re-fetching 34MB.
A cache entry that fails its checksum is deleted, not reused.

Run: python3 scripts/diagrid_cli_pin.py [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN_FILE = REPO / ".diagrid-cli-version"

# Read in 1MB blocks: the archive is ~34MB and hashing it a byte at a time is
# slower than the download.
_CHUNK = 1024 * 1024


class PinError(RuntimeError):
    """Anything that makes the pinned CLI unavailable. Always fatal."""


def platform_key() -> str:
    """The `<os>_<arch>` token in the artifact path, as install.sh derives it."""
    system = platform.system().lower()
    if system not in ("linux", "darwin"):
        raise PinError(
            f"unsupported OS {system!r}. The Diagrid CLI publishes linux and "
            f"darwin archives; Windows uses a .zip this module does not read."
        )
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if arch is None:
        raise PinError(f"unsupported architecture {machine!r}")
    return f"{system}_{arch}"


@dataclass(frozen=True)
class Pin:
    """Everything .diagrid-cli-version declares."""

    version: str
    bucket: str
    checksums: dict[str, str]
    # Command paths the CLI resolves only for some logins. See the long note in
    # the pin file; the gate reports these as unverifiable rather than absent.
    identity_gated: dict[str, str]


def read_pin(pin_file: Path = PIN_FILE) -> Pin:
    """Parse and validate the pin file."""
    if not pin_file.is_file():
        raise PinError(f"no pin file at {pin_file}")
    data = tomllib.loads(pin_file.read_text(encoding="utf-8"))
    version = data.get("version")
    bucket = data.get("bucket")
    checksums = data.get("sha256") or {}
    gated = data.get("identity_gated") or {}
    if not isinstance(version, str) or not version.startswith("v"):
        raise PinError(f"{pin_file.name}: `version` must be a string like \"v1.66.0\", got {version!r}")
    if not isinstance(bucket, str) or not bucket:
        raise PinError(f"{pin_file.name}: `bucket` must be a non-empty string")
    if not isinstance(checksums, dict) or not checksums:
        raise PinError(f"{pin_file.name}: `[sha256]` must list at least one platform")
    if not isinstance(gated, dict):
        raise PinError(f"{pin_file.name}: `[identity_gated]` must be a table of name = reason")
    for name, reason in gated.items():
        if not isinstance(reason, str) or not reason.strip():
            raise PinError(
                f"{pin_file.name}: `identity_gated.{name}` needs a reason. An entry "
                f"without one is indistinguishable from silencing a real defect."
            )
    return Pin(
        version=version,
        bucket=bucket,
        checksums={str(k): str(v) for k, v in checksums.items()},
        identity_gated={str(k): str(v) for k, v in gated.items()},
    )


def archive_url(bucket: str, version: str, key: str) -> str:
    """The artifact URL, in the shape install.sh builds.

    Note the doubled path segment — `diagrid/diagrid_<os>_<arch>/diagrid_<os>_<arch>.tar.gz`.
    It is easy to write this with one `diagrid_<os>_<arch>` and get a 404 that
    looks like a missing release rather than a wrong URL.
    """
    stem = f"diagrid_{key}"
    return f"https://storage.googleapis.com/{bucket}/{version}/diagrid/{stem}/{stem}.tar.gz"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def default_cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "diagrid-cli-pin"


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out, _CHUNK)
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise PinError(
            f"HTTP {exc.code} for {url}\n"
            f"A 404 here usually means the pinned version was never published "
            f"under that name, or the URL shape changed. Check the version in "
            f"{PIN_FILE.name} against install.sh."
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        raise PinError(f"cannot reach {url}: {exc}") from exc
    tmp.replace(dest)


def fetch(cache_dir: Path | None = None, pin_file: Path = PIN_FILE) -> Path:
    """Return the path to the verified, extracted pinned `diagrid` binary."""
    pin = read_pin(pin_file)
    key = platform_key()
    if key not in pin.checksums:
        raise PinError(
            f"{pin_file.name} has no sha256 for {key}. Add one — an unverified "
            f"download is not a pin. Platforms listed: {', '.join(sorted(pin.checksums))}"
        )
    expected = pin.checksums[key]

    cache = cache_dir or default_cache_dir()
    home = cache / pin.version / key
    home.mkdir(parents=True, exist_ok=True)
    archive = home / f"diagrid_{key}.tar.gz"
    binary = home / "diagrid"

    if archive.is_file() and sha256_of(archive) != expected:
        # A cache entry that does not match the pin is not a cache entry. Deleting
        # the binary too: it was extracted from the archive we just rejected.
        archive.unlink()
        binary.unlink(missing_ok=True)

    if not archive.is_file():
        _download(archive_url(pin.bucket, pin.version, key), archive)
        actual = sha256_of(archive)
        if actual != expected:
            archive.unlink()
            raise PinError(
                f"sha256 mismatch for {archive.name} at {pin.version}\n"
                f"  expected  {expected}\n"
                f"  got       {actual}\n"
                f"Either {pin_file.name} is stale for this version, or the "
                f"artifact changed under a published version. Do not update the "
                f"checksum to match without knowing which."
            )
        binary.unlink(missing_ok=True)

    if not binary.is_file():
        _extract_binary(archive, home)

    binary.chmod(0o755)
    return binary


def _extract_binary(archive: Path, dest: Path) -> None:
    """Extract only the `diagrid` member, refusing any path that escapes dest."""
    with tarfile.open(archive, "r:gz") as tar:
        member = next((m for m in tar.getmembers() if Path(m.name).name == "diagrid" and m.isfile()), None)
        if member is None:
            raise PinError(f"{archive.name} contains no `diagrid` executable")
        # A tar member is attacker-controlled input even from a checksummed
        # archive: the checksum proves it is the artifact we pinned, not that the
        # artifact is well-behaved. Flatten the name so `../` cannot escape.
        member.name = "diagrid"
        tar.extract(member, dest, filter="data")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", type=Path, default=None, help="where to keep the verified archive")
    args = parser.parse_args(argv[1:])
    try:
        binary = fetch(args.cache_dir)
    except PinError as exc:
        print(f"cannot fetch the pinned Diagrid CLI: {exc}", file=sys.stderr)
        return 1
    print(binary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
