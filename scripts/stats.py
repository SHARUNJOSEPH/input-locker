"""Privacy-First Download & Usage Metrics Viewer for Input Locker.

Fetches aggregated public metrics from GitHub's Releases and Repository API.
Collects ZERO user data, IP addresses, or device telemetry.
"""
from __future__ import annotations

import json
import sys
import urllib.request

REPO = "SHARUNJOSEPH/input-locker"


def fetch_metrics(repo: str = REPO) -> None:
    headers = {
        "User-Agent": "InputLocker-Stats-Viewer",
        "Accept": "application/vnd.github.v3+json",
    }

    print("=" * 60)
    print(f"  Input Locker Metrics & Analytics Dashboard ({repo})")
    print("=" * 60)

    # 1. Fetch Repository Info
    repo_url = f"https://api.github.com/repos/{repo}"
    try:
        req = urllib.request.Request(repo_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            r_data = json.loads(resp.read().decode())
            print(f"⭐ Stars:          {r_data.get('stargazers_count', 0)}")
            print(f"🍴 Forks:          {r_data.get('forks_count', 0)}")
            print(f"👀 Watchers:       {r_data.get('subscribers_count', 0)}")
            print(f"📂 Open Issues:    {r_data.get('open_issues_count', 0)}")
    except Exception as exc:
        print(f"Could not load repository stats: {exc}")

    print("-" * 60)

    # 2. Fetch Release Downloads
    releases_url = f"https://api.github.com/repos/{repo}/releases"
    try:
        req = urllib.request.Request(releases_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            releases = json.loads(resp.read().decode())

        if not releases:
            print("No published releases found.")
            return

        total_downloads = 0
        print(f"📦 Releases Published: {len(releases)}\n")

        for rel in releases:
            tag = rel.get("tag_name", "Unknown")
            name = rel.get("name", tag)
            published = rel.get("published_at", "")[:10]
            print(f"  Release: {tag} ({name}) - {published}")

            assets = rel.get("assets", [])
            rel_downloads = 0
            for asset in assets:
                a_name = asset.get("name", "asset")
                count = asset.get("download_count", 0)
                size_mb = asset.get("size", 0) / (1024 * 1024)
                print(f"    • {a_name:<35} {count:>5} downloads ({size_mb:.1f} MB)")
                rel_downloads += count
                total_downloads += count

            print(f"    Subtotal for {tag}: {rel_downloads} downloads\n")

        print("=" * 60)
        print(f"  TOTAL DOWNLOADS ACROSS ALL RELEASES: {total_downloads}")
        print("=" * 60)
        print("\nPrivacy Guarantee: No user data or telemetry is collected by Input Locker.")
        print("These numbers are aggregated download counts provided by GitHub Releases.")

    except Exception as exc:
        print(f"Could not load release stats: {exc}")


if __name__ == "__main__":
    fetch_metrics()
