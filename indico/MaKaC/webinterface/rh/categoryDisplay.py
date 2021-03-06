# -*- coding: utf-8 -*-
##
##
## This file is part of Indico.
## Copyright (C) 2002 - 2013 European Organization for Nuclear Research (CERN).
##
## Indico is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 3 of the
## License, or (at your option) any later version.
##
## Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Indico;if not, see <http://www.gnu.org/licenses/>.

from datetime import timedelta, datetime

#################################
# Fermi timezone awareness      #
#################################
from pytz import timezone
from MaKaC.common.timezoneUtils import nowutc, DisplayTZ
#################################
# Fermi timezone awareness(end) #
#################################
import MaKaC.webinterface.rh.base as base
from base import RoomBookingDBMixin
import MaKaC.webinterface.locators as locators
import MaKaC.webinterface.wcalendar as wcalendar
import MaKaC.webinterface.webFactoryRegistry as webFactoryRegistry
import MaKaC.webinterface.urlHandlers as urlHandlers
import MaKaC.webinterface.pages.category as category
import MaKaC.webinterface.displayMgr as displayMgr
from MaKaC.errors import MaKaCError,FormValuesError,NoReportError
import MaKaC.conference as conference
from MaKaC.conference import ConferenceChair
from MaKaC.common.general import *
import MaKaC.statistics as statistics
from MaKaC.common.Configuration import Config
import MaKaC.user as user
import MaKaC.common.info as info
from MaKaC.i18n import _
from MaKaC.webinterface.user import UserListModificationBase
from MaKaC.common.utils import validMail, setValidEmailSeparators
from MaKaC.common.mail import GenericMailer
from MaKaC.webinterface.common.tools import escape_html
from indico.web.http_api.api import CategoryEventHook
from indico.web.http_api.metadata.serializer import Serializer
from indico.web.wsgi import webinterface_handler_config as apache
from MaKaC.webinterface.common.tools import cleanHTMLHeaderFilename

class RHCategDisplayBase( base.RHDisplayBaseProtected ):

    def _checkProtection( self ):
        from MaKaC.webinterface.rh.collaboration import RCCollaborationAdmin, RCCollaborationPluginAdmin
        if not RCCollaborationAdmin.hasRights(self, None) and \
            not RCCollaborationPluginAdmin.hasRights(self, plugins = "any"):
            base.RHDisplayBaseProtected._checkProtection( self )

    def _checkParams( self, params, mustExist = 1 ):
        if "categId" in params:
            params["categId"] = escape_html(str(params["categId"]))
        l = locators.CategoryWebLocator( params, mustExist )
        self._target = l.getObject()

        # throw an error if the category was not found
        if mustExist and self._target == None:
            raise NoReportError(_("The specified category with id \"%s\" does not exist or has been deleted")%params["categId"])


class RHCategoryDisplay( RHCategDisplayBase ):
    _uh = urlHandlers.UHCategoryDisplay

    def _process( self ):

        wfReg = webFactoryRegistry.WebFactoryRegistry()
        p = category.WPCategoryDisplay( self, self._target, wfReg )
        return p.display()


class RHCategoryMap( RHCategDisplayBase ):
    _uh = urlHandlers.UHCategoryMap

    def _process( self ):
        p = category.WPCategoryMap( self, self._target )
        return p.display()

class RHCategoryStatistics( RHCategDisplayBase ):
    _uh = urlHandlers.UHCategoryStatistics

    def _process( self ):
        wfReg = webFactoryRegistry.WebFactoryRegistry()
        stats = statistics.CategoryStatistics(self._target).getStatistics()
        p = category.WPCategoryStatistics( self, self._target, wfReg, stats )
        return p.display()

class RHCategOverviewDisplay( RoomBookingDBMixin, RHCategDisplayBase ):

    def _checkParams( self, params ):
        id = params.get("selCateg", "")
        if id != "" and not params.has_key("categId"):
            params["categId"] = id
        RHCategDisplayBase._checkParams( self, params )
        if not self._target:
            raise MaKaCError( _("wrong category identifier"))
        tz = DisplayTZ(self._aw).getDisplayTZ()
        month = int( params.get("month", nowutc().astimezone(timezone(tz)).month) )
        year = int( params.get("year", nowutc().astimezone(timezone(tz)).year) )
        day = int( params.get("day", nowutc().astimezone(timezone(tz)).day) )
        sd = timezone(tz).localize(datetime( year, month, day ))
        period = params.get("period", "day")
        if period == "month":
            self._cal = wcalendar.MonthOverview( self._aw, sd, [self._target] )
        elif period == "week":
            self._cal = wcalendar.WeekOverview( self._aw, sd, [self._target] )
        elif period == "nextweek":
            self._cal = wcalendar.NextWeekOverview( self._aw, [self._target] )
        else:
            self._cal = wcalendar.Overview( self._aw, sd, [self._target] )
        self._cal.setDetailLevel( params.get("detail", "conference") )

    def _process( self ):
        p = category.WPCategOverview( self, self._target, self._cal )
        return p.display()

