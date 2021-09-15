#!/usr/bin/env bash
set -e
IMAGE="$1"
VERSION="$2"
DOCKERCOMPOSE="$3"
IMAGE_RE=`python -c "import re; import sys; sys.stdout.write(re.escape(sys.argv[1]))" "$IMAGE"`

sed -i -E "s|image: ['\"]?$IMAGE_RE(:.+?)?['\"]?$|image: \"$IMAGE:$VERSION\"|gm" "$DOCKERCOMPOSE"

docker-compose -f "$DOCKERCOMPOSE" up -d --remove-orphans
