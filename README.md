# Custom Odoo Addons

This repository contains two custom Odoo addons developed for business-specific sales control and approval workflows.

## Modules

### 1. `customer_credit_control`

Credit limit enforcement for customers, integrated with Sales, Accounting, and Partners.

#### Main Features

- Defines a custom model: `customer.credit.limit`
- Tracks:
  - customer (`partner_id`)
  - credit limit amount
  - currency
  - total due
  - remaining credit
- Validates sales operations against risk exposure:
  - posted unpaid accounting entries
  - open uninvoiced confirmed sales
  - current order total
- Blocks operations when limit is exceeded:
  - order confirmation
  - invoice creation
  - order line updates
- Provides Sales Order smart credit info and warning indicator.
- Enforces one active credit limit per customer.

#### Security

- Accounting Manager: full access (create/write/delete)
- Sales User: read-only access
- Regular internal user: no edit rights

---

### 2. `sale_approval`

Approval workflow for high-value sales orders.

#### Main Features

- Defines a custom model: `sale.approval.request`
- Auto sequence for request naming (`SAR/YYYY/#####`)
- Workflow states:
  - `draft`
  - `submitted`
  - `approved`
  - `rejected`
- For sales orders above 10,000:
  - confirmation is blocked until approval
  - approval request is created automatically
- When approved by Sales Manager, order is confirmed automatically.
- Includes reject reason support and smart button access from Sales Order.

#### Security

- Sales Manager: can approve/reject/reset approval state
- Sales User: can submit requests only

---

## Installation

1. Add this directory to your Odoo `addons_path`.
2. Update the app list.
3. Install modules:
   - `customer_credit_control`
   - `sale_approval`

## Update Command (example)

```bash
./venv/bin/python ./odoo-bin -d task_db --addons-path=addons,custom_addons -u customer_credit_control,sale_approval --stop-after-init
```

## Notes

- These addons were built for Odoo 19.
- Always validate access rights with at least two users:
  - manager role
  - regular sales role
