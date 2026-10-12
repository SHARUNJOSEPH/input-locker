"""Package and validate Microsoft Store MSIX package for Input Locker.

Generates a fully compliant, self-contained MSIX package conforming to Microsoft Appx
packaging specifications, including AppxManifest.xml, [Content_Types].xml, and
AppxBlockMap.xml with SHA-256 block hashing.
"""
from __future__ import annotations

import base64
import glob
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

BLOCK_SIZE = 65536  # 64 KB Appx block size


def find_makeappx() -> str | None:
    """Find official Microsoft MakeAppx.exe from PATH, electron-builder cache, or Windows Kits."""
    which = shutil.which("makeappx.exe") or shutil.which("makeappx")
    if which:
        return which
    pattern = os.path.expandvars(r"%LOCALAPPDATA%\electron-builder\cache\winCodeSign-*\*\windows-10\x64\makeappx.exe")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    kit_matches = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\makeappx.exe")
    if kit_matches:
        return kit_matches[-1]
    return None


def compute_blockmap_for_file(file_path: Path, rel_name: str) -> tuple[int, int, list[str]]:
    """Compute file size, local file header size, and list of base64 SHA-256 hashes per 64KB block."""
    with open(file_path, "rb") as f:
        data = f.read()
    file_size = len(data)
    # Win32 zip local file header size = 30 + length of relative filename string
    lfh_size = 30 + len(rel_name.encode("utf-8"))

    hashes = []
    for i in range(0, file_size, BLOCK_SIZE):
        chunk = data[i : i + BLOCK_SIZE]
        h = base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii")
        hashes.append(h)

    return file_size, lfh_size, hashes


def build_msix_package(
    project_root: Path,
    version: str = "0.2.11",
    output_dir: Path | None = None,
) -> Path:
    """Stage, block-hash, assemble, and validate the MSIX package."""
    if output_dir is None:
        output_dir = project_root / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = output_dir / "msix_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    exe_path = output_dir / "InputLocker.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Missing executable at {exe_path}. Build InputLocker.exe first.")

    manifest_source = project_root / "packaging" / "msix" / "AppxManifest.xml"
    if not manifest_source.is_file():
        raise FileNotFoundError(f"Missing AppxManifest.xml at {manifest_source}.")

    # Copy binary and manifest
    shutil.copy2(exe_path, staging_dir / "InputLocker.exe")
    shutil.copy2(manifest_source, staging_dir / "AppxManifest.xml")

    # Copy required assets
    assets_dest = staging_dir / "assets"
    assets_dest.mkdir(parents=True, exist_ok=True)
    branding_dest = assets_dest / "branding"
    branding_dest.mkdir(parents=True, exist_ok=True)
    store_dest = assets_dest / "store"
    store_dest.mkdir(parents=True, exist_ok=True)

    assets_src = project_root / "assets"
    shutil.copy2(assets_src / "branding" / "github_hero_banner.jpg", branding_dest / "github_hero_banner.jpg")
    for logo in ["Square150x150Logo.png", "Square44x44Logo.png", "StoreLogo.png", "Wide310x150Logo.png"]:
        shutil.copy2(assets_src / "store" / logo, store_dest / logo)

    # List of files to include in BlockMap (ordered as standard)
    file_order = [
        "assets\\branding\\github_hero_banner.jpg",
        "assets\\store\\Square150x150Logo.png",
        "assets\\store\\Square44x44Logo.png",
        "assets\\store\\StoreLogo.png",
        "assets\\store\\Wide310x150Logo.png",
        "InputLocker.exe",
        "AppxManifest.xml",
    ]

    # Generate AppxBlockMap.xml
    blockmap_root = ET.Element(
        "BlockMap",
        {
            "xmlns": "http://schemas.microsoft.com/appx/2010/blockmap",
            "HashMethod": "http://www.w3.org/2001/04/xmlenc#sha256",
        },
    )

    for rel_name in file_order:
        local_path = staging_dir / Path(rel_name)
        file_size, lfh_size, hashes = compute_blockmap_for_file(local_path, rel_name)
        file_el = ET.SubElement(
            blockmap_root,
            "File",
            {
                "Name": rel_name,
                "Size": str(file_size),
                "LfhSize": str(lfh_size),
            },
        )
        for h in hashes:
            ET.SubElement(file_el, "Block", {"Hash": h})

    blockmap_xml = ET.tostring(blockmap_root, encoding="utf-8", xml_declaration=True)
    blockmap_path = staging_dir / "AppxBlockMap.xml"
    with open(blockmap_path, "wb") as f:
        f.write(blockmap_xml)

    # Generate [Content_Types].xml
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="jpg" ContentType="image/jpeg" />'
        '<Default Extension="png" ContentType="image/png" />'
        '<Default Extension="exe" ContentType="application/x-msdownload" />'
        '<Default Extension="xml" ContentType="application/vnd.ms-appx.manifest+xml" />'
        '<Override PartName="/AppxBlockMap.xml" ContentType="application/vnd.ms-appx.blockmap+xml" />'
        "</Types>"
    )
    content_types_path = staging_dir / "[Content_Types].xml"
    with open(content_types_path, "wb") as f:
        f.write(content_types.encode("utf-8"))

    # Assemble MSIX archive
    msix_path = output_dir / f"InputLocker-v{version}.msix"
    if msix_path.exists():
        msix_path.unlink()

    makeappx = find_makeappx()
    if makeappx:
        print(f"Packaging with official Microsoft MakeAppx: {makeappx}")
        # Clean temporary xml files before MakeAppx runs as MakeAppx creates them
        if blockmap_path.exists():
            blockmap_path.unlink()
        if content_types_path.exists():
            content_types_path.unlink()
        cmd = [makeappx, "pack", "/d", str(staging_dir), "/p", str(msix_path), "/o"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"MakeAppx failed ({res.returncode}):\n{res.stderr or res.stdout}")
    else:
        print("MakeAppx not found; falling back to Python zip packaging...")
        # Images are stored (compression=0), others are deflated (compression=8)
        with zipfile.ZipFile(msix_path, "w") as zf:
            for rel_name in file_order:
                local_path = staging_dir / Path(rel_name)
                compress = zipfile.ZIP_STORED if rel_name.endswith((".png", ".jpg")) else zipfile.ZIP_DEFLATED
                zf.write(local_path, arcname=rel_name.replace("\\", "/"), compress_type=compress)

            # Write AppxBlockMap.xml and [Content_Types].xml
            zf.write(blockmap_path, arcname="AppxBlockMap.xml", compress_type=zipfile.ZIP_DEFLATED)
            zf.write(content_types_path, arcname="[Content_Types].xml", compress_type=zipfile.ZIP_DEFLATED)

    print(f"Successfully generated MSIX: {msix_path} ({msix_path.stat().st_size / (1024 * 1024):.2f} MB)")
    validate_msix_package(msix_path, expected_version=version)
    return msix_path


