#!/usr/bin/env python3
import logging
import os
import re
import shutil
import sys
import zlib
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from power_manager.client import Client as PowerManagerClient

CRC32_PATTERN = re.compile(r"\[([0-F]{8})\]")

logger = logging.getLogger(__name__)


class FileStatus(Enum):
    OK = 0
    ERROR = 1
    CORRUPTED = 2
    CONFLICT_NAME = 3


@dataclass
class File:
    status: FileStatus
    path: str
    src_name: str
    dst_name: str

    def src_path(self, root):
        return os.path.join(root, self.path, self.src_name)

    def dst_path(self, root):
        return os.path.join(root, self.path, self.dst_name)


def fcrc32(value):
    return f'{value:0>8X}'


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


def list_files(path):
    result = []
    for root, _, files in os.walk(path):
        root = os.path.relpath(root, path)
        for name in files:
            f = File(
                status=FileStatus.OK,
                path=root,
                src_name=name,
                dst_name=name,
            )
            result.append(f)
    return result


def validate_crc32(root, files):
    correct = []
    corrupted = []

    for f in files:
        p = f.src_path(root)
        extracted_crc32 = extract_crc32(f.dst_name)
        if extracted_crc32 is None:
            logger.debug("The file '%s' don't have a crc32", p)
            correct.append(f)
        else:
            calculated_crc32 = calculate_crc32(p)
            if calculated_crc32 == extracted_crc32:
                logger.debug("The file '%s' has a correct crc32", p)
                correct.append(f)
            else:
                logger.warning("The file '%s' has the crc32 '%s' but the name has crc32 '%s'",
                               p, fcrc32(calculated_crc32), fcrc32(extracted_crc32))
                f.status = FileStatus.CORRUPTED
                corrupted.append(f)

    return (correct, corrupted)


def add_crc32(root, files, extensions):
    result = []

    extensions = set(x.lower() for x in extensions)
    for f in files:
        crc32 = extract_crc32(f.src_name)
        if crc32 is None:
            name, ext = os.path.splitext(f.dst_name)
            if ext.lower() in extensions:
                crc32 = calculate_crc32(f.src_path(root))
                f.dst_name = f"{name} [{fcrc32(crc32)}]{ext}"
        result.append(f)

    return result


class FileOperation:
    def __init__(self, src, dst, op):
        self._src = src
        self._dst = dst
        self._op = op

    def apply(self, files):
        correct = []
        incorrect = []
        for f in files:
            status = self._apply(f)
            if status == FileStatus.OK:
                correct.append(f)
            else:
                f.status = status
                incorrect.append(f)
        return (correct, incorrect)

    def _apply(self, f):
        src = os.path.join(self._src, f.path)
        dst = os.path.join(self._dst, f.path)
        logger.debug('Cloning the path "%s" to "%s"', src, dst)
        try:
            os.makedirs(dst)
            shutil.copystat(src, dst)
        except FileExistsError:
            pass
        except OSError:
            logger.exception('Failed cloning dir "%s" to "%s"', src, dst)
            return FileStatus.ERROR

        src = f.src_path(self._src)

        name = get_non_conflict_name(os.path.join(self._dst, f.path), f.dst_name)
        if name is None:
            logger.warning('Failed to detect a non conflict name for "%s"', f.dst_name(self._dst))
            return FileStatus.CONFLICT_NAME
        f.dst_name = name

        dst = f.dst_path(self._dst)
        logger.debug('Coping "%s" to "%s"', src, dst)
        try:
            self._op(src, dst)
        except OSError:
            logger.exception('Failed apply operation "%s" to "%s"', src, dst)
            return FileStatus.ERROR

        return FileStatus.OK


def get_non_conflict_name(path, name):
    head, ext = os.path.splitext(name)
    for i in range(2, 1000):
        if not os.path.exists(os.path.join(path, name)):
            return name
        name = f'{head} ({i}){ext}'
    return None


def create_arg_parser():
    p = ArgumentParser(
        description="Move files to a nas",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('workspace_path', help='workspace path')
    p.add_argument('dst_path', help='dst path')
    p.add_argument('--pm-address', default='http://127.0.0.1:9353',
                   help='power manager address')
    p.add_argument('--pm-token-id', default='pytonas',
                   help='the power manager token id')
    p.add_argument('--log-level', default='INFO',
                   choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
                   help='logger level')
    p.add_argument('--remove', action='store_true',
                   help='remove the copied files after a successful copy')
    p.add_argument('--check', action='store_true',
                   help='check the integration of the files')
    p.add_argument('--add-crc32', action='store_true',
                   help='add the crc32 to the files')
    p.add_argument('--crc32-ext', nargs='*', default=('.mp4', '.avi', '.mkv'),
                   help='file extensions to add the crc32')
    return p


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    current_date = datetime.now().strftime('%Y%m%d-%H%M%S')
    src = os.path.join(args.workspace_path, 'to_move')

    logger.debug("Obtaining the folders to copy from '%s'", src)

    correct = list_files(src)
    incorrect = []

    if args.check:
        logger.debug("Validating the files of '%s'", src)
        correct, incorrect = validate_crc32(src, correct)

    if args.add_crc32:
        logger.debug("Adding the crc32 of the files in '%s'", src)
        correct = add_crc32(src, correct, args.crc32_ext)

    if correct:
        logger.debug("Starting power manager")
        pm = PowerManagerClient(args.pm_address, token_id=args.pm_token_id)
        pm.start()

        pm.acquire()
        try:
            logger.debug("Coping the correct files from '%s' to '%s'", src, args.dst_path)
            fop = FileOperation(src, args.dst_path, shutil.copy)
            correct, e = fop.apply(correct)
            incorrect.extend(e)
        finally:
            pm.release()

    if args.remove:
        logger.debug("Removing the correct files from '%s'", src)
        for f in correct:
            try:
                p = f.src_path(src)
                logger.debug("Removing the file '%s'", p)
                os.remove(p)
            except OSError:
                incorrect.append(f)
        correct = []
    else:
        dst = os.path.join(args.workspace_path, 'moved', current_date)
        logger.debug("Moving the correct files from '%s' to '%s'", src, dst)
        fop = FileOperation(src, dst, shutil.move)
        _, e = fop.apply(correct)
        incorrect.extend(e)

    for f in incorrect:
        f.dst_name = f.src_name

    dst = os.path.join(args.workspace_path, 'failed', current_date)
    logger.debug("Moving the incorrect files from '%s' to '%s'", src, dst)
    fop = FileOperation(src, dst, shutil.move)
    fop.apply(incorrect)

    logger.debug("Removing the empty dirs from '%s'", src)
    for root, _, _ in os.walk(src, topdown=False):
        if root != src:
            try:
                logger.debug("To remove the dir  '%s' if empty", root)
                os.rmdir(root)
            except OSError:
                pass

    sys.exit(1 if incorrect else 0)


if __name__ == "__main__":
    main()