class RHConferenceCreationBase( RHCategoryDisplay ):

    def _checkProtection( self ):
        self._checkSessionUser()
        RHCategoryDisplay._checkProtection( self )
        if not self._target.isConferenceCreationRestricted():
            return
        if not self._target.canCreateConference( self._getUser() ):
            raise MaKaCError( _("You are not allowed to create conferences inside this category"))

    def _checkParams( self, params, mustExist=1 ):
        RHCategoryDisplay._checkParams( self, params, mustExist )
        #if self._target.getSubCategoryList():
        #    raise MaKaCError( _("Cannot add conferences to a category which already contains some sub-categories"))
        self._wf = None
        self._wfReg = webFactoryRegistry.WebFactoryRegistry()
        et = params.get("event_type", "").strip()
        if et != "" and et !="default":
            self._wf = self._wfReg.getFactoryById( et )


#-------------------------------------------------------------------------------------

class RHConferenceCreation( RoomBookingDBMixin, RHConferenceCreationBase ):
    _uh = urlHandlers.UHConferenceCreation

    def getCurrentURL( self ):
        url = self._uh.getURL(self._target)
        url.addParam("event_type", self._event_type)
        return url

    def _checkProtection( self ):
        try:
            RHConferenceCreationBase._checkProtection( self )
        except Exception:
            self._target = None

    def _checkParams( self, params ):
        self._params = params
        self._event_type = params.get("event_type", "").strip()
        RHConferenceCreationBase._checkParams( self, params, mustExist=0 )

    def _process( self ):

        if self._event_type == "":
            raise MaKaCError("No event type specified")
        else:
            p = category.WPConferenceCreationMainData( self, self._target )
            if self._wf != None:
                p = self._wf.getEventCreationPage( self, self._target )
            return p.display(**self._params)

#-------------------------------------------------------------------------------------

