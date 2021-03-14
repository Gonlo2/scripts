#!/usr/bin/env python3
import logging
import os
import re
import sys
import zlib
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser

CRC32_PATTERN = re.compile(r"\[([0-F]{8})\]")

logger = logging.getLogger(__name__)


def cprint(template, *args, **kwargs):
    _cprint(sys.stdout, template, *args, **kwargs)


def _cprint(fd, template, *args, **kwargs):
    if args or kwargs:
        template = cformat(template, *args, **kwargs)
    fd.write('{}\n'.format(template))


def cformat(template, *args, **kwargs):
    return template.format(
        *args,
        _reset='\033[0m',
        _bold='\033[1m',
        _lred='\033[91m',
        _lgreen='\033[92m',
        _lblue='\033[94m',
        **kwargs
    )


def fcrc32(value):
    return '{:0>8X}'.format(value)


def calculate_crc32(path):
    logger.debug('Calculating the CRC32 of "%s"', path)
    csum = 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            csum = zlib.crc32(chunk, csum)
    return csum & 0xffffffff


def extract_crc32(file_name):
    match = CRC32_PATTERN.search(file_name)
    return None if match is None else int(match.group(1), 16)


def list_files(paths):
    for path in paths:
        if os.path.isfile(path):
            yield os.path.split(path)
        else:
            for root, _, files in os.walk(path):
                for fname in files:
                    yield (root, fname)


def create_arg_parser():
    p = ArgumentParser(description='A recursive CRC32',
                       formatter_class=ArgumentDefaultsHelpFormatter)
    p.add_argument('paths', nargs='*',
                   help='the paths to analize, it could be a file or a directory')
    p.add_argument('--log-level', default='INFO',
                   choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
                   help='logger level')
    p.add_argument('--add', action='store_true',
                   help='add the CRC32 to the files without it')
    p.add_argument('--check', action='store_true',
                   help='calculate only the CRC32 of the files with it in the name')
    p.add_argument('--only-corrupt', action='store_true',
                   help='show only the corrupt files')
    p.add_argument('--extension', '-e', nargs='*', default=('.mp4', '.avi', '.mkv'),
                   help='add the CRC32 only to files with this extensions')
    return p


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    extensions = set(x.lower() for x in args.extension if x)

    corrupted_file = False
    error_adding_crc32 = False
    for root, fname in sorted(list_files(args.paths)):
        name_crc32 = extract_crc32(fname)
        path = os.path.join(root, fname)
        if name_crc32 is None and args.add:
            name, ext = os.path.splitext(fname)
            if extensions and ext.lower() not in extensions:
                logger.debug("The extension '%s' can't be checked", ext)
                continue

            crc32 = calculate_crc32(path)

            new_fname = "{} [{}]{}".format(name, fcrc32(crc32), ext)
            new_path = os.path.join(root, new_fname)
            logger.debug("Renaming the file '%s' to '%s'", path, new_path)
            try:
                os.rename(path, new_path)
            except OSError:
                logger.exception("Can't rename '%s' to '%s'", path, new_path)
                error_adding_crc32 = True
                continue

            cprint('{_bold}{_lblue}NEW{_reset} {} {}', fcrc32(crc32), new_path)
        elif name_crc32 is not None and args.check:
            crc32 = calculate_crc32(path)
            if crc32 != name_crc32:
                cprint('{_bold}{_lred}CORRUPT{_reset} {} {}', fcrc32(crc32), path)
                corrupted_file = True
            elif not args.only_corrupt:
                cprint('{_bold}{_lgreen}HEALTHY{_reset} {} {}', fcrc32(crc32), path)

    if corrupted_file:
        return 1
    if error_adding_crc32:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
