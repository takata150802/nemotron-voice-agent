"""Compare a pinned upstream checkout against the workspace without git staging."""

import argparse
import difflib
import json
import subprocess
from pathlib import Path


def compare(checkout, patch=False):
    """Report only files changed from the imported OSS source snapshot."""
    root = Path(__file__).resolve().parents[1]
    pin = json.loads((root / ".upstream.json").read_text())["revision"]
    actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin:
        raise ValueError(f"Checkout must match recorded upstream revision {pin}")
    files = subprocess.check_output(["git", "-C", str(checkout), "ls-tree", "-r", "--name-only", "HEAD"], text=True)
    for name in files.splitlines():
        original, local = checkout / name, root / name
        if not original.is_file():
            continue
        if not local.is_file():
            print(f"deleted: {name}")
        elif original.read_bytes() != local.read_bytes():
            print(f"modified: {name}")
            if patch:
                try:
                    print(
                        "".join(
                            difflib.unified_diff(
                                original.read_text().splitlines(True),
                                local.read_text().splitlines(True),
                                fromfile="a/" + name,
                                tofile="b/" + name,
                            )
                        ),
                        end="",
                    )
                except UnicodeDecodeError:
                    print("Binary file changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--patch", action="store_true")
    args = parser.parse_args()
    compare(args.checkout, args.patch)
