# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 Georges Toth <georges _at_ trypill _dot_ org>
#
# This file is part of MeMaTool.
#
# MeMaTool is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MeMaTool is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with MeMaTool.  If not, see <http://www.gnu.org/licenses/>.

import logging

import ldap
from mematool.model.baseModelFactory import BaseModelFactory
from mematool.model.dbmodel import Group
from mematool.model.ldapmodel import Member, Domain, Alias
from mematool import Config
from mematool.helpers.exceptions import EntryExists


log = logging.getLogger(__name__)


class LdapModelFactory(BaseModelFactory):
  def __init__(self, ldapcon):
    super(LdapModelFactory, self).__init__()
    self.ldapcon = ldapcon

  def close(self):
    '''Close LDAP connection'''
    self.ldapcon = None

  def getUser(self, uid, clear_credentials=False):
    '''
    Return a Member object populated with it's attributes loaded from LDAP

    :param uid: LDAP UID
    :type uid: string
    :returns: Member
    '''
    filter_ = '(uid=' + uid + ')'
    attrs = ['*']
    basedn = 'uid=' + str(uid) + ',' + str(Config.get('ldap', 'basedn_users'))

    result = self.ldapcon.search_s(basedn, ldap.SCOPE_SUBTREE, filter_, attrs)

    if not result:
      raise LookupError('No such user !')

    m = Member()

    for dn, attr in result:
      for k, v in attr.iteritems():
        if 'objectClass' in k:
          # @TODO ignore for now
          continue

        # @TODO handle multiple results
        v = v[0]

        # @todo:  why again do we still need this ?
        if k == 'sambaSID' and v == '':
          v = None

        m.set_property(k, v)

    if clear_credentials:
      m.sambaNTPassword = '******'
      m.userPassword = '******'

    m.groups = self.getUserGroupList(uid)

    return m

  def getUserList(self):
    '''Get a list of all users belonging to the group "users" (gid-number = 100)
    and having a uid-number >= 1000 and < 65000'''
    filter = '(&(uid=*)(gidNumber=100))'
    attrs = ['uid', 'uidNumber']
    users = []

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_users'), ldap.SCOPE_SUBTREE, filter, attrs)

    for dn, attr in result:
      if int(attr['uidNumber'][0]) >= 1000 and int(attr['uidNumber'][0]) < 65000:
        users.append(attr['uid'][0])

    users.sort()

    return users

  def getActiveMemberList(self):
    '''Get a list of members not belonging to the locked-members group'''
    users = []

    for u in self.getUserList():
      if not self.isUserInGroup(u, Config.get('mematool', 'group_lockedmember')):
        users.append(u)

    return users

  def getUserGroupList(self, uid):
    '''Get a list of groups a user is a member of'''
    filter = '(memberUid=' + uid + ')'
    attrs = ['cn']
    groups = []

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_groups'), ldap.SCOPE_SUBTREE, filter, attrs)

    for dn, attr in result:
      for key, value in attr.iteritems():
        if len(value) == 1:
          groups.append(value[0])
        else:
          for i in value:
            groups.append(i)

    return groups

  def getHighestUidNumber(self):
    '''Get the highest used uid-number
    this is used when adding a new user'''
    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_users'), ldap.SCOPE_SUBTREE, Config.get('ldap', 'uid_filter'), [Config.get('ldap', 'uid_filter_attrs')])

    uidNumber = -1

    for dn, attr in result:
      for key, value in attr.iteritems():
        if int(value[0]) > uidNumber and int(value[0]) < 65000:
          uidNumber = int(value[0])

    uidNumber += 1

    return str(uidNumber)

  def getUidNumberFromUid(self, uid):
    '''Get a UID-number based on its UID'''
    filter = '(uid=' + uid + ')'
    attrs = ['uidNumber']

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_users'), ldap.SCOPE_SUBTREE, filter, attrs)

    if not result:
      raise LookupError('No such user !')

    for dn, attr in result:
      uidNumber = attr['uidNumber'][0]

    return uidNumber

  def prepareVolatileAttribute(self, member, oldmember=None, attribute=None, encoding='utf-8'):
    '''Checks if an attribute is present in the member object and
    whether it should be updated or else deleted.
    While doing that it converts the attribute value to the specified
    encoding, which by default is UTF-8
    Returns None if the attribute it not present or nothing should be
    changed'''
    retVal = None

    if hasattr(member, attribute):
      a = getattr(member, attribute)

    if isinstance(a, bool) or (a and not a is None and a != ''):
      ''' be careful with bool attributes '''
      if isinstance(a, bool):
        a = str(a).upper()
      else:
        if not encoding is None:
          a = str(a.encode(encoding, 'ignore'))

      if oldmember and hasattr(oldmember, attribute) and not getattr(oldmember, attribute) is None and not getattr(oldmember, attribute) == '':
        # @FIXME UnicodeWarning: Unicode equal comparison failed to convert both arguments to Unicode - interpreting them as being unequal
        #   if not a == getattr(oldmember, attribute):
        if not a == getattr(oldmember, attribute):
          retVal = (ldap.MOD_REPLACE, attribute, a)
      else:
        if not oldmember is None:
          retVal = (ldap.MOD_ADD, attribute, a)
        else:
          retVal = (attribute, [a])
    else:
      if oldmember and hasattr(oldmember, attribute) and not getattr(oldmember, attribute) is None and not getattr(oldmember, attribute) == '':
        retVal = (ldap.MOD_DELETE, attribute, None)

    return retVal

  def _updateMember(self, member, is_admin=True):
    mod_attrs = []
    om = self.getUser(member.uid)

    if is_admin:
      for k in member.auto_update_vars:
        mod_attrs.append(self.prepareVolatileAttribute(member, om, k))

    if member.userPassword and member.userPassword != '':
      mod_attrs.append((ldap.MOD_REPLACE, 'userPassword', str(member.userPassword)))
      if member.sambaNTPassword and member.sambaNTPassword != '':
        mod_attrs.append((ldap.MOD_REPLACE, 'sambaNTPassword', str(member.sambaNTPassword)))

    while None in mod_attrs:
      mod_attrs.remove(None)

    dn = 'uid={0},{1}'.format(member.uid, Config.get('ldap', 'basedn_users'))
    result = self.ldapcon.modify_s(dn, mod_attrs)

    diff = lambda l1,l2: [x for x in l1 if x not in l2]
    to_disable_groups = diff(om.groups, member.groups)
    to_enable_groups = diff(member.groups, om.groups)
      
    for g in to_disable_groups:
      self.changeUserGroup(member.uid, g, False)
    for g in to_enable_groups:
      self.changeUserGroup(member.uid, g, True)

    print om.groups
    print member.groups

    return result

  def _addMember(self, member):
    '''Add a new user'''
    member.uidNumber = self.getHighestUidNumber()
    member.generateUserSID()

    mod_attrs = []

    mod_attrs.append(('objectclass', ['posixAccount', 'organizationalPerson', 'inetOrgPerson', 'shadowAccount', 'top', 'samsePerson', 'sambaSamAccount', 'ldapPublicKey', 'syn2catPerson']))
    mod_attrs.append(('ou', ['People']))

    for k in member.auto_update_vars:
      mod_attrs.append(self.prepareVolatileAttribute(member, None, k))

    for k in member.no_auto_update_vars:
      if not k == 'jpegPhoto':
        mod_attrs.append(self.prepareVolatileAttribute(member, None, k))

    while None in mod_attrs:
      mod_attrs.remove(None)

    dn = 'uid=' + member.uid + ',' + Config.get('ldap', 'basedn_users')
    dn = dn.encode('ascii', 'ignore')
    result = self.ldapcon.add_s(dn, mod_attrs)

    self.changeUserGroup(member.uid, Config.get('mematool', 'group_fullmember'), member.fullMember)
    self.changeUserGroup(member.uid, Config.get('mematool', 'group_lockedmember'), member.lockedMember)

    return result

  def deleteUser(self, uid):
    filter_ = '(uid=' + uid + ')'
    attrs = ['*']
    basedn = 'uid=' + str(uid) + ',' + str(Config.get('ldap', 'basedn_users'))

    result = self.ldapcon.search_s(basedn, ldap.SCOPE_SUBTREE, filter_, attrs)

    if not result:
      raise LookupError('No such user !')

    # remove user from all groups
    groups = self.getUserGroupList(uid)
    for k in groups:
      #print 'removing from group {0}'.format(k)
      self.changeUserGroup(uid, k, False)

    # try to auto-delete aliases
    aliases = self.getMaildropList(uid)
    for dn, attr in aliases.items():
      if len(attr) > 1:
        #print 'removing user {0} from alias {1}'.format(uid, dn)
        self.deleteMaildrop(dn, uid)
      else:
        print 'can\'t remove user {0} from alias {1}'.format(uid, dn)

    # finally, remove the user
    result = self.ldapcon.delete_s(basedn)

  def changeUserGroup(self, uid, group, status):
    '''Change user/group membership'''
    '''@TODO check and fwd return value'''
    mod_attrs = []
    result = ''
    m = self.getUser(uid)

    if status and not group in m.groups:
      mod_attrs = [(ldap.MOD_ADD, 'memberUid', uid.encode('ascii', 'ignore'))]
    elif not status and group in m.groups:
      mod_attrs = [(ldap.MOD_DELETE, 'memberUid', uid.encode('ascii', 'ignore'))]

    if len(mod_attrs) == 1:
      try:
        result = self.ldapcon.modify_s('cn=' + group.encode('ascii', 'ignore') + ',' + Config.get('ldap', 'basedn_groups'), mod_attrs)
      except (ldap.TYPE_OR_VALUE_EXISTS, ldap.NO_SUCH_ATTRIBUTE):
        pass
      except Exception as e:
        # @todo: implement better handling
        print e
        pass

    return result

  def updateAvatar(self, member, b64_jpg):
    mod_attrs = []
    om = self.getUser(member.uid)

    member.jpegPhoto = b64_jpg
    mod_attrs.append(self.prepareVolatileAttribute(member, om, 'jpegPhoto', encoding=None))

    while None in mod_attrs:
      mod_attrs.remove(None)

    result = self.ldapcon.modify_s('uid=' + member.uid + ',' + Config.get('ldap', 'basedn_users'), mod_attrs)

    return result

  def getGroup(self, gid):
    ''' Get a specific group'''
    filter = '(cn=' + gid + ')'
    attrs = ['*']

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_groups'), ldap.SCOPE_SUBTREE, filter, attrs)

    if not result:
      raise LookupError('No such group !')

    g = Group()
    g.users = []
    for dn, attr in result:
      for k, v in attr.iteritems():
        if 'cn' in k:
          k = 'gid'

        if 'memberUid' in k:
          for m in v:
            g.users.append(m)
        else:
          v = v[0]
          setattr(g, k, v)

    return g

  def getGroupList(self):
    '''Get a list of all groups'''
    filter = '(cn=*)'
    attrs = ['cn', 'gidNumber']

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_groups'), ldap.SCOPE_SUBTREE, filter, attrs)
    groups = []

    for dn, attr in result:
      groups.append(attr['cn'][0])

    return groups

  def getGroupMembers(self, group):
    '''Get all members of a specific group'''
    filter = '(cn=' + group + ')'
    attrs = ['memberUid']

    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_groups'), ldap.SCOPE_SUBTREE, filter, attrs)

    if not result:
      raise LookupError('No such group !')

    members = []

    for dn, attr in result:
      for key, value in attr.iteritems():
        if len(value) == 1:
          members.append(value[0])
        else:
          for i in value:
            members.append(i)

    return members

  def addGroup(self, gid):
    '''Add a new group'''
    if super(LdapModelFactory, self).addGroup(gid):
      gl = self.getGroupList()

      if not gid in gl:
        g = Group()
        g.gid = gid
        g.gidNumber = self.getHighestGidNumber()
        mod_attrs = []

        mod_attrs.append(('objectClass', ['top', 'posixGroup']))

        mod_attrs.append(self.prepareVolatileAttribute(g, None, 'cn'))
        mod_attrs.append(self.prepareVolatileAttribute(g, None, 'gidNumber'))

        while None in mod_attrs:
          mod_attrs.remove(None)

        dn = 'cn=' + gid + ',' + Config.get('ldap', 'basedn_groups')
        dn = dn.encode('ascii', 'ignore')
        result = self.ldapcon.add_s(dn, mod_attrs)

        if result is None:
          return False

      return True

    return False

  def deleteGroup(self, gid):
    '''Completely remove a group'''
    dn = 'cn=' + gid + ',' + Config.get('ldap', 'basedn_groups')
    dn = dn.encode('ascii', 'ignore')
    retVal = self.ldapcon.delete_s(dn)

    if not retVal is None and super(LdapModelFactory, self).deleteGroup(gid):
      return True

    return False

  def getHighestGidNumber(self):
    '''Get the highest used gid-number
    this is used when adding a new group'''
    result = self.ldapcon.search_s(Config.get('ldap', 'basedn_groups'), ldap.SCOPE_SUBTREE, Config.get('ldap', 'gid_filter'), [Config.get('ldap', 'gid_filter_attrs')])

    gidNumber = -1

    for dn, attr in result:
      for key, value in attr.iteritems():
        if int(value[0]) > gidNumber and int(value[0]) < 65000:
          gidNumber = int(value[0])

    gidNumber += 1

    return str(gidNumber)

  def addDomain(self, domain):
    '''Add a new domain'''
    dl = self.getDomainList()

    if not domain in dl:
      d = Domain()
      d.dc = domain
      mod_attrs = []

      mod_attrs.append(('objectClass', ['top', 'domain', 'mailDomain']))
      mod_attrs.append(self.prepareVolatileAttribute(d, None, 'dc'))

      while None in mod_attrs:
        mod_attrs.remove(None)

      dn = 'dc=' + domain + ',' + Config.get('ldap', 'basedn')
      dn = dn.encode('ascii', 'ignore')
      result = self.ldapcon.add_s(dn, mod_attrs)

      if result is None:
        return False

      return True

    return False

  def deleteDomain(self, domain):
    '''Completely remove a domain'''
    dl = self.getDomainList()

    if domain in dl:
      dn = 'dc=' + domain + ',' + Config.get('ldap', 'basedn')
      dn = dn.encode('ascii', 'ignore')
      retVal = self.ldapcon.delete_s(dn)

      if not retVal is None:
        return True
    else:
      raise LookupError('No such domain!')

    return False

  def getDomain(self, domain):
    filter_ = '(objectClass=mailDomain)'
    attrs = ['*']
    basedn = 'dc=' + str(domain) + ',' + str(Config.get('ldap', 'basedn'))

    result = self.ldapcon.search_s(basedn, ldap.SCOPE_BASE, filter_, attrs)

    if not result:
      raise LookupError('No such domain !')

    d = Domain()

    for dn, attr in result:
      for k, v in attr.iteritems():
        if 'objectClass' in k:
          # @TODO ignore for now
          continue

        # @TODO handle multiple results
        v = v[0]

        setattr(d, k, v)

    return d

  def getDomainList(self):
    result = self.ldapcon.search_s(Config.get('ldap', 'basedn'), ldap.SCOPE_SUBTREE, Config.get('ldap', 'domain_filter'), [Config.get('ldap', 'domain_filter_attrs')])

    domains = []

    for dn, attr in result:
      for key, value in attr.iteritems():
        if len(value) == 1:
          domains.append(value[0])
        else:
          for i in value:
            domains.append(i)

    return domains

  def getAlias(self, alias):
    filter_ = '(&(objectClass=mailAlias)(mail=' + str(alias) + '))'
    attrs = ['*']
    basedn = str(Config.get('ldap', 'basedn'))
    result = self.ldapcon.search_s(basedn, ldap.SCOPE_SUBTREE, filter_, attrs)

    if not result:
      raise LookupError('No such alias !')

    a = Alias()
    a.dn_mail = alias

    for dn, attr in result:
      for k, v in attr.iteritems():
        if 'objectClass' in k:
          # @TODO ignore for now
          continue
        elif k == 'mail':
          if len(v) == 1:
            a.mail.append(v[0])
          else:
            for i in v:
              a.mail.append(i)

          continue
        elif k == 'maildrop':
          if len(v) == 1:
            a.maildrop.append(v[0])
          else:
            for i in v:
              a.maildrop.append(i)

          continue
        else:
          # @TODO handle multiple results
          v = v[0]

          setattr(a, k, v)

    return a

  def getAliasList(self, domain):
    filter_ = 'objectClass=mailAlias'
    attrs = ['']
    basedn = 'dc=' + str(domain) + ',' + str(Config.get('ldap', 'basedn'))
    result = self.ldapcon.search_s(basedn, ldap.SCOPE_SUBTREE, filter_, attrs)

    aliases = []

    for dn, attr in result:
      dn_split = dn.split(',')
      a = dn_split[0].split('=')[1]

      aliases.append(a)

    return aliases

  def getMaildropList(self, uid):
    '''This returns all aliases which have as maildrop the specified uid'''
    filter_ = '(&(objectClass=mailAlias)(maildrop={0}))'.format(uid)
    attrs = ['maildrop']
    basedn = str(Config.get('ldap', 'basedn'))
    result = self.ldapcon.search_s(basedn, ldap.SCOPE_SUBTREE, filter_, attrs)

    aliases = {}

    if not result:
      return aliases

    for dn, attr in result:
      if not dn in aliases:
        aliases[dn] = []

      for a in attr['maildrop']:
        aliases[dn].append(a)

    return aliases

  def addAlias(self, alias):
    try:
      oldalias = self.getAlias(alias.dn_mail)

      raise EntryExists('Alias already exists!')
    except:
      mod_attrs = []
      mod_attrs.append(('objectClass', ['mailAlias']))

      mail = []
      for m in alias.mail:
        mail.append(str(m.encode('utf-8', 'ignore')))

      if len(mail) > 0:
        mod_attrs.append(('mail', mail))

      maildrop = []
      for m in alias.maildrop:
        maildrop.append(str(m.encode('utf-8', 'ignore')))

      if len(maildrop) > 0:
        mod_attrs.append(('maildrop', maildrop))

      while None in mod_attrs:
        mod_attrs.remove(None)

      dn = 'mail=' + alias.dn_mail + ',dc=' + alias.domain + ',' + Config.get('ldap', 'basedn')
      dn = dn.encode('ascii', 'ignore')

      try:
        result = self.ldapcon.add_s(dn, mod_attrs)
      except ldap.ALREADY_EXISTS:
        raise EntryExists('Alias already exists!')

      if result is None:
        return False

      return True

    return False

  def updateAlias(self, alias):
    # @FIXME https://github.com/sim0nx/mematool/issues/1
    oldalias = self.getAlias(alias.dn_mail)
    mod_attrs = []

    for m in alias.mail:
      if m == alias.dn_mail:
        continue

      found = False
      for n in oldalias.mail:
        if m == n:
          found = True
          break

      if not found:
        mod_attrs.append((ldap.MOD_ADD, 'mail', m.encode('ascii', 'ignore')))

    for m in oldalias.mail:
      if m == oldalias.dn_mail:
        continue

      found = False
      for n in alias.mail:
        if m == n:
          found = True
          break

      if not found:
        mod_attrs.append((ldap.MOD_DELETE, 'mail', m.encode('ascii', 'ignore')))

    for m in alias.maildrop:
      if m == alias.dn_mail:
        continue

      found = False
      for n in oldalias.maildrop:
        if m == n:
          found = True
          break

      if not found:
        mod_attrs.append((ldap.MOD_ADD, 'maildrop', m.encode('ascii', 'ignore')))

    for m in oldalias.maildrop:
      if m == oldalias.dn_mail:
        continue

      found = False
      for n in alias.maildrop:
        if m == n:
          found = True
          break

      if not found:
        mod_attrs.append((ldap.MOD_DELETE, 'maildrop', m.encode('ascii', 'ignore')))

    while None in mod_attrs:
      mod_attrs.remove(None)

    # nothing to do
    if len(mod_attrs) == 0:
      return True

    dn = alias.getDN(Config.get('ldap', 'basedn')).encode('ascii', 'ignore')

    result = self.ldapcon.modify_s(dn, mod_attrs)

    if result is None:
      return False

    return True

  def deleteMaildrop(self, alias, uid):
    mod_attrs = []
    mod_attrs.append((ldap.MOD_DELETE, 'maildrop', uid.encode('ascii', 'ignore')))

    result = self.ldapcon.modify_s(alias, mod_attrs)

    if result is None:
      return False

    return True

  def deleteAlias(self, alias):
    '''Completely remove an alias'''

    a = self.getAlias(alias)
    dn = a.getDN(Config.get('ldap', 'basedn')).encode('ascii', 'ignore')
    retVal = self.ldapcon.delete_s(dn)

    if not retVal is None:
      return True

    return False
