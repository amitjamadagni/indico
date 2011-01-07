# -*- coding: utf-8 -*-
##
##
## This file is part of CDS Indico.
## Copyright (C) 2002, 2003, 2004, 2005, 2006, 2007 CERN.
##
## CDS Indico is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## CDS Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with CDS Indico; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

# plugin imports
from indico.ext.livesync.agent import PushSyncAgent

# legacy indico
from MaKaC import conference
from MaKaC.accessControl import AccessWrapper

# legacy OAI/XML libs - this should be replaced soon
from MaKaC.export.oai2 import DataInt
from MaKaC.common.xmlGen import XMLGen

# some useful constants
STATUS_DELETED, STATUS_CREATED, STATUS_CHANGED = 1, 2, 4


# Attention: if this class is not declared, the LiveSync management interface
# will never know this plugin exists!

class BistateRecordProcessor(object):

    @classmethod
    def _setStatus(cls, chgSet, obj, state):
        if obj not in chgSet:
            chgSet[obj] = 0

        chgSet[obj] |= state

    @classmethod
    def _breakDownCategory(cls, categ, chgSet, state):

        # categories are never converted to records

        for conf in categ.getAllConferenceList():
            cls._breakDownConference(conf, chgSet, state)

    @classmethod
    def _breakDownConference(cls, conf, chgSet, state):

        cls._setStatus(chgSet, conf, state)

        for contrib in conf.getContributionList():
            cls._breakDownContribution(contrib, chgSet, state)

    @classmethod
    def _breakDownContribution(cls, contrib, chgSet, state):

        cls._setStatus(chgSet, contrib, state)

        for scontrib in contrib.getSubContributionList():
            cls._setStatus(chgSet, scontrib, state)

    @classmethod
    def _computeProtectionChanges(cls, obj, action, chgSet):
        if isinstance(obj, conference.Category):
            cls._breakDownCategory(obj, chgSet, STATUS_CHANGED)
        elif isinstance(obj, conference.Conference):
            cls._breakDownConference(obj, chgSet, STATUS_CHANGED)
        elif isinstance(obj, conference.Contribution):
            cls._breakDownContribution(obj, chgSet, STATUS_CHANGED)
        elif isinstance(obj, conference.SubContribution):
            cls._setStatus(chgSet, obj, STATUS_CHANGED)

    @classmethod
    def computeRecords(cls, data, access):
        """
        Receives a sequence of ActionWrappers and returns a sequence
        of records to be updated (created, changed or deleted)
        """

        records = dict()

        for __, aw in data:
            obj = aw.getObject()

            if  isinstance(obj, conference.Category) or \
                   not obj.canAccess(AccessWrapper(access)):
                # category? no access? jump over this one
                continue

            if obj not in records:
                records[obj] = 0

            for action in aw.getActions():
                if action == 'deleted':
                    # if the record has been deleted, mark it as such
                    # nothing else will matter
                    records[obj] |= STATUS_DELETED

                elif action == 'created':
                    # if the record has been created, mark it as such
                    records[obj] |= STATUS_CREATED

                elif action in ['data_changed', 'acl_changed', 'moved']:
                    # categories are ignored
                    records[obj] |= STATUS_CHANGED

                elif action in ['set_private', 'set_public']:
                    # protection changes have to be handled more carefully
                    cls._computeProtectionChanges(obj, action, records)

        for record, state in records.iteritems():
            yield record, state


class BistateBatchUploaderAgent(PushSyncAgent):
    """
    Invenio WebUpload-compatible LiveSync agent
    """

    _creationState = STATUS_CREATED
    _extraOptions = {'url': 'Server URL'}

    def __init__(self, aid, name, description, updateTime,
                 access=None, url=None):
        super(BistateBatchUploaderAgent, self).__init__(
            aid, name, description, updateTime, access)
        self._url = url

    def _getMetadata(self, records):
        """
        Retrieves the MARCXML metadata for the record
        """
        xg = XMLGen()
        di = DataInt(xg)
        # set the permissions
        di.setPermissionsOf(self._access)

        xg.initXml()

        xg.openTag("collection", [["xmlns", "http://www.loc.gov/MARC21/slim"]])

        for record, operation in records:
            di.toMarc(record, overrideCache=True,
                      deleted=(operation & STATUS_DELETED))

        xg.closeTag("collection")

        return xg.getXml()

    def _generateRecords(self, data, lastTS):
        return BistateRecordProcessor.computeRecords(data, self._access)