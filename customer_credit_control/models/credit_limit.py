from odoo import models, fields, api
from odoo.exceptions import ValidationError, AccessError


class CustomerCreditLimit(models.Model):
    _name = 'customer.credit.limit'
    _description = 'Mijoz Kredit Limiti'
    _order = 'create_date desc'

    partner_id = fields.Many2one('res.partner', string='Mijoz', required=True, ondelete='cascade')
    credit_limit = fields.Monetary(string='Kredit Limiti', required=True)
    currency_id = fields.Many2one('res.currency', string='Valyuta',
                                  default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(default=True)
    note = fields.Text(string='Izohlar')
    total_due = fields.Monetary(string='Jami Qarz', compute='_compute_total_due', store=True)
    remaining_credit = fields.Monetary(string='Qolgan Kredit', compute='_compute_remaining_credit', store=True)


    @api.depends('partner_id')
    def _compute_total_due(self):
        for limit in self:
            if limit.partner_id:
                limit.total_due = limit._get_partner_total_due(
                    partner=limit.partner_id,
                    company=self.env.company,
                    target_currency=limit.currency_id,
                )
            else:
                limit.total_due = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            partner_id = vals.get('partner_id')
            if partner_id:
                partner = self.env['res.partner'].browse(partner_id)
                vals['partner_id'] = partner.commercial_partner_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('partner_id'):
            partner = self.env['res.partner'].browse(vals['partner_id'])
            vals['partner_id'] = partner.commercial_partner_id.id
        return super().write(vals)

    def _get_partner_total_due(self, partner, company, target_currency):
        commercial_partner = partner.commercial_partner_id
        invoices = self.env['account.move'].search([
            ('commercial_partner_id', '=', commercial_partner.id),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial', 'in_payment']),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
        ])
        total_due_company_currency = sum(invoices.mapped('amount_residual_signed'))
        return company.currency_id._convert(
            total_due_company_currency,
            target_currency,
            company,
            fields.Date.context_today(self),
        )

    def _get_partner_open_sales_exposure(self, partner, company, target_currency, exclude_order=None):
        commercial_partner = partner.commercial_partner_id
        domain = [
            ('partner_id', 'child_of', commercial_partner.id),
            ('state', '=', 'sale'),
        ]
        if exclude_order:
            domain.append(('id', '!=', exclude_order.id))

        open_orders = self.env['sale.order'].search(domain)
        exposure = 0.0
        for so in open_orders:
            if so.amount_to_invoice <= 0:
                continue
            exposure += so.currency_id._convert(
                so.amount_to_invoice,
                target_currency,
                so.company_id,
                so.date_order.date() if so.date_order else fields.Date.context_today(so),
            )
        return exposure

    @api.depends('credit_limit', 'total_due')
    def _compute_remaining_credit(self):
        for limit in self:
            limit.remaining_credit = limit.credit_limit - limit.total_due

    @api.constrains('partner_id', 'active')
    def _check_unique_active_credit_limit(self):
        for record in self:
            if record.active:
                existing = self.search([
                    ('partner_id', '=', record.partner_id.commercial_partner_id.id),
                    ('active', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(
                        'Bir mijoz uchun faqat bitta aktiv kredit limit bo\'lishi mumkin!'
                    )

    def toggle_active(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError("Faqat Accounting Manager aktiv/pasiv holatini o'zgartira oladi.")
        for rec in self:
            rec.active = not rec.active


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    available_credit = fields.Monetary(string='Mavjud Kredit', compute='_compute_available_credit')
    credit_limit_warning = fields.Boolean(compute='_compute_credit_limit_warning')

    @api.depends('partner_id')
    def _compute_available_credit(self):
        for order in self:
            credit_limit = self.env['customer.credit.limit'].search([
                ('partner_id', '=', order.partner_id.commercial_partner_id.id),
                ('active', '=', True)
            ], limit=1)

            if credit_limit:
                live_total_due = credit_limit._get_partner_total_due(
                    partner=order.partner_id,
                    company=order.company_id,
                    target_currency=credit_limit.currency_id,
                )
                open_sales_exposure = credit_limit._get_partner_open_sales_exposure(
                    partner=order.partner_id,
                    company=order.company_id,
                    target_currency=credit_limit.currency_id,
                    exclude_order=order,
                )
                order.available_credit = credit_limit.credit_limit - (live_total_due + open_sales_exposure)
            else:
                order.available_credit = 0

    @api.depends('available_credit', 'amount_total')
    def _compute_credit_limit_warning(self):
        for order in self:
            credit_limit = self.env['customer.credit.limit'].search([
                ('partner_id', '=', order.partner_id.commercial_partner_id.id),
                ('active', '=', True),
            ], limit=1)
            if not credit_limit:
                order.credit_limit_warning = False
                continue

            order_total_in_limit_currency = order.currency_id._convert(
                order.amount_total,
                credit_limit.currency_id,
                order.company_id,
                order.date_order.date() if order.date_order else fields.Date.context_today(order),
            )
            order.credit_limit_warning = (
                order_total_in_limit_currency > order.available_credit
            )

    def _check_credit_limit_restriction(self):
        for order in self:
            credit_limit_rec = self.env['customer.credit.limit'].search([
                ('partner_id', '=', order.partner_id.commercial_partner_id.id),
                ('active', '=', True)
            ], limit=1)

            if not credit_limit_rec:
                continue

            live_total_due = credit_limit_rec._get_partner_total_due(
                partner=order.partner_id,
                company=order.company_id,
                target_currency=credit_limit_rec.currency_id,
            )
            open_sales_exposure = credit_limit_rec._get_partner_open_sales_exposure(
                partner=order.partner_id,
                company=order.company_id,
                target_currency=credit_limit_rec.currency_id,
                exclude_order=order,
            )
            order_total_in_limit_currency = order.currency_id._convert(
                order.amount_total,
                credit_limit_rec.currency_id,
                order.company_id,
                order.date_order.date() if order.date_order else fields.Date.context_today(order),
            )
            total_risk = live_total_due + open_sales_exposure + order_total_in_limit_currency
            if total_risk > credit_limit_rec.credit_limit:
                raise ValidationError(
                    "Kredit limiti oshdi. Amaliyot ruxsat etilmaydi.\n"
                    "Mijoz: %s\n"
                    "Limit: %s %s\n"
                    "Joriy qarz: %s %s\n"
                    "Ochiq savdo riski: %s %s\n"
                    "Buyurtma summasi: %s %s\n"
                    "Jami risk: %s %s" % (
                        order.partner_id.name,
                        credit_limit_rec.credit_limit,
                        credit_limit_rec.currency_id.symbol,
                        live_total_due,
                        credit_limit_rec.currency_id.symbol,
                        open_sales_exposure,
                        credit_limit_rec.currency_id.symbol,
                        order_total_in_limit_currency,
                        credit_limit_rec.currency_id.symbol,
                        total_risk,
                        credit_limit_rec.currency_id.symbol,
                    )
                )

    def action_view_credit_limit(self):
        self.ensure_one()
        if not (
            self.env.user.has_group('account.group_account_manager')
            or self.env.user.has_group('sales_team.group_sale_salesman')
            or self.env.user.has_group('sales_team.group_sale_manager')
        ):
            raise AccessError("Kredit limitni faqat Sales yoki Accounting rollari ko'ra oladi.")

        credit_limit = self.env['customer.credit.limit'].search([
            ('partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('active', '=', True)
        ], limit=1)

        if credit_limit:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'customer.credit.limit',
                'res_id': credit_limit.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            raise ValidationError('Ushbu mijoz uchun kredit limiti topilmadi!')

    def action_confirm(self):
        self._check_credit_limit_restriction()
        return super().action_confirm()

    def _create_invoices(self, grouped=False, final=False, date=None):
        self._check_credit_limit_restriction()
        return super()._create_invoices(grouped=grouped, final=final, date=date)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        orders = lines.mapped('order_id').filtered(lambda o: o.state in ('draft', 'sent', 'sale'))
        if orders:
            orders._check_credit_limit_restriction()
        return lines

    def write(self, vals):
        result = super().write(vals)
        orders = self.mapped('order_id').filtered(lambda o: o.state in ('draft', 'sent', 'sale'))
        if orders:
            orders._check_credit_limit_restriction()
        return result


class ResPartner(models.Model):
    _inherit = 'res.partner'

    credit_limit_count = fields.Integer(
        string='Credit Limit Count',
        compute='_compute_credit_limit_count',
    )

    def _compute_credit_limit_count(self):
        for partner in self:
            partner.credit_limit_count = self.env['customer.credit.limit'].search_count([
                ('partner_id', '=', partner.commercial_partner_id.id)
            ])

    def action_view_credit_limits(self):
        self.ensure_one()
        if not (
            self.env.user.has_group('account.group_account_manager')
            or self.env.user.has_group('sales_team.group_sale_salesman')
            or self.env.user.has_group('sales_team.group_sale_manager')
        ):
            raise AccessError("Kredit limit ro'yxatini faqat Sales yoki Accounting rollari ko'ra oladi.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kredit Limitlari',
            'res_model': 'customer.credit.limit',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.commercial_partner_id.id)],
            'context': {'default_partner_id': self.commercial_partner_id.id},
            'target': 'current',
        }
