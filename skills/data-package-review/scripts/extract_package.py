#!/usr/bin/env python3
"""Extract a UTF-8 or legacy GBK ZIP into a new, isolated review directory."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import zipfile


def extract_package(archive, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Destination already exists; use a new review directory.')
    with zipfile.ZipFile(archive) as package:
        entries, seen = [], set()
        for entry in package.infolist():
            name = entry.filename
            if not entry.flag_bits & 0x800:
                try:
                    name = name.encode('cp437').decode('gb18030')
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            relative = PurePosixPath(name.replace('\\', '/'))
            if relative.is_absolute() or '..' in relative.parts or ':' in name or not relative.parts:
                raise ValueError(f'Unsafe ZIP path: {name!r}')
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'ZIP symlink is not supported: {name!r}')
            key = str(relative).casefold()
            if key in seen:
                raise ValueError(f'Duplicate ZIP path: {name!r}')
            seen.add(key)
            entries.append((entry, relative))
        destination.mkdir(parents=True)
        for entry, relative in entries:
            target = destination.joinpath(*relative.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
    return len(entries)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(f'Extracted {extract_package(args.archive, args.destination)} entries to {args.destination}')
