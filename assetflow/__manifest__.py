# -*- coding: utf-8 -*-
{
    'name': 'AssetFlow — Enterprise Asset & Resource Management',
    'version': '17.0.2.0.0',
    'category': 'Operations/Assets',
    'summary': 'Complete asset lifecycle, conflict-free bookings, transfer workflows, maintenance, and audit cycles.',
    'description': """
AssetFlow — Enterprise Asset & Resource Management System

Key Features:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Asset lifecycle management with auto-tagging (AF-XXXX)
✓ Conflict-free resource bookings with datetime overlap validation
✓ Allocation tracking with Transfer Workflow (Requested → Approved → Re-allocated)
✓ Overdue detection via daily scheduled cron + activity reminders
✓ Maintenance workflows with risk scoring (Low/Medium/High)
✓ Periodic audit cycles with one-click auto-reconciliation
✓ Role-based access control (Admin/Manager/Dept Head/Employee)
✓ KPI Dashboard with real-time operational snapshot
    """,
    'author': 'AssetFlow Team',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'hr'],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        # Sequences & Cron
        'data/sequences.xml',
        'data/cron.xml',
        'data/demo_data.xml',
        # Wizard views
        'wizards/transfer_wizard_views.xml',
        # Views — actions must be defined BEFORE menus reference them
        'views/setup_views.xml',
        'views/asset_views.xml',
        'views/allocation_views.xml',
        'views/booking_views.xml',
        'views/maintenance_views.xml',
        'views/audit_views.xml',
        'views/dashboard_views.xml',
        # Menus last (references action IDs defined above)
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
