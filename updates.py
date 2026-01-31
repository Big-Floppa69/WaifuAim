"""GitHub update checking and installer download helpers.

Uses the public GitHub Releases API to compare APP_VERSION against the latest
published release tag.

Design goals:
- No extra dependencies (urllib only)
- Non-blocking UI usage (callers run in background threads)
- Best-effort Windows installer download + launch
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    html_url: str
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None


def _version_tuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(v or ""))
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums)


def is_newer_version(latest: str, current: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def _http_json(url: str, *, timeout: float = 6.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WaifuAim-UpdateChecker",
            "Accept": "application/vnd.github+json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}


def _normalize_tag(tag: str) -> str:
    tag = str(tag or "").strip()
    if tag.lower().startswith("v") and len(tag) > 1:
        # Common release convention: v1.2.3
        return tag[1:]
    return tag


def get_latest_github_release(owner: str, repo: str) -> Optional[ReleaseInfo]:
    owner = str(owner or "").strip()
    repo = str(repo or "").strip()
    if not owner or not repo:
        return None

    api = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    data = _http_json(api)

    tag = _normalize_tag(str(data.get("tag_name") or "").strip())
    html = str(data.get("html_url") or "").strip()
    if not tag or not html:
        return None

    # Best-effort: pick an installer-like asset.
    asset_name = None
    asset_url = None

    assets = data.get("assets")
    if isinstance(assets, list):
        preferred = None
        for a in assets:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "").strip()
            url = str(a.get("browser_download_url") or "").strip()
            if not name or not url:
                continue

            low = name.lower()
            if low.endswith(".exe") and ("setup" in low or "installer" in low or "waifuaim" in low):
                preferred = (name, url)
                break

        if preferred is None:
            for a in assets:
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name") or "").strip()
                url = str(a.get("browser_download_url") or "").strip()
                if not name or not url:
                    continue
                if str(name).lower().endswith(".exe"):
                    preferred = (name, url)
                    break

        if preferred is not None:
            asset_name, asset_url = preferred

    return ReleaseInfo(version=tag, html_url=html, asset_name=asset_name, asset_url=asset_url)


def download_file(url: str, *, filename: Optional[str] = None, timeout: float = 20.0) -> str:
    url = str(url or "").strip()
    if not url:
        raise ValueError("Empty download URL")

    if not filename:
        # Try to keep a reasonable file extension.
        filename = os.path.basename(url.split("?")[0]) or "download.bin"

    target_dir = tempfile.gettempdir()
    target_path = os.path.join(target_dir, filename)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WaifuAim-UpdateChecker"},
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(target_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)

    return target_path


def launch_installer(path: str) -> bool:
    """Launch the installer executable (Windows)."""
    path = str(path or "").strip()
    if not path or not os.path.exists(path):
        return False

    try:
        # Use ShellExecute semantics via os.startfile on Windows.
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False
