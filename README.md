# Extract-ADF-Python
Extract ADF tool ported to Python

Based on https://github.com/mist64/extract-adf but LLM ported to Python by ChatGPT Codex.

I wanted something a little more easily adoptable, and most modern machines have Python, so this doesn't require building.

# extract-adf.py

`extract-adf.py` is a Python port of [`mist64/extract-adf`](https://github.com/mist64/extract-adf), a utility for extracting files from Amiga OFS ADF disk images, including damaged or partially recoverable filesystems.

The goal of this port is to keep the original command-line shape and core extraction behavior while making the tool easy to run anywhere Python is available. It recreates the AmigaDOS directory hierarchy, writes recovered file data from OFS data blocks, and restores Amiga file timestamps on the host filesystem where possible.

## Usage

```text
python extract-adf.py [-D] [-a] [-z] [-d] [-s <startsector>] [-e <endsector>] [-o <outputfilename>] <adf/adz/dmsfilename>
```

Options match the original tool:

```text
-a  Force ADF extraction
-z  Force ADZ/gzip extraction
-d  Force DMS input handling
-D  Enable verbose debugging output
-s  Set the starting sector, default 0
-e  Set the ending sector, default 1760
-o  Redirect status/debug output to a file
```

Examples:

```sh
python extract-adf.py disk.adf
python extract-adf.py -z disk.adz
python extract-adf.py -s 513 -e 1760 kickstart-disk.adf
python extract-adf.py -D -o extract.log damaged.adf
```

Extraction writes files and directories into the current working directory.

## Supported Input

Implemented:

- Raw ADF images.
- ADZ / gzip-compressed ADF images.
- ZIP files containing an ADF image.
- OFS-family AmigaDOS filesystems, including damaged images where enough file-header and data blocks remain readable.
- Host-safe filename mapping for path characters that are legal on AmigaDOS but illegal on Windows.

Recognized but not implemented:

- DMS archives. The `-d` flag and `.dms` detection are present for CLI compatibility, but this Python port does not include the original C version's embedded DMS decompressor.

Explicitly unsupported:

- FFS-family filesystems. Like the original tool, this port targets OFS. FFS images are detected from the bootblock `DOS\N` flag and rejected with a clear error instead of producing empty or misleading output.
- Hard disk images, partition tables, and multi-volume devices.
- Full AmigaDOS link semantics. Link-heavy images may be rejected as unsupported if they are FFS-family, or only partially represented if link metadata does not map cleanly to host files.

## Validation

The port was validated against several classes of images:

- The bundled `Raytracer_1987_Graham_Source_Code.adf` image in this repository. Extracted file sizes were checked against the image's file headers, including large multi-sector files such as `movie.data` and `movie2.data`.
- Locally generated compressed variants of that image:
  - gzip / ADZ path.
  - ZIP-wrapped ADF path.
- Freely available test fixtures from the public [ADFlib](https://github.com/adflib/ADFlib) repository:
  - `arccsh.adf`: extracted successfully, 32 files, 610,677 bytes.
  - `blank.adf`: extracted successfully, 1 file, 1,172 bytes.
  - `cache_crash.adf`: extracted successfully, 2 files, 173,848 bytes.
  - `ffdisk0049.adf.gz`: extracted successfully, 81 files, 767,363 bytes.
  - `g1a30c.adf`: extracted successfully, 22 files, 782,780 bytes.
  - `testofs.adf`: extracted successfully, 2 files, 173,848 bytes.
  - `links.adf`, `test_link_chains.adf`, `testffs.adf`, `testhd.adf`, and `win32-names.adf`: rejected cleanly as unsupported FFS-family images.
- Byte-for-byte comparison against ADFlib's reference extracted files:
  - `arccsh.adf` -> `CSH`.
  - `testofs.adf` -> `MOON.GIF`.

The script also passes Python bytecode compilation:

```sh
python -m py_compile extract-adf.py
```

## Relationship To The Original

The original C project is [`mist64/extract-adf`](https://github.com/mist64/extract-adf), credited there to Michael Steil, Sigurbjorn B. Larusson, and David Tritscher for the DMS extraction code. That project describes itself as a tool for extracting files from broken Amiga OFS ADF/ADZ/DMS disk images and restoring directory hierarchy and timestamps.

This repository is a Python port, not a drop-in feature-complete replacement. The main intentional gap is DMS decompression; the Python version focuses on OFS filesystem extraction from already-available ADF data, including gzip/ADZ and ZIP-contained ADF images.

## AI/LLM Declaration

This tool is 100% AI/LLM ported from the original code by ChatGPT Codex 5.5 (Medium).

AI/LLM tools were used for this because the use case was single and simple, and it was deemed to be valuable enough to make and publish a Python port, but not really critical enough to dedicate the human engineering and testing resources to it. Use it at your own risk and discretion.

No novel copyright is claimed on the resulting data product as LLM/AI code is not deemed copyrightable.

The original code did not declare any specific license and the copyright is:
 * (C)2008 Michael Steil, http://www.pagetable.com/
 * Do whatever you want with it, but please give credit.
 * (C)2011-2019 Sigurbjorn B. Larusson, http://www.dot1q.org/

Therefore this code is a derivative of the original and would inherit those same conditions.



