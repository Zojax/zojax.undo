##############################################################################
#
# Copyright (c) 2009 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
from zope.security.proxy import removeSecurityProxy
"""

$Id$
"""
import cgi
import sys
import logging
import pytz

import transaction

from zope import interface, schema, component
from zope.location import Location
from zope.component import getUtility, getMultiAdapter, queryMultiAdapter
from zope.session.interfaces import ISession
from zope.app.intid.interfaces import IIntIds
from zope.traversing.browser import absoluteURL
from zope.dublincore.interfaces import IDCTimes
from zope.app.undo.browser import UndoView
from zope.app.undo.interfaces import IUndoManager
from zope.app.component.hooks import getSite
from zope.datetime import parseDatetimetz

from zojax.layoutform import Fields, PageletEditForm, button
from zojax.wizard.interfaces import ISaveable
from zojax.wizard.step import WizardStepForm
from zojax.catalog.interfaces import ICatalog
from zojax.batching.session import SessionBatch
from zojax.ownership.interfaces import IOwnership
from zojax.content.type.interfaces import IItem, IContentViewView, IContentType
from zojax.content.table.author import AuthorColumn
from zojax.content.table.times import TimesColumn
from zojax.content.table.interfaces import IContentsTable
from zojax.table.table import Table
from zojax.table.column import Column
from zojax.table.interfaces import IDataset
from zojax.table.column import Column
from zojax.pageelement.interfaces import IPageElement
from zojax.principal.profile.interfaces import IPersonalProfile
from zojax.statusmessage.interfaces import IStatusMessage

from zojax.undo.interfaces import _, IUndo
from zojax.undo import undoSetup

SESSIONKEY = u'zojax.undo'
logger = logging.getLogger('zojax.undo')


class ISearchForm(interface.Interface):

    searchableText = schema.TextLine(
        title = u'Searchable text',
        required = False)


class UndoContent(WizardStepForm, UndoView):

    fields = Fields(ISearchForm)

    def applyChanges(self, data):
        session = ISession(self.request)
        session[SESSIONKEY]['params'] = data
        return True

    def getContent(self):
        session = ISession(self.request)
        return session[SESSIONKEY].get('params', {})

    @button.buttonAndHandler(_(u'Undo'), name='undo')
    def handleUndo(self, action):
        data, errors = self.extractData()
        ids = self.request.get('ids', [])
        if errors:
            IStatusMessage(self.request).add(self.formErrorsMessage, 'warning')
        elif not ids:
            IStatusMessage(self.request).add(_(u'You must select transactions'), 'warning')
        else:
            try:
                self.undoAllTransactions(ids)
                IStatusMessage(self.request).add(_(u'Selected transactions has been undoed'))
            except Exception, e:
                logger.warning('Error upon undo:', exc_info=True)
                IStatusMessage(self.request).add(_(u'Error upon undo: %s' % e), 'warning')
            self.redirect(self.request.getURL())


class UndoContentsTable(Table):
    component.adapts(interface.Interface, interface.Interface, interface.Interface)

    pageSize = 20
    enabledColumns = ('id', 'location', 'request', 'date', 'description', 'author', 'size')
    msgEmptyTable = _('No undo content.')
    sessionBatch = False


class UndoContentsDataset(object):

    interface.implements(IDataset)

    def __init__(self, context, table):
        self.context, self.table = context, table
        self.showall =  bool(self.table.request.get('showall'))

    def __getslice__(self, i, j):
        """ data slice """
        class ev(object):

            def __init__(self, db):
                self.database = db
        #undoSetup(ev(removeSecurityProxy(self.context)._p_jar._db))
        return self.table.view.getAllTransactions(i, -(j-i), showall=self.showall)

    def __len__(self):
        return sys.maxint


class DescriptionColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'description'
    title = _('Description')
    cssClass = 'ctb-description'

    def query(self, default=None):
        return self.content.get('description', _(u'[No description]'))


class SizeColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'size'
    title = _('Size')
    cssClass = 'ctb-size'

    def query(self, default=None):
        return self.content.get('size', _(u'[No size]'))


class LocationColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'location'
    title = _('Location')
    cssClass = 'ctb-location'

    def query(self, default=None):
        return self.content.get('location', _(u'[Unknown]'))

    def render(self):
        value = self.query()
        return u'<a href="%s">%s<a>'%(
            value, cgi.escape(value))


class LocationColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'location'
    title = _('Location')
    cssClass = 'ctb-location'

    def query(self, default=None):
        return self.content.get('location', _(u'[Unknown]'))

    def render(self):
        value = self.query()
        return u'<a href="%s">%s<a>'%(
            value, cgi.escape(value))


class RequestColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'request'
    title = _('Request')
    cssClass = 'ctb-request'

    def query(self, default=None):
        return self.content.get('request_info', _(u'[Unknown]'))


class AuthorColumn(AuthorColumn):

    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    title = _('Author')

    def getPrincipal(self, content):
        return content['principal']


class DateColumn(TimesColumn):

    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    name = 'date'
    title = _('Date')
    cssClass = 'ctb-date'

    def query(self, default=None):
        return parseDatetimetz(str(self.content.get('datetime'))).astimezone(pytz.utc)


class IdColumn(Column):
    component.adapts(interface.Interface, interface.Interface, UndoContentsTable)

    weight = 0
    name = 'id'
    cssClass = 'z-table-cell-min'

    def query(self, default=None):
        return self.content['id']

    def update(self):
        super(IdColumn, self).update()

        self.table.environ['activeIds'] = self.request.get('ids', ())

    def render(self):
        value = self.query()
        ids = self.globalenviron['activeIds']
        return u'<input type="checkbox" name="ids:list" value="%s" %s/>'%(
            cgi.escape(value), value in ids and u'checked="yes"' or u'')
