{
    'name': 'Customer Credit Control',
    'version': '1.0.0',
    'category': 'Accounting',
    'summary': 'Mijoz kredit limitini boshqarish',
    'description': 'Mijozlar uchun kredit limitini belgilash va kuzatish',
    'author': 'Your Company',
    'depends': ['account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'views/credit_limit_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}