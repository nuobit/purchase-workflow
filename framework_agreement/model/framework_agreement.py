# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Nicolas Bessi
#    Copyright 2013 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from operator import attrgetter
from datetime import datetime
from openerp.osv import orm, fields
from openerp.osv.orm import except_orm
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
import openerp.addons.decimal_precision as dp


class framework_agreement(orm.Model):
    """Long term agreement on product price with a supplier"""

    _name = 'framework.agreement'

    def _check_running_date(self, cr, agreement, context=None):
        """ Validate that the current agreement is actually active
        using date only
        :param agreement: an agreement browse record
        :returns: a string - "running" if now is between,
                           - "future" if agreement is in future,
                           - "closed" if agreement is outdated
        """
        now = datetime.strptime(fields.datetime.now(),
                                DEFAULT_SERVER_DATETIME_FORMAT)
        start = datetime.strptime(agreement.start_date,
                                  DEFAULT_SERVER_DATETIME_FORMAT)
        end = datetime.strptime(agreement.end_date,
                                DEFAULT_SERVER_DATETIME_FORMAT)
        if start > now:
            return 'future'
        elif end < now:
            return 'closed'
        elif start <= now <= end:
            return 'running'
        else:
            raise ValueError('Agreement start/end dates are incorrect')

    def _get_self(self, cr, uid, ids, context=None):
        """ Store field function to get current ids"""
        return ids

    def _compute_state(self, cr, uid, ids, field_name, arg, context=None):
        """ Compute current state of agreement based on date and consumed
        amount"""
        res = {}
        for agreement in self.browse(cr, uid, ids, context=context):
            dates_state = self._check_running_date(cr, agreement, context=context)
            if dates_state == 'running':
                if agreement.available_quantity <= 0:
                    res[agreement.id] = 'consumed'
                else:
                    res[agreement.id] = 'running'
            else:
                res[agreement.id] = dates_state
        return res

    def _search_state(self, cr, uid, obj, name, args, context=None):
        """Implement serach on field in "and" mode only.
        supported opperators are =, in, not in, <>.
        For more information please refer to fnct_search OpenERP documentation"""
        if not args:
            return []
        ids = self.search(cr, uid, [], context=context)
        # this can be problematic in term of performace but the
        # state field can be changed by values and time evolution
        # In a business point of view there should be around 30 yearly LTA

        found_ids = []
        res = self.read(cr, uid, ids, ['state'], context=context)
        for field, operator, value in args:
            assert field == name
            if operator == '=':
                found_ids += [frm['id'] for frm in res if frm['state'] in value]
            elif operator == 'in' and isinstance(value, list):
                found_ids += [frm['id'] for frm in res if frm['state'] in value]
            elif operator in ("!=", "<>"):
                found_ids += [frm['id'] for frm in res if frm['state'] != value]
            elif operator == 'not in'and isinstance(value, list):
                found_ids += [frm['id'] for frm in res if frm['state'] not in value]
            else:
                raise NotImplementedError('Search operator %s not implemented for value %s'
                                          % (operator, value))
        to_return = set(found_ids)
        return [('id', 'in', [x['id'] for x in to_return])]

    def _get_state(self, cr, uid, ids, field_name, arg, context=None):
        """Return current state of agreement"""
        return self._compute_state(cr, uid, ids, field_name, arg, context=context)

    _columns = {'name': fields.char('Number',
                                    required=True,
                                    readonly=True),
                'supplier_id': fields.many2one('res.partner',
                                               'Supplier',
                                               required=True),
                'product_id': fields.many2one('product.product',
                                              'Product',
                                              required=True),
                'start_date': fields.datetime('Begin of Agreement',
                                              required=True),
                'end_date': fields.datetime('End of Agreement',
                                            required=True),
                'delay': fields.integer('Lead time in days'),
                'quantity': fields.integer('Negociated quantity',
                                           required=True),
                'framework_agreement_line_ids': fields.one2many('framework.agreement.line',
                                                                'framework_agreement_id',
                                                                'Price lines',
                                                                required=True),
                'available_quantity': fields.integer('Available quantity'), # To be transformer in function field
                'state': fields.function(_get_state,
                                         fnct_search=_search_state,
                                         string='state',
                                         type='selection',
                                         selection=[('future', 'Future'),
                                                    ('running', 'Running'),
                                                    ('consumed', 'Consumed'),
                                                    ('closed', 'Closed')],
                                         readonly=True),
                'company_id': fields.many2one('res.company',
                                              'Company')
                }

    def _sequence_get(self, cr, uid, context=None):
        return self.pool['ir.sequence'].get(cr, uid, 'framework.agreement')

    def check_overlap(self, cr, uid, ids, context=None):
        """ Constraint to check that no agreements for same product overlap"""
        for agreement in self.browse(cr, uid, ids, context=context):
            # we do not add current id in domain for readability reasons
            overlap = self.search(cr, uid, ['&', '&',
                                            ('product_id', '=', agreement.product_id.id),
                                            ('supplier_id', '=', agreement.supplier_id.id),
                                            '|', '&',
                                            ('start_date', '>=', agreement.start_date),
                                            ('start_date', '<=', agreement.end_date),
                                            '&',
                                            ('end_date', '>=', agreement.start_date),
                                            ('end_date', '<=', agreement.end_date)])
            # we also look for the one that include current offer
            overlap += self.search(cr, uid, [('start_date', '<=', agreement.start_date),
                                             ('end_date', '>=', agreement.end_date),
                                             ('id', '!=', agreement.id),
                                             ('product_id', '=', agreement.product_id.id)])
            # Gain has a special need they can not negotiate LTA for many supplier
                                             # ('supplier_id', '=', agreement.supplier_id.id),])
            overlap = [x for x in overlap if x != agreement.id]
            if overlap:
                return False
        return True

    _defaults = {'name': _sequence_get}

    _sql_constraints = [('date_priority',
                         'check(start_date < end_date)',
                         'Start/end date inversion')]

    _constraints = [(check_overlap,
                     "You can not have overlapping dates for same supplier and product",
                     ('start_date', 'end_date'))]

    def get_all_product_agreements(self, cr, uid, product_id, lookup_dt, qty=None, context=None):
        """ get the all the active agreement of a given product at a given date
        :param product_id: product id of the product
        :param lookup_dt: datetime string of the lookup date
        :param qty: quantity that should be available if parameter is
        passed and qty is insuffisant no aggrement would be returned
        :returns: a list of corresponding agreements or None"""
        search_args = [('product_id', '=', product_id),
                       ('start_date', '<=', lookup_dt),
                       ('end_date', '>=', lookup_dt)]
        if qty:
            search_args.append(('available_quantity', '>=', qty))
        agreement_ids = self.search(cr, uid, search_args)
        if agreement_ids:
            return self.browse(cr, uid, agreement_ids, context=context)
        return None

    def get_cheapest_agreement_for_qty(self, cr, uid, product_id, date, qty, context=None):
        """
        Return the cheapest agreement that has enought available qty else
        fallback on the cheapest
        :param product_id:
        :param date:
        :param qty:
        returns (cheapest, enough qty)
        """
        agreements = self.get_all_product_agreements(cr, uid, product_id,
                                                     date, qty, context=context)
        if not agreements:
            return (None, None)
        agreements.sort(key=lambda x: x.get_price(qty))
        enough = True
        cheapest_agreement = None
        for agr in agreements:
            if agr.available_quantity >= qty:
                cheapest_agreement = agr
                break
        if not cheapest_agreement:
            cheapest_agreement = agreements[0]
            enough = False
        return (cheapest_agreement, enough)

    def get_product_agreement(self, cr, uid, product_id, supplier_id,
                              lookup_dt, qty=None, context=None):
        """ get the agreement price of a given product at a given date
        :param product_id: product id of the product
        :param supplier_id: supplier to look for agreement
        :param lookup_dt: datetime string of the lookup date
        :param qty: quantity that should be available if parameter is
        passed and qty is insuffisant no aggrement would be returned
        :returns: a corresponding agreement or None"""
        search_args = [('product_id', '=', product_id),
                       ('supplier_id', '=', supplier_id),
                       ('start_date', '<=', lookup_dt),
                       ('end_date', '>=', lookup_dt)]
        if qty:
            search_args.append(('available_quantity', '>=', qty))
        agreement_ids = self.search(cr, uid, search_args)
        if len(agreement_ids) > 1:
            raise except_orm(_('Many agreements found for the product with id %s'
                               ' at date %s') % (product_id, lookup_dt),
                             _('Please contact your ERP administrator'))
        if agreement_ids:
            agreement = self.browse(cr, uid, agreement_ids[0], context=context)
            return agreement
        return None

    def get_price(self, cr, uid, agreement_id, qty=0, context=0):
        """Return price negociated for quantity

        :returns: price float

        """
        if isinstance(agreement_id, list):
            assert len(agreement_id) == 1
            agreement_id = agreement_id[0]
        current = self.browse(cr, uid, agreement_id, context=context)
        lines = current.framework_agreement_line_ids
        lines.sort(key=attrgetter('quantity'), reverse=True)
        for line in lines:
            if qty >= line.quantity:
                return line.price
        return lines[-1:]


