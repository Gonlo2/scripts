# Github markdown table of contents

Script to create a table of contents compatible with github from a markdown.

To use it redirect the markdown to the stdin of the script like:

```shell
$ cat ../README.md | python3 gh_md_tod.py
# Table of Contents

* [Introduction](#introduction)
    * [Scripts](#scripts)
    * [Credits](#credits)
    * [License](#license)
```