class RHConferencePerformCreation( RoomBookingDBMixin, RHConferenceCreationBase ):
    _uh = urlHandlers.UHConferencePerformCreation

    def _checkParams( self, params ):
        self._params =params
        RHConferenceCreationBase._checkParams( self, params )
        self._datecheck = False
        self._confirm = False
        self._performedAction = ""
        if "ok" in params:
            self._confirm = True
        return

    def _process( self ):
        params = self._getRequestParams()
        if params["title"]=="":
            params["title"]="No Title"
        # change number of dates (lecture)
        if self._confirm == True:
            if self._params.get("event_type","") != "simple_event":
                c = self._createEvent( self._params )
                self.alertCreation([c])
            # lectures
            else:
                lectures = []
                for i in range (1, int(self._params["nbDates"])+1):
                    self._params["sDay"] = self._params.get("sDay_%s"%i,"")
                    self._params["sMonth"] = self._params.get("sMonth_%s"%i,"")
                    self._params["sYear"] = self._params.get("sYear_%s"%i,"")
                    self._params["sHour"] = self._params.get("sHour_%s"%i,"")
                    self._params["sMinute"] = self._params.get("sMinute_%s"%i,"")
                    self._params["duration"] = int(self._params.get("dur_%s"%i,60))
                    lectures.append(self._createEvent(self._params))
                self.alertCreation(lectures)
                lectures.sort(sortByStartDate)
                # create links
                for i in range(0,len(lectures)):
                    lecture = lectures[i]
                    if len(lectures) > 1:
                        lecture.setTitle("%s (%s/%s)" % (lecture.getTitle(),i+1,len(lectures)))
                    for j in range(0,len(lectures)):
                        if j != i:
                            mat = conference.Material()
                            mat.setTitle("part%s"%(j+1))
                            url = str(urlHandlers.UHConferenceDisplay.getURL(lectures[j]))
                            link = conference.Link()
                            link.setURL(url)
                            link.setName(url)
                            mat.addResource(link)
                            lecture.addMaterial(mat)
                c = lectures[0]
            self._redirect(urlHandlers.UHConferenceModification.getURL( c ) )
        else :
            url = urlHandlers.UHCategoryDisplay.getURL(self._target)
            self._redirect(url)

    def _createEvent(self, params):
        c = self._target.newConference( self._getUser() )

        UtilsConference.setValues(c, self._params)

        if self._wf:
            self._wfReg.registerFactory( c, self._wf )

        eventAccessProtection = params.get("eventProtection", "inherit")

        if eventAccessProtection == "private" :
            c.getAccessController().setProtection(1)
        elif eventAccessProtection == "public" :
            c.getAccessController().setProtection(-1)

        avatars, newUsers, allowedAvatars = self._getPersons()
        UtilPersons.addToConf(avatars, newUsers, allowedAvatars, c, self._params.has_key('grant-manager'))
        if params.get("sessionSlots",None) is not None :
            if params["sessionSlots"] == "enabled" :
                c.enableSessionSlots()
            else :
                c.disableSessionSlots()

        return c

    def _getPersons(self):
        cpAvatars, cpNewUsers, auAvatars = [], [], []
        from MaKaC.services.interface.rpc import json
        chairpersonDict = json.decode(self._params.get("chairperson", []))
        allowedUsersDict = json.decode(self._params.get("allowedUsers", []))
        if chairpersonDict:
            cpAvatars, cpNewUsers, cpEditedAvatars = UserListModificationBase.retrieveUsers({"userList":chairpersonDict})
        if allowedUsersDict :
            auAvatars, auNewUsers, auEditedAvatars = UserListModificationBase.retrieveUsers({"userList":allowedUsersDict})
        #raise "avt: %s, newusers: %s, edited: %s"%(map(lambda x:x.getFullName(),avatars), newUsers, editedAvatars)

        return cpAvatars, cpNewUsers, auAvatars

    def alertCreation(self, confs):
        conf = confs[0]
        fromAddr = Config.getInstance().getSupportEmail()
        addrs = [ Config.getInstance().getSupportEmail() ]
        eventType = conf.getType()
        if eventType == "conference":
            type = "conference"
        elif eventType == "meeting":
            type = "meeting"
        else:
            type = "lecture"
        chair = ""
        if conf.getChairmanText() != "":
            chair = conf.getChairmanText()
        else:
            for c in conf.getChairList():
                chair += c.getFullName() + "; "
        subject = "New %s in indico (%s)" % (type,conf.getId())
        if conf.getRoom() != None:
            room = conf.getRoom().getName()
        else:
            room = ""
        text = """
_Category_
%s
_Title_
%s
_Speaker/Chair_
%s
_Room_
%s
_Description_
%s
_Creator_
%s (%s)"""%(conf.getOwner().getTitle(), conf.getTitle(), chair, room, conf.getDescription(), conf.getCreator().getFullName(), conf.getCreator().getId())
        if len(confs) == 1:
            text += """
_Date_
%s -> %s
_Access_
%s""" % ( conf.getAdjustedStartDate(), conf.getAdjustedEndDate(), urlHandlers.UHConferenceDisplay.getURL(conf))
        else:
            i = 1
            for c in confs:
                text += """
_Date%s_
%s -> %s
_Access%s_
%s """ % (i,c.getAdjustedStartDate(), c.getAdjustedEndDate(), i,urlHandlers.UHConferenceDisplay.getURL(c))
                i+=1

        msg = ("Content-Type: text/plain; charset=\"utf-8\"\r\nFrom: %s\r\nReturn-Path: %s\r\nTo: %s\r\nCc: \r\nSubject: %s\r\n\r\n"%(fromAddr, fromAddr, addrs, subject))
        msg = msg + text
        maildata = { "fromAddr": fromAddr, "toList": addrs, "subject": subject, "body": text }
        GenericMailer.send(maildata)
        # Category notification
        if conf.getOwner().getNotifyCreationList() != "":
            addrs2 = [ conf.getOwner().getNotifyCreationList() ]
            maildata2 = { "fromAddr": fromAddr, "toList": addrs2, "subject": subject, "body": text }
            GenericMailer.send(maildata2)