class framework_agreement_line(orm.Model):
    """ price list line of framework agreement
    that contains price and qty"""

    _name = 'framework.agreement.line'

    _order = "quantity"

    _columns = {'framework_agreement_id': fields.many2one('framework.agreement',
                                                          'Agreement',
                                                          required=True),
                'quantity': fields.integer('Quantity',
                                           required=True),
                'price': fields.float('Price', 'Negociated price',
                                      required=True,
                                      digits_compute=dp.get_precision('Product Price'))}


class FrameworkAgreementObservable(object):
    """Base function for obect that have to be (pseudo) observable
    by framework agreement using OpenERP on change mechanism"""

    def onchange_price_obs(self, cr, uid, ids, price, date,
                           supplier_id, product_id, qty=0, context=None):
        """Raise a warning if a agreed price is changed on observed object"""
        if context is None:
            context = {}
        if not supplier_id or not ids:
            return {}
        agreement_obj = self.pool['framework.agreement']
        agreement = agreement_obj.get_product_agreement(cr, uid, product_id,
                                                        supplier_id, date,
                                                        context=context)
        if agreement is not None and agreement.get_price(qty) != price:
            msg = _("You have set the price to %s \n"
                    " but there is a running agreement"
                    " with price %s") % (price, agreement.get_price(qty))
            return {'warning': {'title': _('Agreement Warning!'),
                                'message': msg}}
        return {}

    def onchange_quantity_obs(self, cr, uid, ids, qty, date,
                              supplier_id, product_id, context=None):
        """Raise a warning if agreed qty is not sufficient when changed on observed object"""
        res = {}
        if not supplier_id:
            return res
        agrement, status = self._get_agreement_and_qty_status(cr, uid, ids, qty, date,
                                                              supplier_id, product_id,
                                                              context=context)
        if status:
            res['warning'] = {'title': _('Agreement Warning!'),
                              'message': status}
        return res

    def _get_agreement_and_qty_status(self, cr, uid, ids, qty, date,
                                      supplier_id, product_id, context=None):
        """Lookup for agreement and return (matching_agreement, status)

        Aggrement or status can be None

        """
        agreement_obj = self.pool['framework.agreement']
        agreement = agreement_obj.get_product_agreement(cr, uid, product_id,
                                                        supplier_id, date,
                                                        context=context)
        if agreement is None:
            return (None, None)
        msg = None
        if agreement.available_quantity < qty:
            msg = _("You have ask for a quantity of %s \n"
                    " but there is only %s available"
                    " for current agreement") % (qty, agreement.available_quantity)
        return (agreement, msg)

    def onchange_product_id_obs(self, cr, uid, ids, qty, date,
                                supplier_id, product_id, price_field='price',
                                context=None):
        """
        Lookup for agreement corresponding to product or return None.
        It will raise a warning if not enough available qty.
        :param product_id:
        :param qty:
        :param lookup_dt:
        """
        res = {}
        if not supplier_id:
            return res
        agreement, status = self._get_agreement_and_qty_status(cr, uid, ids, qty, date,
                                                               supplier_id, product_id,
                                                               context=context)
        if agreement:
            res['value'] = {price_field: agreement.get_price(qty)}
        if status:
            res['warning'] = {'title': _('Agreement Warning!'),
                              'message': status}
        return res
