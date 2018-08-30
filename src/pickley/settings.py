# coding=utf-8
"""
Simple json configuration system

<base>: installation folder, ex ~/.local/bin

The following locations will be examined for config (in this order, first value found wins):
- ~/.config/pickley.json
- <base>/pickley.json

tree <base>
├── .pickley/                       # Folder where pickley will build/manage/track installations
│   ├── audit.log                   # Activity is logged here
│   ├── tox/
│   │   ├── dist/                   # Temp folder used during packaging
│   │   ├── tox-2.9.1/              # Actual installation, as packaged by pickley
│   │   ├── current.json            # Currently installed version
│   │   └── latest.json             # Latest version as determined by querying pypi
├── tox -> .pickley/tox/2.9.1/...   # Produced exe, can be a symlink or a small wrapper exe (to ensure up-to-date)
├── pickley                         # pickley itself
└── pickley.json                    # Optional config provided by user

{
    "bundle": {
        "mybundle": "tox twine"
    },
    "channels": {
        "stable": {
            "tox": "1.0"
        }
    },
    "default": {
        "channel": "latest",
        "delivery": "wrapper, or symlink, or copy",
        "packager": "virtualenv"
    },
    "include": [
        "~/foo/pickley.json"
    ],
    "index": "https://pypi.org/",
    "select": {
        "twine": {
            "channel": "latest",
            "delivery": "symlink",
            "packager": "pex",
        }
    }
}
"""

import json
import logging
import os
import sys

import six

from pickley import ensure_folder, flattened, represented_args, resolved_path, short


LOG = logging.getLogger(__name__)


def same_type(t1, t2):
    """
    :return bool: True if 't1' and 't2' are of equivalent types
    """
    if isinstance(t1, six.string_types) and isinstance(t2, six.string_types):
        return True
    return type(t1) == type(t2)


def meta_cache(path):
    """
    :param str path: Path to folder to use
    :return FolderBase: Associated object
    """
    return FolderBase(os.path.join(path, ".pickley"), name="meta")


def add_representation(result, data, indent=""):
    if not data:
        return
    if isinstance(data, list):
        for item in data:
            result.append("%s- %s" % (indent, short(item)))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                brief = represented_args(value, separator=", ")
                if len(brief) < 60:
                    result.append("%s%s: [%s]" % (indent, short(key), brief))
                    continue
            if not isinstance(value, (dict, list)):
                result.append("%s%s: %s" % (indent, short(key), short(value)))
            else:
                result.append("%s%s:" % (indent, short(key)))
                add_representation(result, value, indent="  %s" % indent)
        return
    result.append("%s- %s" % (indent, short(data)))


