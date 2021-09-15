#!/usr/bin/env python3
import errno
import logging
import os
import re
import select
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from collections import defaultdict

import tomlkit


class BuildException(Exception):
    pass

class HookException(Exception):
    pass

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

logger = logging.getLogger(__name__)

def create_arg_parser():
    p = ArgumentParser(description='Container image craftsbot',
                       formatter_class=ArgumentDefaultsHelpFormatter)
    sp = p.add_subparsers(title='subcommands',
                          description='valid subcommands',
                          help='additional help')
    p.add_argument('-f', '--file', default='.craftsbot.toml', help='path to the craftsbot file')
    p.set_defaults(func=dummy_cmd)

    p.add_argument('--log-level', default='INFO',
                   choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
                   help='logger level')

    configure_update_arg_parser(sp.add_parser('update', help='Update a image'))

    return p

def configure_update_arg_parser(p):
    p.set_defaults(func=update_cmd)
    p.add_argument('alias', help='the alias of the image to update')
    p.add_argument('tag', nargs='?', help='the new tag')

def dummy_cmd(args):
    pass

def update_cmd(args):
    craftsbot = Craftsbot(args.file)
    craftsbot.load()

    if args.tag is not None:
        craftsbot.update(args.alias, args.tag)

    for alias, tag in craftsbot.get_affected_images(args.alias):
        if tag is True:
            craftsbot.process(alias)
            craftsbot.save()

class Craftsbot:
    _DF_FROM_RE = re.compile(r"^FROM\s+(.+?)(?::.+?)?(\s)", flags=re.M)
    _IMAGE_RE = re.compile(r"{image\.(.*?)}")

    def __init__(self, data_path):
        self._data_path = data_path
        self._data = None
        self._image_to_alias = None

    def load(self):
        logger.debug("Loading data from '%s'", self._data_path)
        with open(self._data_path) as f:
            self._data = tomlkit.parse(f.read())

        self._image_to_alias = {}
        for alias, info in self._get_images().items():
            for image in info.get('images', []):
                self._image_to_alias[image] = alias

    def save(self):
        logger.debug("Saving data to '%s'", self._data_path)
        with open(self._data_path, 'w') as f:
            f.write(tomlkit.dumps(self._data))

    def update(self, alias, tag):
        logger.debug("Updating image with alias '%s' to tag '%s'", alias, tag)
        self._get_info(alias)['tag'] = tag

    def _get_images(self):
        return self._data.get('images', {})

    def _get_info(self, alias):
        info = self._get_images().get(alias)
        #TODO raise exception
        assert info is not None
        return info

    def get_affected_images(self, alias, tag=True):
        dependencies = defaultdict(list)
        for x, info in self._get_images().items():
            for k, v in info.get('depends_on', {}).items():
                if v is True:
                    dependencies[(k, True)].append((x, True))

        visited = set()
        result = []

        def topological_sort(alias_and_tag):
            visited.add(alias_and_tag)
            for x in dependencies.get(alias_and_tag, []):
                if x not in visited:
                    topological_sort(x)
            result.append(alias_and_tag)

        topological_sort((alias, tag))
        result.reverse()

        return result

    def process(self, alias):
        tag = self._get_tmpl_tag(alias)
        logger.info("Processing image with alias '%s:%s'", alias, tag)
        info = self._get_info(alias)
        image = next(iter(info.get('images', [])), alias)

        if info.get('workdir'):
            logger.info("Building image with alias '%s:%s'", alias, tag)
            self._build(image, alias, tag, info)

        on_success = info.get('on_success')
        if on_success is not None:
            logger.info("Ejecuting on_success hook of image with alias '%s:%s'", alias, tag)
            ctx = {'image': image, 'alias': alias, 'tag': tag}
            self._execute_hook(ctx, on_success)

        info['tag'] = tag

    def _build(self, image, alias, tag, info):
        def _format_from(match):
            from_image = match.group(1)
            alias = self._image_to_alias.get(from_image, from_image)
            tag = info.get('depends_on', {}).get(alias)
            if tag is None:
                return match.group(0)
            if tag is True:
                tag = self._get_tag(alias)
            return f"FROM {from_image}:{tag}{match.group(2)}"

        dockerfile_path = os.path.join(info['workdir'], 'Dockerfile')
        dockerfile_bak_path = dockerfile_path + '.bak'
        dockerfile_tmp_path = dockerfile_path + '.craftsbot'

        with open(dockerfile_path) as f:
            dockerfile = f.read()

        new_dockerfile = self._DF_FROM_RE.sub(_format_from, dockerfile)

        with open(dockerfile_tmp_path, 'w') as f:
            f.write(new_dockerfile)

        params = ['docker', 'build']
        params.extend(["-f", dockerfile_tmp_path])
        params.extend(["-t", f"{image}:{tag}"])
        params.append(info['workdir'])

        return_code, lines = run(params)
        if return_code != 0:
            logger.error("Some error take place building the image with alias '%s:%s': %d", alias, tag, return_code)
            for kind, l in lines:
                logger.error("%s: %s", kind, l)
            raise BuildException
        logger.debug("Executed build of the image with alias '%s:%s'", alias, tag)

        with open(dockerfile_bak_path, 'w') as f:
            f.write(dockerfile)

        with open(dockerfile_path, 'w') as f:
            f.write(new_dockerfile)

        os.remove(dockerfile_tmp_path)

    def _get_tag(self, alias):
        return self._get_info(alias)['tag']

    def _get_tmpl_tag(self, alias):
        cache = {}

        def get_tmpl_tag_rec(alias):
            tag = cache.get(alias)
            if tag is None:
                info = self._get_info(alias)
                tmpl = info.get('tag_tmpl')
                if tmpl is None:
                    cache[alias] = tag = info['tag']
                else:
                    def subs(match):
                        alias = match.group(1)
                        tag = info.get('depends_on', {}).get(alias)
                        return get_tmpl_tag_rec(alias) if tag in (None, True) else tag

                    cache[alias] = 'CIRCULAR_DEPENDENCY'
                    cache[alias] = tag = self._IMAGE_RE.sub(subs, tmpl)
            return tag

        return get_tmpl_tag_rec(alias)

    def _execute_hook(self, ctx, hook):
        cmd = [x.format(**ctx) for x in hook['cmd']]
        env = {k: v.format(**ctx) for k, v in hook.get('env', {}).items()} or None
        return_code, lines = run(cmd, env=env)
        if return_code != 0:
            logger.error("Some error take place on the hook: %d", return_code)
            for kind, l in lines:
                logger.error("%s: %s", kind, l)
            raise HookException
        logger.debug("Executed hook")


