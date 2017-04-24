# Copyright (C) 2008-2010 Adam Olsen
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#
# The developers of the Exaile media player hereby grant permission
# for non-GPL compatible GStreamer and Exaile plugins to be used and
# distributed together with GStreamer and Exaile. This permission is
# above and beyond the permissions granted by the GPL license by which
# Exaile is covered. If you modify this code, you may extend this
# exception to your version of the code, but you are not obligated to
# do so. If you do not wish to do so, delete this exception statement
# from your version.

from collections import namedtuple
import copy

import logging
logger = logging.getLogger('xl.metadata')

INFO_TAGS = ['__bitrate', '__length']

# Generic description of cover images
# - type is a number corresponding to the cover type of ID3 APIC tags, 
#   desc is a string describing the image, mime is a type, 
#   data is the img data
# -> if type is None, then the type is not changeable
CoverImage = namedtuple('CoverImage', 'type desc mime data')

class NotWritable(Exception):
    pass

class NotReadable(Exception):
    pass

class BaseFormat(object):
    """
        Base class for handling loading of metadata from files.

        subclasses using mutagen should set MutagenType and overload
        the _get_tag, _set_tag, and _del_tag methods as needed.

        subclasses not using mutagen should leave MutagenType as None
    """
    MutagenType = None
    
    # This should contain ALL keys supported by this filetype, unless 'others'
    # is set to True. If others is True, then anything not in tag_mapping will
    # be written using the Exaile tag name
    # -> dict k: exaile tag name, v: native tag name
    tag_mapping = {}
    others = True
    writable = False
    case_sensitive = True
    
    @classmethod
    def _compute_mappings(cls):
        # this only needs to be run once per class
        
        if cls.case_sensitive:
            cls._reverse_mapping = {v: k for k,v in cls.tag_mapping.iteritems()}
        else:
            cls._reverse_mapping = {v.lower(): k for k,v in cls.tag_mapping.iteritems()}
        
        from .tags import disk_tags
        cls.ignore_tags = set(disk_tags)
        
    def __init__(self, loc):
        """
            Raises :class:`NotReadable` if the file cannot be
            opened for some reason.

            :param loc: absolute path to the file to read
                (note - this may change to accept gio uris in the future)
        """
        self.loc = loc
        self.open = False
        self.mutagen = None
        try:
            self._reverse_mapping
        except AttributeError:
            self.__class__._compute_mappings()
        
        self.load()

    def load(self):
        """
            Loads the tags from the file.
        """
        if self.MutagenType:
            try:
                self.mutagen = self.MutagenType(self.loc)
            except Exception:
                raise NotReadable

    def save(self):
        """
            Saves any changes to the tags.
        """
        if self.writable and self.mutagen:
            self.mutagen.save()

    def _get_raw(self):
        if self.MutagenType:
            return self.mutagen
        else:
            return {}

    def _get_tag(self, raw, tag):
        try:
            return raw[tag]
        except KeyError:
            return None

    def _get_keys(self):
        keys = []
        for k in self._get_raw().keys():
            if k in self._reverse_mapping:
                keys.append(self._reverse_mapping[k])
            else:
                keys.append(k)
        return keys

    def read_all(self):
        """
            Reads all non-blacklisted tags from the file.

            Blacklisted tags include lyrics, covers, and any field starting
            with __. If you need to read these, call read_tags directly.
        """
        tags = INFO_TAGS[:]
        for t in self.get_keys_disk():
            if t in self.ignore_tags:
                continue
            # __ is used to denote exaile's internal tags, so we skip
            # loading them to avoid conflicts. usually this shouldn't be
            # an issue.
            if isinstance(t, basestring) and t.startswith("__"):
                continue
            tags.append(t)
        alltags = self.read_tags(tags)
        return alltags

    def read_tags(self, tags):
        """
            get the values for the specified tags.

            returns a dict of the found values. if no value was found for a
            requested tag it will not exist in the returned dict.

            :param tags: a list of tag names to read
            :returns: a dictionary of tag/value pairs.
        """
        raw = self._get_raw()
        td = {}
        for tag in tags:
            t = None
            if tag in INFO_TAGS:
                try:
                    t = self.get_info(tag)
                except KeyError:
                    pass
            if t == None and tag in self.tag_mapping:
                try:
                    t = self._get_tag(raw, self.tag_mapping[tag])
                    if type(t) in [str, unicode]:
                        t = [t]
                    elif isinstance(t, list):
                        pass
                    elif t is not None:
                        try:
                            t = [unicode(u) for u in list(t)]
                        except UnicodeDecodeError:
                            t = t
                except (KeyError, TypeError):
                    logger.debug("Unexpected error reading `%s`", tag, exc_info=True)
            if t == None and self.others:
                try:
                    t = self._get_tag(raw, tag)
                    if type(t) in [str, unicode]:
                        t = [t]
                    elif t is not None:
                        t = [unicode(u) for u in list(t)]
                except (KeyError, TypeError):
                    logger.debug("Unexpected error reading `%s`", tag, exc_info=True)

            if t not in [None, []]:
                td[tag] = t
        return td

    def _set_tag(self, raw, tag, value):
        raw[tag] = value

    def _del_tag(self, raw, tag):
        del raw[tag]

    def write_tags(self, tagdict):
        """
            Write a set of tags to the file. Raises a NotWritable exception
            if the format does not support writing tags.

            :param tagdict: A dictionary of tag/value pairs to write.
        """
        if not self.MutagenType or not self.writable:
            raise NotWritable
        else:
            tagdict = copy.deepcopy(tagdict)
            raw = self._get_raw()
            # Add tags if it doesn't have them.
            # Most of Mutagen's modules throw an exception if the file already
            # contains tags, except for mp4. See also
            # http://code.google.com/p/mutagen/issues/detail?id=101
            if getattr(raw, 'tags', None) is None:
                try:
                    raw.add_tags()
                except Exception:
                    # XXX: Not sure needed since we're already checking for
                    # existence of tags.
                    pass

            # info tags are not actually writable
            for tag in INFO_TAGS:
                try:
                    del tagdict[tag]
                except KeyError:
                    pass

            # tags starting with __ are internal and should not be written
            for tag in tagdict.keys():
                if tag.startswith("__"):
                    try:
                        del tagdict[tag]
                    except KeyError:
                        pass

            for tag in tagdict:
                if tag in self.tag_mapping:
                    self._set_tag(raw, self.tag_mapping[tag], tagdict[tag])
                elif self.others:
                    self._set_tag(raw, tag, tagdict[tag])

            defname = None
            for tag in raw:
                if self.others:
                    # this is here so that the delete will succeed later
                    defname = tag
                tagname = self._reverse_mapping.get(tag, defname)
                if tagname is None:
                    tag = tag.split(':',1)[0]   # handles multi-part tags
                    tagname = self._reverse_mapping.get(tag)
                # delete tags not present in the tagdict
                if tagname and tagname not in tagdict:
                    self._del_tag(raw, tag)
            self.save()

    def get_info(self, info):
        # TODO: add sample rate? filesize?
        if info == "__length":
            return self.get_length()
        elif info == "__bitrate":
            return self.get_bitrate()
        else:
            raise KeyError

    def get_length(self):
        try:
            return self.mutagen.info.length
        except AttributeError:
            try:
                return self._get_raw()['__length']
            except (KeyError, TypeError):
                return None

    def get_bitrate(self):
        try:
            return self.mutagen.info.bitrate
        except AttributeError:
            try:
                return self._get_raw()['__bitrate']
            except (KeyError, TypeError):
                return None

class CaseInsensitveBaseFormat(BaseFormat):
    case_sensitive = False
    
    def get_keys_disk(self):
        """
            Returns keys of all tags that can be read from disk
        """
        return [self._reverse_mapping.get(k.lower(), k) for k in self._get_raw().keys()]

# vim: et sts=4 sw=4

