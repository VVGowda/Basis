"""Stamp each asset URL with a hash of that asset's contents.

Run after changing anything in web/assets:

    venv\\Scripts\\python.exe scripts\\version_assets.py

Why this exists. The server sends `Cache-Control: no-cache`, which makes a
browser revalidate before reusing a file. That is correct going forward, but it
does nothing for a browser that cached the file *before* the header existed:
those copies can sit in the cache with a heuristic freshness of hours, and the
user sees old behaviour on a page that looks current. It is a genuinely
confusing class of bug, because the server is serving the right thing and the
browser is showing the wrong thing.

Hashing the contents into the URL removes the ambiguity. A changed file gets a
new URL that nothing can have cached; an unchanged file keeps its URL and stays
cached. Idempotent, so running it twice changes nothing.
"""

import hashlib
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
ASSETS = WEB / "assets"


def main() -> int:
    if not ASSETS.is_dir():
        print(f"No assets directory at {ASSETS}")
        return 1

    versions = {
        asset.name: hashlib.sha256(asset.read_bytes()).hexdigest()[:8]
        for asset in sorted(ASSETS.iterdir())
        if asset.suffix in {".css", ".js"}
    }
    if not versions:
        print("No CSS or JS assets found.")
        return 1

    changed = []
    for page in sorted(WEB.glob("*.html")):
        original = page.read_text(encoding="utf-8")
        updated = original
        for name, digest in versions.items():
            # Match the asset with or without an existing version stamp, so
            # re-running replaces rather than accumulating query strings.
            updated = re.sub(
                r"(assets/" + re.escape(name) + r")(\?v=[a-f0-9]+)?",
                r"\1?v=" + digest,
                updated,
            )
        if updated != original:
            page.write_text(updated, encoding="utf-8")
            changed.append(page.name)

    print(f"\n{len(versions)} assets hashed:")
    for name, digest in versions.items():
        print(f"  {name:<18} v={digest}")

    if changed:
        print(f"\nUpdated: {', '.join(changed)}\n")
    else:
        print("\nAll pages already current.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
