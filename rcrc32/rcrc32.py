#!/usr/bin/env python3
import logging
import os
import random
import re
import stat
import sys
import zlib
from argparse import (ArgumentDefaultsHelpFormatter, ArgumentParser,
                      ArgumentTypeError)

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
    result = []
    for path in paths:
        _list_files(path, os.stat(path), result)
    return result


def _list_files(path, st, result):
    if stat.S_ISDIR(st.st_mode):
        with os.scandir(path) as it:
            for entry in it:
                _list_files(entry.path, entry.stat(), result)
    else:
        root, fname = os.path.split(path)
        result.append((root, fname, st.st_size))


def filter_randomly(files, percentage):
    size_sum = sum(f[2] for f in files)
    logger.debug("The total file size is %d", size_sum)
    size_limit = max(int(size_sum * (percentage / 100.0)), 1)
    result_size = 0
    result = []
    while files and result_size < size_limit:
        i = random.randrange(len(files))
        logger.debug("Adding the file '%s/%s' with size %d", files[i][0], files[i][1], files[i][2])
        result_size += files[i][2]
        result.append(files[i])
        files[i] = files[-1]
        files.pop()
    logger.debug("The result file size is %d of %d (%f%%)", result_size, size_sum, 100.0 * result_size / size_sum)
    return result


def filter_extensions(files, extensions):
    result = []
    for f in files:
        name, ext = os.path.splitext(f[1])
        if ext.lower() in extensions:
            result.append(f)
    return result


def filter_name_crc32(files):
    return [f for f in files if extract_crc32(f[1]) is not None]


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
    p.add_argument('--random', type=type_random, default=None,
                   help='apply randomly to this percentage of the files size')
    p.add_argument('--extension', '-e', nargs='*', default=('.mp4', '.avi', '.mkv'),
                   help='apply only to files with this extensions')
    return p


def type_random(x):
    try:
        return max(0.0, min(float(x), 100.0))
    except ValueError:
        raise ArgumentTypeError("The random percentage must be a valid number")


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    logger.debug("Listing files")
    files = list_files(args.paths)

    extensions = set(x.lower() for x in args.extension if x)
    if extensions:
        logger.debug("Filtering files by extension")
        files = filter_extensions(files, extensions)

    if not args.add:
        logger.debug("Filtering files with name CRC32")
        files = filter_name_crc32(files)

    if args.random is not None:
        logger.debug("Filtering files randomly")
        files = filter_randomly(files, args.random)

    corrupted_file = False
    error_adding_crc32 = False
    logger.debug("Doing operations")
    files.sort()
    for root, fname, _ in files:
        path = os.path.join(root, fname)
        name_crc32 = extract_crc32(fname)
        if name_crc32 is None and args.add:
            crc32 = calculate_crc32(path)

            name, ext = os.path.splitext(fname)
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
