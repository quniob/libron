"""Unpack the losslessly compressed FontForge masters before building or editing."""
from pathlib import Path
import lzma


def unpack_sources(root):
    for archive in sorted((Path(root) / "src").glob("*.sfd.xz")):
        destination = archive.with_suffix("")
        if not destination.exists():
            destination.write_bytes(lzma.decompress(archive.read_bytes()))
            print(f"Unpacked {destination.name}")


if __name__ == "__main__":
    unpack_sources(Path(__file__).resolve().parent.parent)
