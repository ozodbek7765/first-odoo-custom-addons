{
    'name': 'Sale Approval',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Buyuk buyurtmalar uchun tasdiqlash tizimi',
    'depends': ['base', 'sale', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/approval_request_views.xml',
    ],
    'installable': True,
    'application': True,
}