class JsonSerializable:
    """
    Json serializable object
    """

    _path = None            # type: str # Path where this file should be stored, if any
    _source = None          # type: str # Where data came from

    def __repr__(self):
        return self._source or "no source"

    @classmethod
    def from_json(cls, path):
        """
        :param str path: Path to json file
        :return cls: Deserialized object
        """
        result = cls()
        result.load(path)
        return result

    def set_from_dict(self, data, source=None):
        """
        :param dict data: Set this object from deserialized 'dict'
        :param source: Source where 'data' came from
        """
        if source:
            self._source = source
        if not data:
            return
        for key, value in data.items():
            key = key.replace("-", "_")
            if not hasattr(self, key):
                LOG.debug("%s is not an attribute of %s", key, self.__class__.__name__)
                continue
            attr = getattr(self, key)
            if attr is not None and not same_type(value, attr):
                LOG.debug(
                    "Wrong type %s for %s.%s in %s, expecting %s",
                    type(value),
                    self.__class__.__name__,
                    key,
                    self._source,
                    type(attr)
                )
                continue
            setattr(self, key, value)

    def reset(self):
        """
        Reset all fields of this object to class defaults
        """
        for name in self.__dict__:
            if name.startswith('_'):
                continue
            attr = getattr(self, name)
            setattr(self, name, attr and attr.__class__())

    def to_dict(self):
        """
        :return dict: This object serialized to a dict
        """
        result = {}
        for name in self.__dict__:
            if name.startswith('_'):
                continue
            name = name.replace("_", "-")
            attr = getattr(self, name)
            result[name] = attr.to_dict() if isinstance(attr, JsonSerializable) else attr
        return result

    def load(self, path=None):
        """
        :param str|None path: Load this object from file with 'path' (default: self._path)
        """
        self.reset()
        if path:
            self._path = path
            self._source = short(path)
        if not self._path:
            return
        data = JsonSerializable.get_json(self._path)
        if not data:
            return
        self.set_from_dict(data)

    def save(self, path=None):
        """
        :param str|None path: Save this serializable to file with 'path' (default: self._path)
        """
        JsonSerializable.save_json(self.to_dict(), path or self._path)

    @staticmethod
    def save_json(data, path):
        """
        :param dict|list|None data: Data to serialize and save
        :param str path: Path to file where to save
        """
        if data is None or not path:
            return
        try:
            path = resolved_path(path)
            ensure_folder(path, dryrun=SETTINGS.dryrun)
            if SETTINGS.dryrun:
                LOG.debug("Would save %s", short(path))
            else:
                with open(path, 'wt') as fh:
                    json.dump(data, fh, sort_keys=True, indent=2)

        except Exception as e:
            LOG.warning("Couldn't save %s: %s", short(path), e)

    @staticmethod
    def get_json(path, default=None):
        """
        :param str path: Path to file to deserialize
        :param dict|list default: Default if file is not present, or if it's not json
        :return dict|list: Deserialized data from file
        """
        path = resolved_path(path)
        if not path or not os.path.exists(path):
            return default

        try:
            with open(path, 'rt') as fh:
                LOG.debug("Reading %s", short(path))
                data = json.load(fh)
                if default is not None and type(data) != type(default):
                    LOG.warning("Wrong type %s for %s, expecting %s", type(data), short(path), type(default))
                return data

        except Exception as e:
            LOG.warning("Invalid json file %s: %s", short(path), e)
            return default


class FolderBase(object):
    """
    This class allows to more easily deal with folders
    """

    def __init__(self, path, name=None):
        """
        :param str path: Path to folder
        :param str|None name: Name of this folder (defaults to basename of 'path')
        """
        self.path = resolved_path(path)
        self.name = name or os.path.basename(path)

    def relative_path(self, path):
        """
        :param str path: Path to relativize
        :return str: 'path' relative to self.path
        """
        return os.path.relpath(path, self.path)

    def full_path(self, *relative):
        """
        :param list(str) *relative: Relative components
        :return str: Full path based on self.path
        """
        return os.path.join(self.path, *relative)

    def __repr__(self):
        return "%s: %s" % (self.name, short(self.path))


class Definition:
    """
    Defined value, with origin where the value came from
    """

    def __init__(self, value, source=None):
        """
        :param value: Actual value
        :param SettingsFile|None source: Where value was defined
        """
        self.value = value
        self.source = source
        self.channel = None

    def __repr__(self):
        channel = " [%s]" % self.channel if self.channel else ""
        source = " from %s" % short(self.source.path) if self.source else ""
        return "%s%s%s" % (self.value, source, channel)

    def __str__(self):
        return str(self.value)


