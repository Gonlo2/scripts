#!/usr/bin/env python3
import re
import sys


def main():
    title_re = re.compile(r"^(#+)\s+(.*)$", flags=re.MULTILINE)
    split_re = re.compile(r"\W+")

    print("# Table of Contents")
    print()
    for m in title_re.finditer(sys.stdin.read()):
        level = len(m.group(1))-1
        title = m.group(2)
        normalized_title = '-'.join(x for x in split_re.split(title.lower()) if x)

        print(" " * (level*4) + f"* [{title}](#{normalized_title})")


if __name__ == "__main__":
    main()