class UtilPersons:

    @staticmethod
    def addToConf( avatars, newUsers, accessingAvatars, conf, grantManager):

        if newUsers :
            for newUser in newUsers:
                person = ConferenceChair()
                person.setFirstName(newUser.get("firstName",""))
                person.setFamilyName(newUser.get("familyName",""))
                person.setEmail(newUser.get("email",""))
                person.setAffiliation(newUser.get("affiliation",""))
                person.setAddress(newUser.get("address",""))
                person.setPhone(newUser.get("telephone",""))
                person.setTitle(newUser.get("title",""))
                person.setFax(newUser.get("fax",""))
                if not UtilPersons._alreadyDefined(person) :
                    #TODO: add to conf
                    UtilPersons._addChair(conf, person, grantManager)
                else :
                    #self._errorList.append("%s has been already defined as %s of this conference"%(person.getFullName(),self._typeName))
                    pass

        if avatars:

            for selected in avatars :
                if isinstance(selected, user.Avatar) :
                    person = ConferenceChair()
                    person.setDataFromAvatar(selected)
                    if not UtilPersons._alreadyDefined(person):
                        #TODO: add to conf
                        UtilPersons._addChair(conf, person, grantManager)
                    else :
                        #self._errorList.append("%s has been already defined as %s of this conference"%(person.getFullName(),self._typeName))
                        pass

                #elif isinstance(selected, user.Group) :
                #    for member in selected.getMemberList() :
                #        person = ConferenceChair()
                #        person.setDataFromAvatar(member)
                #        if not self._alreadyDefined(person, definedList) :
                #            definedList.append([person,params.has_key("submissionControl")])
                #        else :
                #            self._errorList.append("%s has been already defined as %s of this conference"%(presenter.getFullName(),self._typeName))

        if accessingAvatars:
            for person in accessingAvatars :
                if isinstance(person, user.Avatar) or isinstance(person, user.Group) or isinstance(person, user.CERNGroup):
                    conf.grantAccess(person)

    @staticmethod
    def _alreadyDefined(person):#, definedList):
        #if person is None :
        #    return True
        #if definedList is None :
        #    return False
        #fullName = person.getFullName()
        #for p in definedList :
        #    if p[0].getFullName() == fullName :
        #        return True
        return False

    @staticmethod
    def _addChair(conf, chair, grant):
        conf.addChair(chair)
        if grant:
            conf.grantModification(chair)

class UtilsConference:

    def setValues(c, confData, notify=False):
        from MaKaC.webinterface.common.tools import escape_tags_short_url
        c.setTitle( confData["title"] )
        c.setDescription( confData["description"] )
        c.setOrgText(confData.get("orgText",""))
        c.setComments(confData.get("comments",""))
        c.setKeywords( confData["keywords"] )
        c.setChairmanText( confData.get("chairText", "") )
        if "shortURLTag" in confData.keys():
            tag = confData["shortURLTag"].strip()
            tag = escape_tags_short_url(tag)
            if c.getUrlTag() != tag:
                from MaKaC.common.url import ShortURLMapper
                sum = ShortURLMapper()
                sum.remove(c)
                c.setUrlTag(tag)
                if tag:
                    sum.add(tag, c)
        c.setContactInfo( confData.get("contactInfo","") )
        #################################
        # Fermi timezone awareness      #
        #################################
        c.setTimezone(confData["Timezone"])
        tz = confData["Timezone"]
        try:
            sDate = timezone(tz).localize(datetime(int(confData["sYear"]), \
                                 int(confData["sMonth"]), \
                                 int(confData["sDay"]), \
                                 int(confData["sHour"]), \
                                 int(confData[ "sMinute"])))
        except ValueError,e:
            raise FormValuesError("The start date you have entered is not correct: %s"%e, "Event")

        if confData.get("duration","") != "":
            eDate = sDate + timedelta(minutes=confData["duration"])
        else:
            try:
                eDate = timezone(tz).localize(datetime(   int(confData["eYear"]), \
                                     int(confData["eMonth"]), \
                                     int(confData["eDay"]), \
                                     int(confData["eHour"]), \
                                     int(confData[ "eMinute"])))
            except ValueError,e:
                raise FormValuesError("The end date you have entered is not correct: %s"%e)
        moveEntries = int(confData.get("move",0))
        c.setDates( sDate.astimezone(timezone('UTC')), \
                    eDate.astimezone(timezone('UTC')), moveEntries=moveEntries)

        #################################
        # Fermi timezone awareness(end) #
        #################################
        changed = False
        newLocation = confData.get("locationName","")
        newRoom = confData.get( "locationBookedRoom" )  or  \
                   confData.get( "roomName" )  or  ""

        if newLocation.strip() == "":
            c.setLocation( None )
        else:
            l = c.getLocation()
            if not l:
                l = conference.CustomLocation()
                c.setLocation( l )

            if l.getName() != newLocation:
                l.setName(newLocation)
                changed = True

            l.setAddress( confData.get("locationAddress","") )

        if newRoom.strip() == "":
            c.setRoom( None )
        else:
            r = c.getRoom()
            if not r:
                r = conference.CustomRoom()
                c.setRoom( r )

            if r.getName() != newRoom:
                r.setName(newRoom)
                r.retrieveFullName(newLocation)
                changed = True

        if changed:
            c._notify('placeChanged')

        emailstr = setValidEmailSeparators(confData.get("supportEmail", ""))

        if (emailstr != "") and not validMail(emailstr):
            raise FormValuesError("One of the emails specified or one of the separators is invalid")

        c.getSupportInfo().setEmail(emailstr)
        c.getSupportInfo().setCaption(confData.get("supportCaption","Support"))
        displayMgr.ConfDisplayMgrRegistery().getDisplayMgr(c).setDefaultStyle(confData.get("defaultStyle",""))
        if c.getVisibility() != confData.get("visibility",999):
            c.setVisibility( confData.get("visibility",999) )
        curType = c.getType()
        newType = confData.get("eventType","")
        if newType != "" and newType != curType:
            wr = webFactoryRegistry.WebFactoryRegistry()
            factory = wr.getFactoryById(newType)
            wr.registerFactory(c,factory)
            dispMgr = displayMgr.ConfDisplayMgrRegistery().getDisplayMgr(c)
            styleMgr = info.HelperMaKaCInfo.getMaKaCInfoInstance().getStyleManager()
            dispMgr.setDefaultStyle(styleMgr.getDefaultStyleForEventType(newType))
    setValues = staticmethod( setValues )