class SettingsFile:
    """
    Deserialized json settings file, configures:
    - installation "channel" to use (stable, latest, ...)
    - other setting files to include
    - versions to use per channel
    """
    def __init__(self, parent, path=None):
        """
        :param Settings parent: Parent settings object
        :param str|None path: Path to settings file
        """
        self.parent = parent
        self.path = short(path) or "defaults"
        self.folder = path and os.path.dirname(resolved_path(path))
        self._contents = None

    def __repr__(self):
        return self.path

    def set_contents(self, *args, **kwargs):
        for arg in args:
            if isinstance(arg, dict):
                kwargs.update(args[0])
        self._contents = kwargs
        self.flatten("bundle", separator=" ")
        self.flatten("include", direct=True)
        bundle = self._contents.get("bundle")
        if isinstance(bundle, dict):
            result = {}
            for name, value in bundle.items():
                result[name] = self.unbundled_names(value)
            self._contents["bundle"] = result

    def unbundled_names(self, names):
        """
        :param list|tuple names: Names to unbundle
        :return set: Resolved full set of names
        """
        result = []
        if names:
            for name in names:
                if name.startswith("bundle:"):
                    bundle = self.get_value("bundle.%s" % name[7:])
                    if bundle:
                        result.extend(flattened(bundle, separator=" "))
                        continue
                result.append(name)
        return flattened(result, separator=" ")

    def flatten(self, key, separator=None, direct=False):
        if not self._contents:
            return
        node = self._contents.get(key)
        if not node:
            return
        if direct:
            self._contents[key] = flattened(node, separator=separator)
            return
        result = {}
        for name, value in node.items():
            result[name] = flattened(value, separator=separator)
        self._contents[key] = result

    @property
    def contents(self):
        """
        :return dict: Deserialized contents of settings file
        """
        if self._contents is None:
            self.set_contents(JsonSerializable.get_json(self.path, default={}))
        return self._contents

    @property
    def include(self):
        """
        :return list(str): Optional list of other settings files to include
        """
        return self.contents.get("include")

    def package_channel(self, package_name):
        """
        :param str package_name: Package name
        :return Definition|None: Channel to use to determine versions for 'package_name'
        """
        value = self._get_raw_value("select.%s.channel" % package_name)
        if value:
            return value
        channels = self.contents.get("channels")
        if isinstance(channels, dict):
            for name, values in channels.items():
                if package_name in values:
                    return Definition(name, source=self)
        return None

    def get_definition(self, key, package_name=None):
        """
        :param str key: Key to look up
        :param str|None package_name: Optional associated package name
        :return Definition|None: Definition corresponding to 'key' in this settings file, if any
        """
        value = self.get_value(key, package_name=package_name)
        if value is not None:
            return Definition(value, source=self)
        return None

    def get_value(self, key, package_name=None):
        """
        :param str key: Key to look up
        :param str|None package_name: Optional associated package name
        :return: Value corresponding to 'key' in this settings file, if any
        """
        if not key:
            return None
        if package_name:
            value = self._get_raw_value("select.%s.%s" % (package_name, key))
            if value:
                return value
        return self._get_raw_value(key)

    def _get_raw_value(self, key):
        """
        :param str key: Key to look up
        :return: Value corresponding to 'key' in this settings file, if any
        """
        if not key:
            return None
        if "." in key:
            prefix, _, leaf = key.rpartition(".")
            value = self._get_raw_value(prefix)
            if isinstance(value, dict):
                return value.get(leaf)
            if value is not None:
                LOG.debug("'%s' is not a dict in '%s'", prefix, self)
            return None
        return self.contents.get(key)

    def represented(self):
        """
        :return str: Human readable representation of these settings
        """
        if not self.contents:
            return "    - %s: # empty" % short(self.path)
        result = ["    - %s:" % short(self.path)]
        add_representation(result, self.contents, indent="      ")
        return "\n".join(result)


