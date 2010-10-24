#
#    MeMaTool (c) 2010 Georges Toth <georges _at_ trypill _dot_ org>
#
#
#    This file is part of MeMaTool.
#
#
#    MeMaTool is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Foobar is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with MeMaTool.  If not, see <http://www.gnu.org/licenses/>.


from sqlalchemy import schema, types, orm, create_engine, Table, Column, Integer, String, MetaData, ForeignKey, Boolean, DateTime, ForeignKeyConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relation

from mematool.model.meta import Base
from mematool.lib.base import Session

class Payment(Base):
	__tablename__ = 'payment'
	__table_args__ = (
		{'mysql_engine':'InnoDB'}
		)

	idpayment = Column(Integer, primary_key=True)
	dtreason = Column(String(255))
	dtdate = Column(DateTime)
	dtamount = Column(Integer)
	lipaymentmethod = Column(Integer)	

	# defined in the member model
	limember = Column(Integer, ForeignKey('member.idmember'))
	#limember = relation(Member, backref=backref('payments', order_by=idpayment))

	#def __init__(self,reason,date,amount,limethod,limember):
	def __init__(self):
		pass	

	def __repr__(self):
		return "<Payment('idpayment=%d, limember=%d')>" % (self.idpayment, self.limember)


	def save(self):
		Session.commit()

