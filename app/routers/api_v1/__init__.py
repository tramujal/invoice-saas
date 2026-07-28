"""The public REST API (/api/v1) -- Organization API Key authenticated,
never browser-session authenticated (see app.api_key_auth). Every router
here calls the exact same service-layer functions the browser routers
use (app.services.customers/products/quotes/invoices) -- no business
logic, plan enforcement, or usage tracking is duplicated; both surfaces
share one implementation of each.
"""
