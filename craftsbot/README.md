# Craftsbot

Script to manage docker images dependencies without getting lost in the ocean.

## Usage

First you need [pipenv](https://pipenv.pypa.io/en/latest/#) to install the dependencies. Once installed is possible update some dependency tag and build the affected images executing

```bash
pipenv run ./craftsbot.py update alpine 3.14.2
```

Or if you want to only build the images that use a dependency ignore the tag

```bash
pipenv run ./craftsbot.py update alpine
```

## Dependencies file example

The dependencies file mush have the name `.craftsbot.toml` and have the next format

```toml
# Some docker image without a workdir to build the image
[images.alpine]
description = "Security-oriented, lightweight Linux distribution based on musl libc and busybox."
tag = "3.14.2"

# Some docker image without a workdir to build the image but with a hook on success
[images.nginx]
description = "Web server that can also be used as a reverse proxy, load balancer, mail proxy and HTTP cache"
tag = "1.21.0-alpine"
on_success.cmd = [ "/data/craftsbot/update_docker_compose_image.sh", "{image}", "{tag}", "/data/nginx/docker-compose.yaml",]

# Some docker image without a workdir to build the image but with a different image name that the resource alias
[images.prometheus]
images = [ "prom/prometheus",]
description = "Systems and service monitoring system"
tag = "v2.28.1"
on_success.cmd = [ "/data/craftsbot/update_docker_compose_image.sh", "{image}", "{tag}", "/data/nginx/docker-compose.yaml",]

# Some docker image with a dependency defined in the resources file
[images.syncthing]
description = "Continuous file synchronization program"
tag_tmpl = "1.17.0-alpine_{image.alpine}"
workdir = "/data/syncthing"
tag = "1.17.0-alpine_3.14.2"
depends_on.alpine = true
on_success.cmd = [ "/data/craftsbot/update_docker_compose_image.sh", "{image}", "{tag}", "/data/nginx/docker-compose.yaml",]

# Some docker image with a forced dependency tag
[images.dnsmasq]
description = "Lightweight, easy to configure DNS forwarder"
tag_tmpl = "alpine_{image.alpine}"
workdir = "/home/pi/dockerfiles/dnsmasq"
tag = "alpine_3.13.5"
depends_on.alpine = "3.13.5"
on_success.cmd = [ "/data/craftsbot/update_docker_compose_image.sh", "{image}", "{tag}", "/data/dnsmasq/docker-compose.yaml",]
```
