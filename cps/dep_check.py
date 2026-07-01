# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import re
import sys
import json

from .constants import BASE_DIR
try:
    from importlib.metadata import version
    importlib = True
    ImportNotFound = BaseException
except ImportError:
    importlib = False
    version = None

if not importlib:
    try:
        import pkg_resources
        from pkg_resources import DistributionNotFound as ImportNotFound
        pkgresources = True
    except ImportError as e:
        pkgresources = False


def load_dependencies(optional=False):
    deps = list()
    if getattr(sys, 'frozen', False):
        pip_installed = os.path.join(BASE_DIR, ".pip_installed")
        if os.path.exists(pip_installed):
            with open(pip_installed) as f:
                exe_deps = json.loads("".join(f.readlines()))
        else:
            return deps
    if importlib or pkgresources:
        pyproject_path = os.path.join(BASE_DIR, "pyproject.toml")
        if not os.path.exists(pyproject_path):
            return deps
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                return deps
        with open(pyproject_path, 'rb') as f:
            pyproject = tomllib.load(f)
        project = pyproject.get('project', {})
        if optional:
            lines = []
            for group, group_deps in project.get('optional-dependencies', {}).items():
                if group == 'dev':
                    continue
                lines.extend(group_deps)
        else:
            lines = project.get('dependencies', [])
        for line in lines:
            line = line.strip()
            if not line:
                continue
            res = re.match(r'(.*?)([<=>\s]+)([\d\.]+),?\s?([<=>\s]+)?([\d\.]+)?(?:\s?;\s?'
                           r'(?:(python_version)\s?([<=>]+)\s?\'([\d\.]+)\'|'
                           r'(sys_platform)\s?([\!=]+)\s?\'([\w]+)\'))?', line)
            if not res or not res.group(1):
                continue
            try:
                if getattr(sys, 'frozen', False):
                    dep_version = exe_deps[res.group(1).lower().replace('_', '-')]
                else:
                    if res.group(7) and res.group(8):
                        val = res.group(8).split(".")
                        if not eval(str(sys.version_info[0]) + "." + "{:02d}".format(sys.version_info[1]) +
                                    res.group(7) + val[0] + "." + "{:02d}".format(int(val[1]))):
                            continue
                    elif res.group(10) and res.group(11):
                        if res.group(10) == "==":
                            if sys.platform != res.group(11):
                                continue
                        elif res.group(10) == "!=":
                            if sys.platform == res.group(11):
                                continue
                    if importlib:
                        dep_version = version(res.group(1))
                    else:
                        dep_version = pkg_resources.get_distribution(res.group(1)).version
            except (ImportNotFound, KeyError):
                if optional:
                    continue
                dep_version = "not installed"
            deps.append([dep_version, res.group(1), res.group(2), res.group(3), res.group(4), res.group(5)])
    return deps


def dependency_check(optional=False):
    d = list()
    dep_version_int = None
    low_check = None
    deps = load_dependencies(optional)
    for dep in deps:
        try:
            dep_version_int = [int(x) if x.isnumeric() else 0 for x in dep[0].split('.')[:3]]
            low_check = [int(x) for x in dep[3].split('.')]
            high_check = [int(x) for x in dep[5].split('.')]
        except AttributeError:
            high_check = []
        except ValueError:
            d.append({'name': dep[1],
                      'target': "available",
                      'found': "Not available"
                      })
            continue

        if dep[2].strip() == "==":
            if dep_version_int != low_check:
                d.append({'name': dep[1],
                          'found': dep[0],
                          "target": dep[2] + dep[3]})
                continue
        elif dep[2].strip() == ">=":
            if dep_version_int < low_check:
                d.append({'name': dep[1],
                          'found': dep[0],
                          "target": dep[2] + dep[3]})
                continue
        elif dep[2].strip() == ">":
            if dep_version_int <= low_check:
                d.append({'name': dep[1],
                          'found': dep[0],
                          "target": dep[2] + dep[3]})
                continue
        if dep[4] and dep[5]:
            if dep[4].strip() == "<":
                if dep_version_int >= high_check:
                    d.append(
                        {'name': dep[1],
                         'found': dep[0],
                         "target": dep[4] + dep[5]})
                    continue
            elif dep[4].strip() == "<=":
                if dep_version_int > high_check:
                    d.append(
                        {'name': dep[1],
                         'found': dep[0],
                         "target": dep[4] + dep[5]})
                    continue
    return d