class Settings:
    """
    Collection of settings files
    """

    def __init__(self, base=None, config=None, dryrun=False):
        """
        :param str|None base: Base folder to use
        :param list|None config: Optional configuration files to load
        :param bool dryrun: Whether execution should perform a dryrun or not
        """
        if not base:
            base = os.environ.get("PICKLEY_ROOT")
        if not base and sys.prefix.endswith(".venv"):
            # Convenience for development
            base = os.path.join(sys.prefix, "root")
        if not base:
            # By default, base is folder of executable
            base = os.path.dirname(resolved_path(sys.argv[0]))

        self.base = FolderBase(base, name="base")
        self.dryrun = dryrun
        self.cache = meta_cache(self.base.path)
        self.defaults = SettingsFile(self)
        self.defaults.set_contents(
            default=dict(
                channel="latest",
                delivery="symlink",
                packager="virtualenv",
            ),
        )
        self.paths = set()
        self.children = []
        if config:
            self.add(config)

    def __repr__(self):
        return "[%s] %s" % (len(self.children), self.base)

    def add(self, paths, base=None):
        """
        :param list(str) paths: Paths to files to consider as settings
        :param str base: Base path to use to resolve relative paths
        """
        if not paths:
            return
        if not base:
            base = self.base.path
        for path in paths:
            path = resolved_path(path, base=base)
            if path in self.paths:
                return
            settings_file = SettingsFile(self, path)
            self.paths.add(path)
            self.children.append(settings_file)
            if settings_file.include:
                self.add(settings_file.include, base=settings_file.folder)

    def get_definition(self, key, package_name=None):
        """
        :param str key: Key to look up
        :param str|None package_name: Optional associated package name
        :return Definition|None: Top-most definition found, if any
        """
        value = self._get_raw_definition(key, package_name=package_name)
        if value is not None:
            return value
        return self._get_raw_definition("default.%s" % key, package_name=package_name)

    def _get_raw_definition(self, key, package_name=None):
        """
        :param str key: Key to look up
        :param str|None package_name: Optional associated package name
        :return Definition|None: Top-most definition found, if any
        """
        for child in self.children:
            value = child.get_definition(key, package_name=package_name)
            if value is not None:
                return value
        return self.defaults.get_definition(key, package_name=package_name)

    def get_value(self, key, package_name=None, default=None):
        """
        :param str key: Key to look up
        :param str|None package_name: Optional associated package name
        :param default: Default value to return if 'key' is not defined
        :return: Value corresponding to 'key' in this settings file, if any
        """
        value = self.get_definition(key, package_name=package_name)
        if value is not None:
            return value.value
        return default

    @property
    def default_packager(self):
        """
        :return str: Default packager to use
        """
        return self.get_value("default.packager").lower()

    @property
    def default_channel(self):
        """
        :return str: Default channel to use
        """
        return self.get_value("default.channel", default="latest").lower()

    @property
    def index(self):
        """
        :return str: Optional pypi index to use
        """
        return self.get_value("index")

    def resolved_packages(self, names):
        """
        :param list|tuple names: Names to resolve
        :return set: Resolved names
        """
        result = []
        if names:
            for name in names:
                if name.startswith("bundle:"):
                    bundle = self.get_value("bundle.%s" % name[7:])
                    if bundle:
                        result.extend(bundle)
                        continue
                result.append(name)
        return flattened(result)

    def package_delivery(self, package_name):
        """
        :param str package_name: Package name
        :return Definition: Delivery mode to use
        """
        return self.get_definition("delivery", package_name=package_name)

    def package_channel(self, package_name):
        """
        :param str package_name: Package name
        :return Definition: Channel to use to determine versions for 'package_name'
        """
        for child in self.children:
            value = child.package_channel(package_name)
            if value is not None:
                return value
        return self.get_definition("default.channel")

    def version(self, package_name, channel=None):
        """
        :param str package_name: Package name to lookup version for
        :param Definition|None channel: Alternative channel to use
        :return Definition: Configured version
        """
        if not channel:
            channel = self.package_channel(package_name)
        definition = self.get_definition("channels.%s.%s" % (channel.value, package_name))
        if not definition:
            definition = Definition(None)
        definition.channel = channel.value
        return definition

    def current_names(self):
        """Yield names of currently installed packages"""
        result = []
        if os.path.isdir(self.cache.path):
            for fname in os.listdir(self.cache.path):
                fpath = os.path.join(self.cache.path, fname)
                if not os.path.isdir(fpath):
                    continue
                fpath = os.path.join(fpath, "current.json")
                if not os.path.exists(fpath):
                    continue
                result.append(fname)
        return result

    def represented(self):
        """
        :return str: Human readable representation of these settings
        """
        result = [
            "settings:",
            "  base: %s" % short(self.base.path),
            "  cache: %s" % short(self.cache.path),
        ]
        if self.index:
            result.append("  index: %s" % self.index)
        result.append("  config:")
        for child in self.children:
            result.append(child.represented())
        result.append(self.defaults.represented())
        return "\n".join(result)


SETTINGS = Settings()