class RHCategoryGetIcon(RHCategDisplayBase):

    def _checkProtection( self ):
        # Since the object of the request is the icon, and not
        # the conference, we do a first check for the icon
        icon = self._target.getIcon()
        if icon.canAccess( self.getAW() ):
            return
        else:
            RHCategDisplayBase._checkProtection(self)


    def _process(self):
        icon=self._target.getIcon()
        self._req.headers_out["Content-Length"]="%s"%icon.getSize()
        cfg=Config.getInstance()
        mimetype=cfg.getFileTypeMimeType(icon.getFileType())
        self._req.content_type="""%s"""%(mimetype)
        self._req.headers_out["Content-Disposition"]="""inline; filename="%s\""""%icon.getFileName()
        return self._target.getIcon().readBin()

class RHCategoryToiCal(RoomBookingDBMixin, RHCategDisplayBase):

    def _process( self ):
        filename = "%s-Categ.ics"%self._target.getName().replace("/","")

        hook = CategoryEventHook({}, 'categ', {'idlist':self._target.getId(), 'dformat': 'ics'})
        res = hook(self.getAW(), self._req)
        resultFossil = {'results': res[0]}

        serializer = Serializer.create('ics')
        data = serializer(resultFossil)

        self._req.headers_out["Content-Length"] = "%s"%len(data)
        cfg = Config.getInstance()
        mimetype = cfg.getFileTypeMimeType( "ICAL" )
        self._req.content_type = """%s"""%(mimetype)
        self._req.headers_out["Content-Disposition"] = """inline; filename="%s\""""%cleanHTMLHeaderFilename(filename)

        return data

class RHCategoryToRSS(RHCategDisplayBase):

    def _process (self):
        self._redirect(urlHandlers.UHCategoryToAtom.getURL(self._target), status=apache.HTTP_MOVED_PERMANENTLY)

class RHTodayCategoryToRSS(RHCategoryToRSS):

    def _process( self ):
        self._redirect(urlHandlers.UHCategoryToAtom.getURL(self._target), status=apache.HTTP_MOVED_PERMANENTLY)

class RHCategoryToAtom(RoomBookingDBMixin, RHCategDisplayBase):
    _uh = urlHandlers.UHCategoryToAtom

    def _process( self ):

        hook = CategoryEventHook({'from': ['today']}, 'categ', {'idlist':self._target.getId(), 'dformat': 'atom'})
        res = hook(self.getAW(), self._req)
        resultFossil = {'results': res[0], 'url': str(self._uh.getURL(self._target))}

        serializer = Serializer.create('atom')
        data = serializer(resultFossil)

        cfg = Config.getInstance()
        mimetype = cfg.getFileTypeMimeType( "ATOM" )
        self._req.content_type = """%s"""%(mimetype)

        return data


def sortByStartDate(conf1,conf2):
    return cmp(conf1.getStartDate(),conf2.getStartDate())

