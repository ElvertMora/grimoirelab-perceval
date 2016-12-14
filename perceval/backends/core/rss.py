# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Authors:
#     Alvaro del Castillo <acs@bitergia.com>
#

import json
import logging
import os.path

import feedparser
import requests

from ...backend import Backend, BackendCommand, metadata
from ...cache import Cache
from ...errors import CacheError
from ...utils import (DEFAULT_DATETIME,
                      datetime_to_utc,
                      str_to_datetime,
                      urljoin)


logger = logging.getLogger(__name__)


class RSS(Backend):
    """RSS backend for Perceval.

    This class retrieves the entries from a RSS feed.
    To initialize this class the URL must be provided.
    The `url` will be set as the origin of the data.

    :param url: RSS url
    :param tag: label used to mark the data
    :param cache: cache object to store raw data
    """
    version = '0.1.0'

    def __init__(self, url, tag=None, cache=None):
        origin = url

        super().__init__(origin, tag=tag, cache=cache)
        self.url = url
        self.client = RSSClient(url)

    @metadata
    def fetch(self):
        """Fetch the entries from the url.

        The method retrieves all entries from a RSS url

        :returns: a generator of entries
        """

        logger.info("Looking for rss entries at feed '%s'", self.url)

        self._purge_cache_queue()
        nentries = 0  # number of entries

        raw_entries = self.client.get_entries()
        self._push_cache_queue(raw_entries)
        entries = self.parse_feed(raw_entries)['entries']
        self._flush_cache_queue()
        for item in entries:
            yield item
            nentries += 1

        logger.info("Total number of entries: %i", nentries)

    @classmethod
    def parse_feed(self, raw_entries):
        return feedparser.parse(raw_entries)

    @metadata
    def fetch_from_cache(self):
        """Fetch the entries from the cache.

        :returns: a generator of entries

        :raises CacheError: raised when an error occurs accessing the
            cache
        """
        if not self.cache:
            raise CacheError(cause="cache instance was not provided")

        cache_entries = next(self.cache.retrieve())
        entries = feedparser.parse(cache_entries)['entries']

        for item in entries:
            yield item

    @classmethod
    def has_caching(cls):
        """Returns whether it supports caching entries on the fetch process.

        :returns: this backend supports entries cache
        """
        return True

    @classmethod
    def has_resuming(cls):
        """Returns whether it supports to resume the fetch process.

        :returns: this backend does not supports entries resuming
        """
        return False

    @staticmethod
    def metadata_id(item):
        """Extracts the identifier from an entry item."""
        return str(item['link'])

    @staticmethod
    def metadata_updated_on(item):
        """Extracts the update time from a RSS item.

        The timestamp is extracted from 'published' field.
        This date is a datetime string that needs to be converted to
        a UNIX timestamp float value.

        :param item: item generated by the backend

        :returns: a UNIX timestamp
        """
        ts = str_to_datetime(item['published'])

        return ts.timestamp()

    @staticmethod
    def metadata_category(item):
        """Extracts the category from a RSS item.

        This backend only generates one type of item which is
        'entry'.
        """
        return 'entry'


class RSSClient:
    """RSS API client.

    This class implements a simple client to retrieve entries from
    projects in a RSS node.

    :param url: URL of rss node: https://item.opnfv.org/ci

    :raises HTTPError: when an error occurs doing the request
    """

    def __init__(self, url):
        self.url = url

    def get_entries(self):
        """ Retrieve all entries from a RSS feed"""

        req = requests.get(self.url)
        req.raise_for_status()
        return req.text


class RSSCommand(BackendCommand):
    """Class to run RSS backend from the command line."""

    def __init__(self, *args):
        super().__init__(*args)
        self.url = self.parsed_args.url
        self.tag = self.parsed_args.tag
        self.outfile = self.parsed_args.outfile

        if not self.parsed_args.no_cache:
            if not self.parsed_args.cache_path:
                base_path = os.path.expanduser('~/.perceval/cache/')
            else:
                base_path = self.parsed_args.cache_path

            cache_path = os.path.join(base_path, self.url)

            cache = Cache(cache_path)

            if self.parsed_args.clean_cache:
                cache.clean()
            else:
                cache.backup()
        else:
            cache = None

        self.backend = RSS(self.url, tag=self.tag, cache=cache)

    def run(self):
        """Fetch and print the entries.

        This method runs the backend to fetch the entries of a given url.
        entries are converted to JSON objects and printed to the
        defined output.
        """
        if self.parsed_args.fetch_cache:
            entries = self.backend.fetch_from_cache()
        else:
            entries = self.backend.fetch()

        try:
            for item in entries:
                obj = json.dumps(item, indent=4, sort_keys=True)
                self.outfile.write(obj)
                self.outfile.write('\n')
        except requests.exceptions.HTTPError as e:
            raise requests.exceptions.HTTPError(str(e.response.json()))
        except IOError as e:
            raise RuntimeError(str(e))
        except Exception as e:
            if self.backend.cache:
                self.backend.cache.recover()
            raise RuntimeError(str(e))

    @classmethod
    def create_argument_parser(cls):
        """Returns the RSS argument parser."""

        parser = super().create_argument_parser()

        # RSS options
        group = parser.add_argument_group('RSS arguments')

        # Required arguments
        group.add_argument('url',
                           help="URL of the RSS feed")

        return parser