def validate_msix_package(msix_path: Path, expected_version: str = "0.2.11") -> None:
    """Validate integrity, manifest identity, block map, and internal structure of the MSIX package."""
    assert msix_path.is_file(), f"MSIX file not found: {msix_path}"
    with zipfile.ZipFile(msix_path, "r") as zf:
        namelist = zf.namelist()
        required_entries = [
            "AppxManifest.xml",
            "AppxBlockMap.xml",
            "[Content_Types].xml",
            "InputLocker.exe",
            "assets/store/StoreLogo.png",
        ]
        for req in required_entries:
            assert req in namelist, f"MSIX missing required entry: {req}"

        # Validate AppxManifest version
        manifest_data = zf.read("AppxManifest.xml").decode("utf-8")
        assert f'Version="{expected_version}.0"' in manifest_data, (
            f"AppxManifest.xml Version does not match {expected_version}.0"
        )

        # Validate BlockMap
        blockmap_data = zf.read("AppxBlockMap.xml")
        tree = ET.fromstring(blockmap_data)
        assert tree.tag.endswith("BlockMap"), "Invalid BlockMap root tag"

        # Verify hash of each file in BlockMap
        for file_node in tree.findall("{http://schemas.microsoft.com/appx/2010/blockmap}File"):
            name = file_node.attrib["Name"].replace("\\", "/")
            assert name in namelist, f"BlockMap references missing file: {name}"
            file_data = zf.read(name)
            blocks = file_node.findall("{http://schemas.microsoft.com/appx/2010/blockmap}Block")
            for idx, block in enumerate(blocks):
                chunk = file_data[idx * BLOCK_SIZE : (idx + 1) * BLOCK_SIZE]
                expected_hash = block.attrib["Hash"]
                actual_hash = base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii")
                assert expected_hash == actual_hash, f"Hash mismatch in {name} block {idx}"

    print(f"✓ MSIX Package {msix_path.name} passed all structural and cryptographic validations.")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    ver = "0.2.11"
    if len(sys.argv) > 1:
        ver = sys.argv[1].lstrip("v")
    build_msix_package(root, version=ver)