def run(cmd, env=None):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    lines = []
    f_map = {
        p.stdout: ('STDOUT', [], logger.debug),
        p.stderr: ('STDERR', [], logger.warning),
    }
    while p.poll() is None:
        try:
            for f in select.select(f_map.keys(), [], [])[0]:
                kind, line_parts, log_fun = f_map[f]
                chunk_lines = os.read(f.fileno(), 2048).split(b'\n')
                line_parts.append(chunk_lines[0])
                for i in range(1, len(chunk_lines)):
                    line = b''.join(line_parts).decode('utf-8')
                    line = ANSI_ESCAPE.sub('', line)
                    lines.append((kind, line))
                    log_fun('%s: %s', kind, line)
                    line_parts.clear()
                    line_parts.append(chunk_lines[i])
        except (OSError, select.error) as e:
            if hasattr(e, "errno") and e.errno == errno.EINTR:
                continue
            if hasattr(e, "args") and e.args[0] == errno.EINTR:
                continue
            raise

    for f, (kind, line_parts, log_fun) in f_map.items():
        chunk_lines = f.read().split(b'\n')
        for l in chunk_lines:
            line_parts.append(l)
            line = b''.join(line_parts).decode('utf-8')
            line = ANSI_ESCAPE.sub('', line)
            lines.append((kind, line))
            log_fun('%s: %s', kind, line)
            line_parts.clear()

    return (p.returncode, lines)


def main(args):
    parser = create_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    args.func(args)


if __name__ == "__main__":
    main(sys.argv)
