from odoo import models, fields, api
from odoo.exceptions import ValidationError


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
                invoices = self.env['account.move'].search([
                    ('partner_id', '=', limit.partner_id.id),
                    ('state', '=', 'posted'),
                    ('payment_state', 'not in', ['paid', 'in_payment']),
                    ('move_type', '=', 'out_invoice')
                ])
                limit.total_due = sum(invoices.mapped('amount_residual'))
            else:
                limit.total_due = 0

    @api.depends('credit_limit', 'total_due')
    def _compute_remaining_credit(self):
        for limit in self:
            limit.remaining_credit = limit.credit_limit - limit.total_due

    @api.constrains('partner_id', 'active')
    def _check_unique_active_credit_limit(self):
        for record in self:
            if record.active:
                existing = self.search([
                    ('partner_id', '=', record.partner_id.id),
                    ('active', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(
                        'Bir mijoz uchun faqat bitta aktiv kredit limit bo\'lishi mumkin!'
                    )

    def toggle_active(self):
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
                ('partner_id', '=', order.partner_id.id),
                ('active', '=', True)
            ], limit=1)

            order.available_credit = credit_limit.remaining_credit if credit_limit else 0

    @api.depends('available_credit', 'amount_total')
    def _compute_credit_limit_warning(self):
        for order in self:
            order.credit_limit_warning = (
                order.available_credit > 0 and
                order.amount_total > order.available_credit
            )

    def action_view_credit_limit(self):
        self.ensure_one()

        credit_limit = self.env['customer.credit.limit'].search([
            ('partner_id', '=', self.partner_id.id),
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
        for order in self:
            credit_limit_rec = self.env['customer.credit.limit'].search([
                ('partner_id', '=', order.partner_id.id),
                ('active', '=', True)
            ], limit=1)

            if credit_limit_rec:
                total_risk = credit_limit_rec.total_due + order.amount_total

                if total_risk > credit_limit_rec.credit_limit:
                    raise ValidationError(
                        "⚠️ TASDIQLANMADI! Kredit limiti oshib ketdi.\n\n"
                        "Mijoz: %s\n"
                        "Ruxsat etilgan limit: %s %s\n"
                        "Qolgan kredit: %s %s\n"
                        "Buyurtma summasi: %s %s\n"
                        "Jami risk: %s %s\n\n"
                        "Iltimos, Accounting Manager bilan bog'laning!" % (
                            order.partner_id.name,
                            credit_limit_rec.credit_limit,
                            credit_limit_rec.currency_id.symbol,
                            credit_limit_rec.remaining_credit,
                            credit_limit_rec.currency_id.symbol,
                            order.amount_total,
                            order.currency_id.symbol,
                            total_risk,
                            credit_limit_rec.currency_id.symbol
                        )
                    )

        return super().action_confirm()