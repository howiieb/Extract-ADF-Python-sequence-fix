#!/usr/bin/env python3
"""
Extract files from Amiga OFS ADF/ADZ disk images.

This is a Python rewrite of extract-adf.c.  It keeps the same command-line
arguments and output behavior for ADF, ADZ/gzip, and zip-wrapped ADF images.
DMS archives are recognized and can be selected with -d, but the old C file's
embedded DMS crunchers are intentionally not reimplemented here.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import struct
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path


SECTORS = 1760
FIRST_SECTOR = 0
MAX_SECTORS = 3520
SECTOR_SIZE = 512
DATABYTES = 488

T_HEADER = 2
T_DATA = 8
T_LIST = 16

MAX_AMIGADOS_FILENAME_LENGTH = 32
MAX_FILENAME_LENGTH = 256
ROOT_BLOCK = 880

FORMAT_AUTO = 0
FORMAT_ADF = 1
FORMAT_ADZ = 2
FORMAT_DMS = 3

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def usage(program_name: str) -> str:
    return (
        "Extract-ADF 4.0 Originally (C)2008 Michael Steil with many further "
        "additions by Sigurbjorn B. Larusson\n"
        "DMS extraction code (C) 1998 David Tritscher\n"
        f"\nUsage: {program_name} [-D] [-a] [-z] [-d] [-s <startsector>] "
        "[-e <endsector>] [-o <outputfilename>] <adf/adz/dmsfilename>\n"
        "\n\t-a will force ADF extraction (if the filename ends in adf ADF will be assumed"
        "\n\t-z will force ADZ extraction (if the filename ends in adz or adf.gz ADZ will be assumed"
        "\n\t-d will force DMS extraction (if the filename ends in dms DMS format will be assumed"
        "\n\t-D will activate debugging output which will print very detailed information about everything that is going on"
        "\n\t-s along with an integer argument from 0 to 1760 (DD) or 3520 (HD), will set the starting sector of the extraction process"
        "\n\t-e along with an integer argument from 0 to 1760 (DD) or 3520 (HD), will set the end sector of the extraction process"
        "\n\t-o along with an outputfilename will redirect output (including debugging output) to a file instead of to the screen"
        "\n\tFinally the last argument is the ADF/ADZ or DMS filename to process"
        "\n\nThe defaults for start and end sector are 0 and 1760 respectively, this tool was originally"
        "\ncreated to salvage lost data from kickstart disks (which contain the kickstart on sectors 0..512)"
        "\nin order to skip the sectors on kickstart disks which might contain non OFS data, set the start sector to 513\n"
        "\nTo use this tool on a HD floppy, the end sector needs to be 3520"
        "\nIf you get a Bus error it means that you specificed a non-existing end sector"
        "\nThis program does not support FFS floppies(!), it only supports OFS style Amiga Floppies"
        "\nHappy hunting!\n"
    )


class ExtractAdfArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise SystemExit(2)

    def format_usage(self) -> str:
        return usage(Path(sys.argv[0]).name)

    def print_usage(self, file=None) -> None:
        if file is None:
            file = sys.stderr
        file.write(self.format_usage())


@dataclass
class Sector:
    index: int
    raw: bytes
    type: int
    header_key: int
    seq_num: int
    data_size: int
    next_data: int
    chksum: int

    @classmethod
    def parse(cls, index: int, raw: bytes) -> "Sector":
        if len(raw) != SECTOR_SIZE:
            raw = raw.ljust(SECTOR_SIZE, b"\0")
        values = struct.unpack_from(">6I", raw, 0)
        return cls(index, raw, *values)

    @property
    def data(self) -> bytes:
        return self.raw[24:512]

    @property
    def byte_size(self) -> int:
        return u32(self.raw, 324)

    @property
    def days(self) -> int:
        return u32(self.raw, 420)

    @property
    def mins(self) -> int:
        return u32(self.raw, 424)

    @property
    def ticks(self) -> int:
        return u32(self.raw, 428)

    @property
    def name_len(self) -> int:
        return self.raw[432]

    @property
    def filename(self) -> str:
        length = self.name_len
        name_bytes = self.raw[433:463]
        if 0 < length <= len(name_bytes):
            name_bytes = name_bytes[:length]
        else:
            name_bytes = name_bytes.split(b"\0", 1)[0]
        return decode_amiga_name(name_bytes)

    @property
    def parent(self) -> int:
        return u32(self.raw, 500)

    @property
    def sec_type(self) -> int:
        return i32(self.raw, 508)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def i32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">i", data, offset)[0]


def decode_amiga_name(data: bytes) -> str:
    return data.rstrip(b"\0").decode("latin-1", errors="replace")


def valid_amiga_name(name: str) -> bool:
    if not name or len(name) > MAX_AMIGADOS_FILENAME_LENGTH:
        return False
    for char in name:
        code = ord(char)
        if char in {"/", "\\", ":"}:
            return False
        if (0 < code < 32) or (127 < code < 161):
            return False
    return True


def safe_name(name: str, fallback: str) -> str:
    if not valid_amiga_name(name):
        name = fallback
    safe = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name)
    safe = safe.rstrip(" .")
    if not safe:
        safe = fallback
    stem = safe.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        safe = f"{safe}_"
    if safe != name:
        digest = hashlib.sha1(name.encode("utf-8", errors="replace")).hexdigest()[:6]
        safe = f"{safe}-{digest}"
    return safe[:MAX_FILENAME_LENGTH]


def amigados_timestamp(days: int, minutes: int, ticks: int) -> float:
    if ticks == 0:
        ticks = 1
    return 252460800 + (days * 86400) + (minutes * 60) + (ticks // 50)


def set_amiga_mtime(path: Path, sector: Sector) -> None:
    try:
        stamp = amigados_timestamp(sector.days, sector.mins, sector.ticks)
        os.utime(path, (stamp, stamp))
    except OSError:
        pass


def debug_sector(out, sector: Sector) -> None:
    print(f"{sector.index:x}: type       {sector.type:x}", file=out)
    print(f"{sector.index:x}: header_key {sector.header_key:x}", file=out)
    print(f"{sector.index:x}: seq_num    {sector.seq_num:x}", file=out)
    print(f"{sector.index:x}: data_size  {sector.data_size:x}", file=out)
    print(f"{sector.index:x}: next_data  {sector.next_data:x}", file=out)
    print(f"{sector.index:x}: chksum     {sector.chksum:x}", file=out)


def detect_format(filename: str, out) -> int:
    lower = filename.lower()
    if lower.endswith(".adf"):
        print("Autodetected fileformat from extension is ADF", file=out)
        return FORMAT_ADF
    if lower.endswith(".adz"):
        print("Autodetected fileformat from extension is ADZ (.adz)", file=out)
        return FORMAT_ADZ
    if lower.endswith(".adf.gz"):
        print("Autodetected fileformat from extension is ADZ (.adf.gz)", file=out)
        return FORMAT_ADZ
    if lower.endswith(".zip"):
        print("Autodetected fileformat from extension is ZIP (.zip)", file=out)
        return FORMAT_ADZ
    if lower.endswith(".dms"):
        print("Autodetected fileformat from extension is DMS (.dms)", file=out)
        return FORMAT_DMS
    print("Can not figure out file format from file extension, assuming ADF", file=out)
    return FORMAT_ADF


def read_image(filename: Path, fmt: int) -> bytes:
    if fmt == FORMAT_ADF:
        return filename.read_bytes()
    if fmt == FORMAT_ADZ:
        with filename.open("rb") as f:
            magic = f.read(4)
        if magic == b"PK\x03\x04":
            print("Input file appears to be in zip format", file=sys.stderr)
            with zipfile.ZipFile(filename) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if not names:
                    raise RuntimeError("ZIP archive contains no files")
                return zf.read(names[0])
        with gzip.open(filename, "rb") as f:
            return f.read()
    if fmt == FORMAT_DMS:
        raise RuntimeError(
            "DMS input is recognized but not supported by this Python rewrite; "
            "convert the DMS to ADF first or use extract-adf.c for DMS archives."
        )
    raise RuntimeError("No format selected, don't know what to do, exiting")


def check_supported_filesystem(image: bytes) -> None:
    if len(image) < 4 or image[:3] != b"DOS":
        return
    dostype = image[3]
    if dostype & 1:
        raise RuntimeError(
            f"Unsupported Amiga filesystem DOS\\{dostype}: this extractor supports OFS-family images only, not FFS."
        )


def sector_path(
    sector: Sector,
    sectors: list[Sector],
    endsector: int,
    include_self: bool,
) -> list[Sector]:
    chain: list[Sector] = []
    seen: set[int] = set()
    current = sector.index if include_self else sector.parent
    while 0 <= current < min(endsector, len(sectors)) and current not in seen:
        seen.add(current)
        item = sectors[current]
        if item.type != T_HEADER:
            break
        if current != ROOT_BLOCK:
            chain.append(item)
        if current == ROOT_BLOCK or item.parent == 0:
            break
        current = item.parent
    chain.reverse()
    return chain


def ensure_directory(path: Path, stamp_sector: Sector | None = None) -> None:
    if path.exists() and path.is_file() and path.stat().st_size == 0:
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)
    if stamp_sector is not None:
        set_amiga_mtime(path, stamp_sector)


def create_headers(
    sectors: list[Sector],
    startsector: int,
    endsector: int,
    debug: bool,
    out,
) -> dict[int, Path]:
    header_paths: dict[int, Path] = {}
    for sector in sectors[startsector:endsector]:
        if sector.type != T_HEADER:
            continue
        if debug:
            debug_sector(out, sector)
            print(f'{sector.index:x}:  filename  "{sector.filename}"', file=out)
            print(f"{sector.index:x}:  byte_size {sector.byte_size}", file=out)

        components = []
        for entry in sector_path(sector, sectors, endsector, include_self=True):
            components.append(safe_name(entry.filename, f"Unnamed-{entry.index}"))
        if not components:
            continue

        output_path = Path(*components)
        header_paths[sector.index] = output_path

        parent = output_path.parent
        if str(parent) != ".":
            ensure_directory(parent)

        if sector.byte_size == 0:
            ensure_directory(output_path, sector)
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.touch(exist_ok=True)
            set_amiga_mtime(output_path, sector)
    return header_paths


def orphan_name(header_key: int, sectors: list[Sector], previous_path: str) -> tuple[str, Sector | None]:
    if 0 <= header_key < len(sectors):
        header = sectors[header_key]
        name = header.filename
        parent = header.parent
        parent_name = ""
        if 0 <= parent < len(sectors):
            parent_name = sectors[parent].filename
        if valid_amiga_name(name) and valid_amiga_name(parent_name):
            return f"Orphan-{header_key}-{parent_name}-{name}", header
        if valid_amiga_name(name):
            return f"Orphan-{header_key}-{name}", header
        if valid_amiga_name(parent_name):
            return f"Orphan-{header_key}-{parent_name}", sectors[parent]
    if previous_path:
        return f"Orphan-{previous_path}-{previous_path}", None
    return f"Orphan-{header_key}-{header_key}", None


def write_data_sectors(
    sectors: list[Sector],
    header_paths: dict[int, Path],
    startsector: int,
    endsector: int,
    debug: bool,
    out,
) -> None:
    orphan_paths: dict[int, Path] = {}
    previous_path = ""

    for sector in sectors[startsector:endsector]:
        if sector.type != T_DATA:
            continue
        if debug:
            debug_sector(out, sector)

        if not 1 <= sector.seq_num <= MAX_SECTORS:
            print(
                f"Skipping data block at sector {sector.index}: seq_num "
                f"{sector.seq_num} is out of range (expected 1..{MAX_SECTORS})",
                file=sys.stderr,
            )
            continue

        header_key = sector.header_key
        header = sectors[header_key] if 0 <= header_key < len(sectors) else None
        output_path = header_paths.get(header_key)
        if output_path is None:
            if header_key not in orphan_paths:
                name, stamp_sector = orphan_name(header_key, sectors, previous_path)
                parts = name.split("-", 3)
                if len(parts) >= 3 and parts[2]:
                    orphan_dir = Path("Orphaned") / safe_name(parts[2], f"Header-{header_key}")
                    ensure_directory(orphan_dir)
                    output_path = orphan_dir / safe_name(name, f"Orphan-{header_key}")
                else:
                    ensure_directory(Path("Orphaned"))
                    output_path = Path("Orphaned") / safe_name(name, f"Orphan-{header_key}")
                orphan_paths[header_key] = output_path
                if stamp_sector is not None:
                    set_amiga_mtime(output_path.parent, stamp_sector)
            output_path = orphan_paths[header_key]
        else:
            parent_text = str(output_path.parent)
            if parent_text != ".":
                previous_path = output_path.parent.name

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("r+b") as f:
                f.seek((sector.seq_num - 1) * DATABYTES)
                f.write(sector.data[: sector.data_size])
        except FileNotFoundError:
            with output_path.open("wb") as f:
                f.seek((sector.seq_num - 1) * DATABYTES)
                f.write(sector.data[: sector.data_size])
        except IsADirectoryError:
            output_path = output_path.with_name(f"{output_path.name}-{sector.header_key}")
            with output_path.open("wb") as f:
                f.seek((sector.seq_num - 1) * DATABYTES)
                f.write(sector.data[: sector.data_size])

        if header is not None:
            set_amiga_mtime(output_path, header)

        if debug:
            print(
                f"Seek seq_num {sector.seq_num:02x} : DATABYTES: {DATABYTES} SEEKSET: 0 ",
                file=out,
            )
            print(f"seek to {(sector.seq_num - 1) * DATABYTES}", file=out)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = ExtractAdfArgumentParser(add_help=False)
    parser.add_argument("-a", action="store_const", const=FORMAT_ADF, dest="fmt")
    parser.add_argument("-z", action="store_const", const=FORMAT_ADZ, dest="fmt")
    parser.add_argument("-d", action="store_const", const=FORMAT_DMS, dest="fmt")
    parser.add_argument("-D", action="store_true", dest="debug")
    parser.add_argument("-o", dest="outfile")
    parser.add_argument("-s", type=int, default=FIRST_SECTOR, dest="startsector")
    parser.add_argument("-e", type=int, default=SECTORS, dest="endsector")
    parser.add_argument("filename", nargs="?")
    args = parser.parse_args(argv)
    if args.fmt is None:
        args.fmt = FORMAT_AUTO
    if (
        args.startsector < 0
        or args.startsector > MAX_SECTORS
        or args.endsector < 0
        or args.endsector > MAX_SECTORS
        or args.startsector > args.endsector
    ):
        parser.print_usage(sys.stderr)
        raise SystemExit(2)
    if not args.filename:
        parser.print_usage(sys.stderr)
        raise SystemExit(2)
    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)

    out = sys.stdout
    outfile_handle = None
    if args.outfile:
        try:
            outfile_handle = open(args.outfile, "w", encoding="utf-8")
        except OSError as exc:
            print(
                f"Can't open output file {args.outfile} for writing, error returned was: {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"Writing output to {args.outfile}")
        out = outfile_handle

    try:
        fmt = args.fmt
        if args.debug:
            names = {
                FORMAT_AUTO: "File format is not set!",
                FORMAT_ADF: "File format is ADF",
                FORMAT_ADZ: "File format is ADZ",
                FORMAT_DMS: "File format is DMS",
            }
            print(names[fmt], file=out)

        image_path = Path(args.filename)
        if not image_path.exists():
            print(f"Can't open file {args.filename} for reading, error returned was: file not found", file=sys.stderr)
            return 1

        if fmt == FORMAT_AUTO:
            if args.debug:
                print(f"Input filename is {args.filename}", file=out)
            fmt = detect_format(args.filename, out)

        print(f"Startsector is {args.startsector}", file=out)
        print(f"Endsector is {args.endsector}", file=out)

        try:
            image = read_image(image_path, fmt)
            check_supported_filesystem(image)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1

        sectors = [
            Sector.parse(i, image[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE])
            for i in range(args.endsector)
            if (i + 1) * SECTOR_SIZE <= len(image)
        ]
        if args.debug:
            print(f"Total sectors: {len(sectors)}\n", file=out)

        requested = args.endsector - args.startsector
        if len(sectors) < requested:
            print(
                f"Only managed to read {len(sectors)} sectors out of {requested} requested, cowardly refusing to continue",
                file=sys.stderr,
            )
            return 1
        if len(sectors) < args.endsector:
            print(
                f"Only managed to read {len(sectors)} sectors out of {args.endsector} requested, cowardly refusing to continue",
                file=sys.stderr,
            )
            return 1

        header_paths = create_headers(sectors, args.startsector, args.endsector, args.debug, out)
        write_data_sectors(sectors, header_paths, args.startsector, args.endsector, args.debug, out)
        return 0
    finally:
        if outfile_handle is not None:
            outfile_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
