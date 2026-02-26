from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError


class SaleApprovalRequest(models.Model):
    _name = 'sale.approval.request'
    _description = 'Sotish Buyurtmasi Tasdiqlash So\'rovi'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomi', required=True, readonly=True, 
                       default=lambda self: self.env['ir.sequence'].next_by_code('sale.approval.request'))
    sale_order_id = fields.Many2one('sale.order', string='Sotish Buyurtmasi', 
                                     required=True, ondelete='cascade')
    requested_by = fields.Many2one('res.users', string='So\'rov Qilgan', 
                                    required=True, readonly=True,
                                    default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', string='Tasdiqlagan')
    rejection_reason = fields.Text(string='Rad Etish Sababi')
    state = fields.Selection([
        ('draft', 'Taslagi'),
        ('submitted', 'Yuborildi'),
        ('approved', 'Tasdiqlandi'),
        ('rejected', 'Rad Etildi'),
    ], string='Holati', default='draft', tracking=True)
    total_amount = fields.Monetary(string='Jami Summa', compute='_compute_total_amount', store=True)
    currency_id = fields.Many2one('res.currency', string='Valyuta',
                                   default=lambda self: self.env.company.currency_id)
    approval_date = fields.Datetime(string='Tasdiqlash Vaqti', readonly=True)

    _sql_constraints = [
        ('sale_order_unique', 'unique(sale_order_id)', "Har bir sale order uchun faqat bitta approval request bo'lishi mumkin."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self.env.user.has_group('sales_team.group_sale_manager')
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.approval.request') or '/'
            if not is_manager:
                # Oddiy user faqat o'zi uchun submit jarayonini boshlaydi.
                vals['requested_by'] = self.env.user.id
                vals.pop('approved_by', None)
                vals.pop('approval_date', None)
                if vals.get('state') in ('approved', 'rejected'):
                    raise AccessError(_("Oddiy user approval holatini belgilay olmaydi."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            allowed_fields = {'state'}
            if set(vals) - allowed_fields:
                raise AccessError(_("Oddiy user faqat submit (state) amalini bajarishi mumkin."))

            if 'state' in vals:
                if vals['state'] != 'submitted':
                    raise AccessError(_("Oddiy user faqat `submitted` holatiga o'tkaza oladi."))
                if any(rec.state != 'draft' for rec in self):
                    raise ValidationError(_("Faqat draft so'rovni submit qilish mumkin."))
        return super().write(vals)

    @api.depends('sale_order_id.amount_total')
    def _compute_total_amount(self):
        for request in self:
            if request.sale_order_id:
                request.total_amount = request.sale_order_id.amount_total
            else:
                request.total_amount = 0

    def action_submit(self):
        """So'rovni yuborish"""
        for request in self:
            if request.state != 'draft':
                raise ValidationError('Faqat taslagi holatdagi so\'rovlarni yuborish mumkin!')
            
            request.write({'state': 'submitted'})
            
            # Notifikatsiya yuborish
            request._send_notification_to_managers()
    
    def action_approve(self):
        """Tasdiqlash"""
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise ValidationError(_("Faqat Sales Manager tasdiqlashi mumkin!"))

        for request in self:
            if request.state != 'submitted':
                raise ValidationError('Faqat yuborilgan so\'rovlarni tasdiqlash mumkin!')
            
            request.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approval_date': fields.Datetime.now()
            })
            
            # Sale Order avtomatik confirm qilish
            request.sale_order_id.action_confirm()
            
            # Notifikatsiya yuborish
            request._send_approval_notification()
    
    def action_reject(self):
        """Rad etish"""
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise ValidationError(_("Faqat Sales Manager rad etishi mumkin!"))

        for request in self:
            if not request.rejection_reason:
                raise ValidationError('Rad etish sababini kiriting!')

            if request.state != 'submitted':
                raise ValidationError('Faqat yuborilgan so\'rovlarni rad etish mumkin!')
            
            request.write({'state': 'rejected'})
            
            # Notifikatsiya yuborish
            request._send_rejection_notification()
    
    def action_draft(self):
        """Taslagi holatiga qaytarish"""
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise ValidationError(_("Faqat Sales Manager holatni qaytarishi mumkin!"))

        for request in self:
            if request.state not in ['rejected', 'submitted']:
                raise ValidationError('Faqat rad etilgan yoki yuborilgan so\'rovlarni taslagi holatiga qaytarish mumkin!')
            
            request.write({
                'state': 'draft',
                'rejection_reason': '',
                'approved_by': False,
                'approval_date': False
            })
    
    def _send_notification_to_managers(self):
        """Menejerlarni notifikatsiya qilish"""
        managers = self.env['res.users'].search([
            ('groups_id.name', 'ilike', 'Sales Manager')
        ])
        
        for manager in managers:
            if manager.partner_id:
                self.message_notify(
                    partner_ids=[manager.partner_id.id],
                    body=f"Yangi sotish tasdiqlash so'rovi: {self.name}<br/>"
                         f"Buyurtma: {self.sale_order_id.name}<br/>"
                         f"Summa: {self.total_amount} {self.currency_id.name}<br/>"
                         f"So'rov Qilgan: {self.requested_by.name}",
                    subject=f"Tasdiqlash So'rovi: {self.name}"
                )

    def _send_approval_notification(self):
        """Tasdiqlash notifikatsiyasi"""
        self.message_notify(
            partner_ids=[self.requested_by.partner_id.id] if self.requested_by.partner_id else [],
            body=f"Sizning '{self.sale_order_id.name}' so'rovingiz {self.approved_by.name} tomonidan tasdiqlandi!",
            subject=f"✓ Tasdiqlandi: {self.name}"
        )

    def _send_rejection_notification(self):
        """Rad etish notifikatsiyasi"""
        self.message_notify(
            partner_ids=[self.requested_by.partner_id.id] if self.requested_by.partner_id else [],
            body=f"Sizning '{self.sale_order_id.name}' so'rovingiz rad etildi!<br/>"
                 f"Sabab: {self.rejection_reason}",
            subject=f"✗ Rad Etildi: {self.name}"
        )


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    approval_request_id = fields.Many2one('sale.approval.request', string='Tasdiqlash So\'rovi',
                                           readonly=True)
    approval_status = fields.Selection(related='approval_request_id.state', string='Tasdiqlash Holati')
    requires_approval = fields.Boolean(compute='_compute_requires_approval', string='Tasdiqlash Kerak')
    approval_count = fields.Integer(compute='_compute_approval_count', string='Tasdiqlashlar Soni')

    @api.depends('amount_total')
    def _compute_requires_approval(self):
        """10000 dan katta buyurtmalar tasdiqlash talab qiladi"""
        for order in self:
            order.requires_approval = order.amount_total > 10000

    @api.depends('approval_request_id')
    def _compute_approval_count(self):
        for order in self:
            order.approval_count = self.env['sale.approval.request'].search_count([
                ('sale_order_id', '=', order.id)
            ])

    def action_confirm(self):
        """Buyurtmani tasdiqlash"""
        for order in self:
            if order.amount_total > 10000:
                # Agar tasdiqlash so'rovi mavjud bo'lsa, uni tekshir
                approval = self.env['sale.approval.request'].search([
                    ('sale_order_id', '=', order.id)
                ], limit=1)
                
                if not approval:
                    # Yangi tasdiqlash so'rovi yarating
                    approval = self.env['sale.approval.request'].create({
                        'sale_order_id': order.id,
                        'requested_by': self.env.user.id,
                    })
                    order.approval_request_id = approval.id
                    
                    raise ValidationError(
                        f"⚠️ Bu buyurtma tasdiqlash talab qiladi!\n\n"
                        f"Summa: {order.amount_total} {order.currency_id.name}\n"
                        f"Limit: 10,000 {order.currency_id.name}\n\n"
                        f"Tasdiqlash so'rovi ({approval.name}) yaratildi.\n"
                        f"Iltimos, Sales Manager tasdiqlasinini kuting."
                    )
                
                elif approval.state in ('draft', 'submitted'):
                    order.approval_request_id = approval.id
                    raise ValidationError(
                        f"⏳ Bu buyurtma hali tasdiqlash kutmoqda!\n"
                        f"Tasdiqlash so'rovi: {approval.name}\n"
                        f"Iltimos, so'rovni yuboring va Sales Manager tasdiqlasinini kuting."
                    )
                
                elif approval.state == 'rejected':
                    order.approval_request_id = approval.id
                    raise ValidationError(
                        f"❌ Bu buyurtma rad etildi!\n"
                        f"Sabab: {approval.rejection_reason}\n"
                        f"Iltimos, satish jamiyatiga murojaat qiling."
                    )
                
                elif approval.state == 'approved':
                    # Tasdiqlash so'rovi tasdiqlandi, davom et
                    order.approval_request_id = approval.id
        
        return super(SaleOrder, self).action_confirm()

    def action_view_approval_request(self):
        """Tasdiqlash so'rovini ko'rish"""
        self.ensure_one()

        approval = self.approval_request_id or self.env['sale.approval.request'].search([
            ('sale_order_id', '=', self.id)
        ], limit=1)
        
        if approval:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.approval.request',
                'res_id': approval.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            raise ValidationError('Ushbu buyurtma uchun tasdiqlash so\'rovi topilmadi!')

    def action_create_approval_request(self):
        """Tasdiqlash so'rovi yarating"""
        self.ensure_one()
        
        if self.amount_total <= 10000:
            raise ValidationError('Faqat 10000 dan katta buyurtmalar uchun tasdiqlash kerak!')
        
        if self.approval_request_id:
            approval = self.approval_request_id
        else:
            approval = self.env['sale.approval.request'].search([
                ('sale_order_id', '=', self.id)
            ], limit=1)

            if not approval:
                approval = self.env['sale.approval.request'].create({
                    'sale_order_id': self.id,
                    'requested_by': self.env.user.id,
                })
            self.approval_request_id = approval.id
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.approval.request',
            'res_id': approval.id,
            'view_mode': 'form',
            'target': 'current',
        }
