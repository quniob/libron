"""Package all four styles in TTF, CFF OTF and WOFF2, with OFL notices."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STYLES = ("Regular", "Italic", "Bold", "BoldItalic")
version = (ROOT / "VERSION").read_text().strip()
files = []
for folder, extension in (("ttf", "ttf"), ("otf", "otf"), ("web", "woff2")):
    for style in STYLES:
        source = ROOT / "out" / folder / f"LibronCyrillic-{style}.{extension}"
        if not source.is_file():
            raise FileNotFoundError(source)
        files.append((source, f"fonts/{folder}/{source.name}"))
for relative in (
    "LICENSE", "COPYRIGHT", "README.md", "README-RU.md", "preview.html",
    "fonts/web/libron-cyrillic.css", "cyrillic/OFL-Literata.txt",
    "cyrillic/PROVENANCE.json", "specimens/alphabet.png", "specimens/reading.png",
):
    files.append((ROOT / relative, relative))
files.append((ROOT / "out/validation.json", "fonts/validation.json"))
checksums = [
    {"file": destination, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
     "bytes": source.stat().st_size}
    for source, destination in files
]
archive = ROOT / "out" / f"Libron-Cyrillic-{version}.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for source, destination in files:
        bundle.write(source, f"Libron-Cyrillic/{destination}")
    bundle.writestr("Libron-Cyrillic/SHA256.json", json.dumps(checksums, indent=2) + "\n")
with zipfile.ZipFile(archive) as bundle:
    if bundle.testzip() is not None:
        raise RuntimeError("Font package failed its CRC check")
print(archive.relative_to(ROOT))
