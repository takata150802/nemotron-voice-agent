"""Preinstall verified NLTK sentence data without runtime downloads."""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

URL = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip"
SHA256 = "e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106"


def install():
    """Verify the official data archive before extracting inside the workspace."""
    target = Path(__file__).resolve().parents[1] / ".models/nltk/tokenizers"
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("NLTK tokenizer checksum changed; review the official data before updating the pin")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            (target / member.filename).resolve().relative_to(target.resolve())
        archive.extractall(target)
    print(f"Offline sentence tokenizer installed: {target}")


if __name__ == "__main__":
    install()
