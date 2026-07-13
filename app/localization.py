"""Organization-level localization: language and translated strings.

Organization.language ("en"/"es") drives which strings the PDF and email
templates use. Adding a new language means adding one more dict below —
call sites don't change.
"""

from typing import TYPE_CHECKING

from app.payment_status import PaymentStatus
from app.quote_status import QuoteStatus

if TYPE_CHECKING:
    from app.models import Invoice, Organization, Quote

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "es")

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "invoice_title": "Invoice",
        "invoice_no_label": "Invoice No.",
        "created_label": "Issue Date",
        "due_date_label": "Due Date",
        "payment_status_label": "Payment Status",
        "from_label": "From",
        "bill_to_label": "Bill To",
        "line_description_label": "Description",
        "line_quantity_label": "Quantity",
        "line_unit_price_label": "Unit Price",
        "line_total_label": "Line Total",
        "subtotal_label": "Subtotal",
        "tax_amount_label": "Tax",
        "total_label": "Total",
        "no_customer": "No customer on file",
        "status_pending": "Pending",
        "status_paid": "Paid",
        "status_overdue": "Overdue",
        "email_subject": "Invoice {invoice_number}",
        "email_greeting": "Hello {name},",
        "email_intro": "Please find your invoice attached.",
        "email_invoice_number_label": "Invoice Number:",
        "email_due_date_label": "Due Date:",
        "email_total_label": "Total:",
        "email_payment_status_label": "Payment Status:",
        "email_thanks": "Thank you.",
        "password_reset_subject": "Reset your password",
        "password_reset_greeting": "Hello,",
        "password_reset_instructions": "We received a request to reset your password.",
        "password_reset_link_label": "Reset your password:",
        "password_reset_expiry": "This link expires in 30 minutes.",
        "password_reset_ignore": (
            "If you did not request this, you can safely ignore this email."
        ),
        "verification_subject": "Verify your email address",
        "verification_greeting": "Hello,",
        "verification_instructions": (
            "Please confirm your email address to finish setting up your account."
        ),
        "verification_link_label": "Verify your email:",
        "verification_expiry": "This link expires in 24 hours.",
        "verification_ignore": (
            "If you did not create an account, you can safely ignore this email."
        ),
        "assistant_no_data_note": "This organization has no invoices or customers yet.",
        "assistant_org_label": "Organization",
        "assistant_total_invoices_label": "Total Invoices",
        "assistant_total_customers_label": "Total Customers",
        "assistant_revenue_heading": "Revenue by Currency",
        "assistant_no_exchange_rate_note": (
            "No exchange-rate conversion has been performed between currencies "
            "— amounts in different currencies are never added together."
        ),
        "assistant_this_month_label": "this month",
        "assistant_last_month_label": "last month",
        "assistant_growth_label": "growth",
        "assistant_invoice_status_heading": "Invoices by Status",
        "assistant_recent_invoices_heading": "Recent Invoices",
        "assistant_overdue_invoices_heading": "Overdue Invoices",
        "assistant_no_overdue_invoices": "No overdue invoices.",
        "assistant_due_soon_invoices_heading": "Invoices Due Soon",
        "assistant_no_due_soon_invoices": "No invoices due soon.",
        "assistant_reminders_sent_label": (
            "{count} payment reminders sent in the last {days} days"
        ),
        "assistant_top_customers_heading": "Top Customers by Revenue",
        "assistant_top_products_heading": "Top Products & Services by Revenue",
        "assistant_products_label": "Products",
        "assistant_services_label": "Services",
        "assistant_dormant_products_heading": "Products That Stopped Selling",
        "assistant_no_dormant_products": "No products have stopped selling recently.",
        "assistant_days_since_last_sale": "{days} days since last sale",
        "assistant_stale_customers_heading": "Customers Not Invoiced Recently",
        "assistant_no_stale_customers": "All customers have been invoiced recently.",
        "assistant_never_invoiced": "never invoiced",
        "assistant_days_since_invoice": "{days} days since last invoice",
        "assistant_monthly_revenue_heading": "Monthly Revenue (last 6 months, by currency)",
        "assistant_monthly_volume_heading": (
            "Monthly Invoice Volume (last 6 months, all currencies combined — a count, not money)"
        ),
        "import_template_name_label": "Name",
        "import_template_email_label": "Email",
        "import_template_phone_label": "Phone",
        "import_template_address_label": "Address",
        "import_template_example_name": "Acme Inc.",
        "import_template_example_email": "billing@example.com",
        "import_template_example_phone": "+1 555 0100",
        "import_template_example_address": "123 Main St, Springfield",
        "import_template_example_tax_id": "12-3456789",
        "import_product_template_name_label": "Name",
        "import_product_template_description_label": "Description",
        "import_product_template_type_label": "Type",
        "import_product_template_sku_label": "SKU",
        "import_product_template_price_label": "Default Price",
        "import_product_template_currency_label": "Currency",
        "import_product_template_tax_rate_label": "Default Tax Rate",
        "import_product_template_example_name": "Hosting - Premium",
        "import_product_template_example_description": "Monthly premium hosting plan",
        "import_product_template_example_type": "service",
        "import_product_template_example_sku": "HOST-PREM",
        "import_product_template_example_price": "49.00",
        "import_product_template_example_tax_rate": "0.10",
        "insight_no_invoices_title": "No invoices yet",
        "insight_no_invoices_message": (
            "You haven't created any invoices yet — once you do, you'll see insights "
            "about revenue, overdue payments, and your customers here."
        ),
        "insight_no_invoices_suggestion": "Create your first invoice to get started.",
        "insight_first_invoice_title": "First invoice created",
        "insight_first_invoice_message": (
            "You've created your first invoice. As you add more, you'll start seeing "
            "trends and comparisons here."
        ),
        "insight_revenue_first_month_title": "First month with {currency} revenue",
        "insight_revenue_first_month_message": (
            "You've recorded {currency} {amount} in revenue this month — there's no "
            "prior month yet to compare it to."
        ),
        "insight_revenue_increase_title": "{currency} revenue up {percentage}%",
        "insight_revenue_increase_message": (
            "{currency} revenue this month is {this_month}, up from {last_month} "
            "last month ({percentage}%)."
        ),
        "insight_revenue_decline_title": "{currency} revenue down {percentage}%",
        "insight_revenue_decline_message": (
            "{currency} revenue this month is {this_month}, down from {last_month} "
            "last month ({percentage}%)."
        ),
        "insight_revenue_stable_title": "{currency} revenue holding steady",
        "insight_revenue_stable_message": (
            "{currency} revenue this month is {this_month}, close to last month's {last_month}."
        ),
        "insight_revenue_decline_suggestion": (
            "Review recent invoices and customer activity to understand the change."
        ),
        "insight_revenue_ask_question": "Explain why {currency} revenue changed this month.",
        "insight_overdue_title": "{count} overdue invoices in {currency}",
        "insight_overdue_message": (
            "{count} invoices totaling {currency} {amount} are overdue. The oldest, "
            "{oldest_invoice}, is {oldest_days} days overdue; the largest is "
            "{largest_invoice} at {currency} {largest_amount}."
        ),
        "insight_overdue_suggestion": "Follow up on the oldest or largest overdue invoices first.",
        "insight_pending_title": "High pending balance in {currency}",
        "insight_pending_message": (
            "{currency} {amount} is still pending payment — {percentage}% of this "
            "currency's total revenue."
        ),
        "insight_pending_suggestion": (
            "Review pending invoices and consider following up with customers."
        ),
        "insight_concentration_title": "Revenue concentrated in one customer ({currency})",
        "insight_concentration_message": (
            "{customer} accounts for {percentage}% of your {currency} revenue."
        ),
        "insight_concentration_suggestion": (
            "Consider diversifying your customer base to reduce this risk."
        ),
        "insight_concentration_ask_question": "Help me reduce customer concentration risk.",
        "insight_inactivity_title": "{count} customers gone quiet",
        "insight_inactivity_message": (
            "{count} previously active customers haven't been invoiced in a while — "
            "{customer} the longest, at {days} days."
        ),
        "insight_inactivity_suggestion": "Consider reaching out to check in.",
        "insight_inactivity_ask_question": (
            "Which inactive customers should I follow up with, starting with {customer}?"
        ),
        "insight_volume_first_month_title": "First month with invoices",
        "insight_volume_first_month_message": (
            "You created {count} invoices this month — there's no prior month yet to "
            "compare it to."
        ),
        "insight_volume_increase_title": "Invoice volume up {percentage}%",
        "insight_volume_decrease_title": "Invoice volume down {percentage}%",
        "insight_volume_message": (
            "You created {this_month} invoices this month, versus {last_month} last month."
        ),
        "insight_status_high_overdue_title": "High share of overdue invoices",
        "insight_status_high_overdue_message": (
            "{overdue} of your {total} invoices ({percentage}%) are overdue."
        ),
        "insight_status_all_pending_title": "All invoices still pending",
        "insight_status_all_pending_message": "All {count} of your invoices are still pending payment.",
        "insight_status_no_paid_title": "No invoices paid yet",
        "insight_status_no_paid_message": (
            "None of your invoices have been paid yet, and {overdue} are overdue."
        ),
        "insight_status_mostly_paid_title": "Most invoices paid",
        "insight_status_mostly_paid_message": (
            "{paid} of your {total} invoices ({percentage}%) are paid."
        ),
        "insight_multi_currency_title": "Tracking revenue in {count} currencies",
        "insight_multi_currency_message": (
            "You have revenue in {currencies}. Figures are always tracked separately "
            "per currency and never combined."
        ),
        "insight_data_quality_title": "A few things worth tidying up",
        "insight_data_quality_invoices_without_customer_message": (
            "{count} invoices have no customer attached."
        ),
        "insight_data_quality_customers_missing_phone_message": (
            "{count} customers have no phone number on file."
        ),
        "insight_data_quality_customers_never_invoiced_message": (
            "{count} customers have never been invoiced."
        ),
        "insight_data_quality_invoices_missing_due_date_message": (
            "{count} invoices have no due date on file."
        ),
        "insight_data_quality_products_never_invoiced_message": (
            "{count} products have never been invoiced."
        ),
        "insight_data_quality_products_dormant_message": (
            "{count} products haven't sold in over 90 days."
        ),
        "insight_top_product_title": "{product} is your top performer in {currency}",
        "insight_top_product_message": (
            "{product} generated {currency} {amount} in total revenue across "
            "{count} invoices."
        ),
        "insight_product_decline_title": "{product} revenue down {percentage}%",
        "insight_product_decline_message": (
            "{product} generated {currency} {this_month} this month, down from "
            "{currency} {last_month} last month ({percentage}%)."
        ),
        "insight_product_decline_suggestion": (
            "Consider checking in with customers who used to buy {product}."
        ),
        "insight_product_growth_title": "{product} revenue up {percentage}%",
        "insight_product_growth_message": (
            "{product} generated {currency} {this_month} this month, up from "
            "{currency} {last_month} last month ({percentage}%)."
        ),
        "insight_due_soon_title": "{count} invoices due soon in {currency}",
        "insight_due_soon_message": (
            "{count} invoices totaling {currency} {amount} are due within the next "
            "{days} days. The soonest, {soonest_invoice}, is due {soonest_due_date}."
        ),
        "insight_due_soon_suggestion": (
            "Consider sending a payment reminder before these come due."
        ),
        "payment_terms_label": "Payment Terms",
        "payment_terms_on_receipt": "Due on receipt",
        "payment_terms_net_days": "Net {days} days",
        "payment_terms_none": "—",
        "reminder_before_due_subject": "Reminder: Invoice {invoice_number} due soon",
        "reminder_before_due_greeting": "Hello {name},",
        "reminder_before_due_intro": (
            "This is a friendly reminder that your invoice is due in {days} day(s)."
        ),
        "reminder_due_today_subject": "Reminder: Invoice {invoice_number} due today",
        "reminder_due_today_greeting": "Hello {name},",
        "reminder_due_today_intro": "This is a friendly reminder that your invoice is due today.",
        "reminder_after_due_subject": "Overdue: Invoice {invoice_number}",
        "reminder_after_due_greeting": "Hello {name},",
        "reminder_after_due_intro": (
            "Our records show this invoice is now {days} day(s) past its due date."
        ),
        "reminder_invoice_number_label": "Invoice Number:",
        "reminder_due_date_label": "Due Date:",
        "reminder_total_label": "Amount Due:",
        "reminder_closing": "Please let us know if you have any questions.",
        "reminder_thanks": "Thank you.",
        "quote_title": "Quote",
        "quote_no_label": "Quote No.",
        "quote_expiry_date_label": "Expiry Date",
        "quote_status_label": "Status",
        "status_draft": "Draft",
        "status_sent": "Sent",
        "status_accepted": "Accepted",
        "status_rejected": "Rejected",
        "status_expired": "Expired",
        "status_converted": "Converted",
        "quote_email_subject": "Quote {quote_number}",
        "quote_email_intro": "Please find your quote attached.",
        "quote_email_number_label": "Quote Number:",
        "quote_email_expiry_date_label": "Expiry Date:",
        "quote_email_accept_label": "Accept this quote:",
        "quote_email_reject_label": "Reject this quote:",
        "quote_reminder_before_expiry_subject": "Reminder: Quote {quote_number} expires soon",
        "quote_reminder_before_expiry_greeting": "Hello {name},",
        "quote_reminder_before_expiry_intro": (
            "This is a friendly reminder that your quote expires in {days} day(s)."
        ),
        "insight_quotes_pending_title": "{count} quotes awaiting response",
        "insight_quotes_pending_message": (
            "{count} quotes totaling {currency} {amount} have been sent and are "
            "still awaiting a response."
        ),
        "insight_quotes_pending_suggestion": "Consider following up with these customers.",
        "insight_quotes_expiring_title": "{count} quotes expiring soon in {currency}",
        "insight_quotes_expiring_message": (
            "{count} quotes totaling {currency} {amount} expire within the next "
            "{days} days."
        ),
        "insight_quotes_expiring_suggestion": "Follow up before these quotes expire.",
        "insight_quote_acceptance_rate_title": "Quote acceptance rate: {percentage}%",
        "insight_quote_acceptance_rate_message": (
            "Of your decided quotes, {percentage}% have been accepted."
        ),
        "insight_quote_rejection_trend_title": "Rising quote rejections",
        "insight_quote_rejection_trend_message": (
            "{count} quotes were rejected this month, more than usual."
        ),
        "insight_quote_rejection_trend_suggestion": (
            "Consider reviewing your recent quote pricing or terms."
        ),
        "insight_quotes_converted_title": "{count} quotes converted to invoices this month",
        "insight_quotes_converted_message": (
            "{count} accepted quotes were converted into invoices this month."
        ),
        "insight_repeated_rejections_title": "Repeated rejections from {customer}",
        "insight_repeated_rejections_message": (
            "{customer} has rejected {count} quotes."
        ),
        "insight_repeated_rejections_suggestion": (
            "Consider reaching out to understand their concerns before quoting again."
        ),
        "assistant_quotes_pending_heading": "Quotes Awaiting Response",
        "assistant_no_quotes_pending": "No quotes are currently awaiting a response.",
        "assistant_quotes_expired_heading": "Expired Quotes",
        "assistant_no_quotes_expired": "No expired quotes.",
        "assistant_quote_conversion_rate_label": (
            "Quote conversion rate: {percentage}% of decided quotes (accepted vs. rejected) have been accepted"
        ),
    },
    "es": {
        "invoice_title": "Factura",
        "invoice_no_label": "Nº de factura",
        "created_label": "Fecha de emisión",
        "due_date_label": "Fecha de vencimiento",
        "payment_status_label": "Estado",
        "from_label": "Emisor",
        "bill_to_label": "Cliente",
        "line_description_label": "Descripción",
        "line_quantity_label": "Cantidad",
        "line_unit_price_label": "Precio unitario",
        "line_total_label": "Total de línea",
        "subtotal_label": "Subtotal",
        "tax_amount_label": "Impuesto",
        "total_label": "Total",
        "no_customer": "Sin cliente registrado",
        "status_pending": "Pendiente",
        "status_paid": "Pagada",
        "status_overdue": "Vencida",
        "email_subject": "Factura {invoice_number}",
        "email_greeting": "Hola {name},",
        "email_intro": "Adjuntamos su factura.",
        "email_invoice_number_label": "Número de factura:",
        "email_due_date_label": "Fecha de vencimiento:",
        "email_total_label": "Total:",
        "email_payment_status_label": "Estado de pago:",
        "email_thanks": "Gracias.",
        "password_reset_subject": "Restablece tu contraseña",
        "password_reset_greeting": "Hola,",
        "password_reset_instructions": "Recibimos una solicitud para restablecer tu contraseña.",
        "password_reset_link_label": "Restablece tu contraseña:",
        "password_reset_expiry": "Este enlace expira en 30 minutos.",
        "password_reset_ignore": (
            "Si no solicitaste esto, puedes ignorar este correo de forma segura."
        ),
        "verification_subject": "Verifica tu dirección de correo",
        "verification_greeting": "Hola,",
        "verification_instructions": (
            "Por favor confirma tu dirección de correo para terminar de configurar tu cuenta."
        ),
        "verification_link_label": "Verifica tu correo:",
        "verification_expiry": "Este enlace expira en 24 horas.",
        "verification_ignore": (
            "Si no creaste una cuenta, puedes ignorar este correo de forma segura."
        ),
        "assistant_no_data_note": "Esta empresa aún no tiene facturas ni clientes.",
        "assistant_org_label": "Empresa",
        "assistant_total_invoices_label": "Facturas totales",
        "assistant_total_customers_label": "Clientes totales",
        "assistant_revenue_heading": "Ingresos por moneda",
        "assistant_no_exchange_rate_note": (
            "No se ha realizado ninguna conversión de tipo de cambio entre monedas: "
            "los montos en distintas monedas nunca se suman entre sí."
        ),
        "assistant_this_month_label": "este mes",
        "assistant_last_month_label": "mes anterior",
        "assistant_growth_label": "crecimiento",
        "assistant_invoice_status_heading": "Facturas por estado",
        "assistant_recent_invoices_heading": "Facturas recientes",
        "assistant_overdue_invoices_heading": "Facturas vencidas",
        "assistant_no_overdue_invoices": "No hay facturas vencidas.",
        "assistant_due_soon_invoices_heading": "Facturas que vencen pronto",
        "assistant_no_due_soon_invoices": "No hay facturas que venzan pronto.",
        "assistant_reminders_sent_label": (
            "{count} recordatorios de pago enviados en los últimos {days} días"
        ),
        "assistant_top_customers_heading": "Mejores clientes por ingresos",
        "assistant_top_products_heading": "Mejores productos y servicios por ingresos",
        "assistant_products_label": "Productos",
        "assistant_services_label": "Servicios",
        "assistant_dormant_products_heading": "Productos que dejaron de venderse",
        "assistant_no_dormant_products": "Ningún producto ha dejado de venderse recientemente.",
        "assistant_days_since_last_sale": "{days} días desde la última venta",
        "assistant_stale_customers_heading": "Clientes sin facturar recientemente",
        "assistant_no_stale_customers": "Todos los clientes han sido facturados recientemente.",
        "assistant_never_invoiced": "nunca facturado",
        "assistant_days_since_invoice": "{days} días desde la última factura",
        "assistant_monthly_revenue_heading": "Ingresos mensuales (últimos 6 meses, por moneda)",
        "assistant_monthly_volume_heading": (
            "Volumen mensual de facturas (últimos 6 meses, todas las monedas combinadas — es un conteo, no dinero)"
        ),
        "import_template_name_label": "Nombre",
        "import_template_email_label": "Correo electrónico",
        "import_template_phone_label": "Teléfono",
        "import_template_address_label": "Dirección",
        "import_template_example_name": "Acme S.A.",
        "import_template_example_email": "facturacion@ejemplo.com",
        "import_template_example_phone": "+598 99 123 456",
        "import_template_example_address": "Av. Principal 123, Montevideo",
        "import_template_example_tax_id": "12345678-9",
        "import_product_template_name_label": "Nombre",
        "import_product_template_description_label": "Descripción",
        "import_product_template_type_label": "Tipo",
        "import_product_template_sku_label": "SKU",
        "import_product_template_price_label": "Precio predeterminado",
        "import_product_template_currency_label": "Moneda",
        "import_product_template_tax_rate_label": "Impuesto predeterminado",
        "import_product_template_example_name": "Hosting - Premium",
        "import_product_template_example_description": "Plan de hosting premium mensual",
        "import_product_template_example_type": "servicio",
        "import_product_template_example_sku": "HOST-PREM",
        "import_product_template_example_price": "49.00",
        "import_product_template_example_tax_rate": "0.10",
        "insight_no_invoices_title": "Aún no hay facturas",
        "insight_no_invoices_message": (
            "Todavía no has creado ninguna factura — cuando lo hagas, aquí verás "
            "información sobre ingresos, pagos vencidos y tus clientes."
        ),
        "insight_no_invoices_suggestion": "Crea tu primera factura para comenzar.",
        "insight_first_invoice_title": "Primera factura creada",
        "insight_first_invoice_message": (
            "Creaste tu primera factura. A medida que agregues más, aquí comenzarás "
            "a ver tendencias y comparaciones."
        ),
        "insight_revenue_first_month_title": "Primer mes con ingresos en {currency}",
        "insight_revenue_first_month_message": (
            "Registraste {currency} {amount} en ingresos este mes — todavía no hay "
            "un mes anterior con el que compararlo."
        ),
        "insight_revenue_increase_title": "Los ingresos en {currency} subieron {percentage}%",
        "insight_revenue_increase_message": (
            "Los ingresos en {currency} este mes son {this_month}, frente a "
            "{last_month} el mes pasado ({percentage}%)."
        ),
        "insight_revenue_decline_title": "Los ingresos en {currency} bajaron {percentage}%",
        "insight_revenue_decline_message": (
            "Los ingresos en {currency} este mes son {this_month}, frente a "
            "{last_month} el mes pasado ({percentage}%)."
        ),
        "insight_revenue_stable_title": "Los ingresos en {currency} se mantienen estables",
        "insight_revenue_stable_message": (
            "Los ingresos en {currency} este mes son {this_month}, cerca de los "
            "{last_month} del mes pasado."
        ),
        "insight_revenue_decline_suggestion": (
            "Revisa las facturas recientes y la actividad de los clientes para entender el cambio."
        ),
        "insight_revenue_ask_question": "Explica por qué cambiaron los ingresos en {currency} este mes.",
        "insight_overdue_title": "{count} facturas vencidas en {currency}",
        "insight_overdue_message": (
            "{count} facturas por un total de {currency} {amount} están vencidas. "
            "La más antigua, {oldest_invoice}, lleva {oldest_days} días vencida; la "
            "más grande es {largest_invoice} por {currency} {largest_amount}."
        ),
        "insight_overdue_suggestion": (
            "Da seguimiento primero a las facturas vencidas más antiguas o más grandes."
        ),
        "insight_pending_title": "Saldo pendiente alto en {currency}",
        "insight_pending_message": (
            "{currency} {amount} sigue pendiente de pago — el {percentage}% de los "
            "ingresos totales en esta moneda."
        ),
        "insight_pending_suggestion": (
            "Revisa las facturas pendientes y considera dar seguimiento a los clientes."
        ),
        "insight_concentration_title": "Ingresos concentrados en un cliente ({currency})",
        "insight_concentration_message": (
            "{customer} representa el {percentage}% de tus ingresos en {currency}."
        ),
        "insight_concentration_suggestion": (
            "Considera diversificar tu base de clientes para reducir este riesgo."
        ),
        "insight_concentration_ask_question": "Ayúdame a reducir el riesgo de concentración de clientes.",
        "insight_inactivity_title": "{count} clientes sin actividad reciente",
        "insight_inactivity_message": (
            "{count} clientes antes activos no han sido facturados en un tiempo — "
            "{customer} es quien más tiempo lleva, con {days} días."
        ),
        "insight_inactivity_suggestion": "Considera contactarlos para saber cómo están.",
        "insight_inactivity_ask_question": (
            "¿A qué clientes inactivos debería dar seguimiento, empezando por {customer}?"
        ),
        "insight_volume_first_month_title": "Primer mes con facturas",
        "insight_volume_first_month_message": (
            "Creaste {count} facturas este mes — todavía no hay un mes anterior con "
            "el que compararlo."
        ),
        "insight_volume_increase_title": "El volumen de facturas subió {percentage}%",
        "insight_volume_decrease_title": "El volumen de facturas bajó {percentage}%",
        "insight_volume_message": (
            "Creaste {this_month} facturas este mes, frente a {last_month} el mes pasado."
        ),
        "insight_status_high_overdue_title": "Alta proporción de facturas vencidas",
        "insight_status_high_overdue_message": (
            "{overdue} de tus {total} facturas ({percentage}%) están vencidas."
        ),
        "insight_status_all_pending_title": "Todas las facturas siguen pendientes",
        "insight_status_all_pending_message": (
            "Las {count} facturas que tienes siguen pendientes de pago."
        ),
        "insight_status_no_paid_title": "Aún no se ha pagado ninguna factura",
        "insight_status_no_paid_message": (
            "Ninguna de tus facturas se ha pagado todavía, y {overdue} están vencidas."
        ),
        "insight_status_mostly_paid_title": "La mayoría de las facturas están pagadas",
        "insight_status_mostly_paid_message": (
            "{paid} de tus {total} facturas ({percentage}%) están pagadas."
        ),
        "insight_multi_currency_title": "Ingresos registrados en {count} monedas",
        "insight_multi_currency_message": (
            "Tienes ingresos en {currencies}. Los montos siempre se registran por "
            "separado en cada moneda y nunca se combinan."
        ),
        "insight_data_quality_title": "Algunos detalles para ordenar",
        "insight_data_quality_invoices_without_customer_message": (
            "{count} facturas no tienen un cliente asociado."
        ),
        "insight_data_quality_customers_missing_phone_message": (
            "{count} clientes no tienen un teléfono registrado."
        ),
        "insight_data_quality_customers_never_invoiced_message": (
            "{count} clientes nunca han sido facturados."
        ),
        "insight_data_quality_invoices_missing_due_date_message": (
            "{count} facturas no tienen una fecha de vencimiento registrada."
        ),
        "insight_data_quality_products_never_invoiced_message": (
            "{count} productos nunca han sido facturados."
        ),
        "insight_data_quality_products_dormant_message": (
            "{count} productos no se han vendido en más de 90 días."
        ),
        "insight_top_product_title": "{product} es tu producto más vendido en {currency}",
        "insight_top_product_message": (
            "{product} generó {currency} {amount} en ingresos totales en "
            "{count} facturas."
        ),
        "insight_product_decline_title": "Los ingresos de {product} bajaron {percentage}%",
        "insight_product_decline_message": (
            "{product} generó {currency} {this_month} este mes, frente a "
            "{currency} {last_month} el mes pasado ({percentage}%)."
        ),
        "insight_product_decline_suggestion": (
            "Considera contactar a los clientes que solían comprar {product}."
        ),
        "insight_product_growth_title": "Los ingresos de {product} subieron {percentage}%",
        "insight_product_growth_message": (
            "{product} generó {currency} {this_month} este mes, frente a "
            "{currency} {last_month} el mes pasado ({percentage}%)."
        ),
        "insight_due_soon_title": "{count} facturas vencen pronto en {currency}",
        "insight_due_soon_message": (
            "{count} facturas por un total de {currency} {amount} vencen dentro de los "
            "próximos {days} días. La más próxima, {soonest_invoice}, vence el {soonest_due_date}."
        ),
        "insight_due_soon_suggestion": (
            "Considera enviar un recordatorio de pago antes de que venzan."
        ),
        "payment_terms_label": "Términos de pago",
        "payment_terms_on_receipt": "Pago al recibir",
        "payment_terms_net_days": "Neto {days} días",
        "payment_terms_none": "—",
        "reminder_before_due_subject": "Recordatorio: Factura {invoice_number} vence pronto",
        "reminder_before_due_greeting": "Hola {name},",
        "reminder_before_due_intro": (
            "Este es un recordatorio de que su factura vence en {days} día(s)."
        ),
        "reminder_due_today_subject": "Recordatorio: Factura {invoice_number} vence hoy",
        "reminder_due_today_greeting": "Hola {name},",
        "reminder_due_today_intro": "Este es un recordatorio de que su factura vence hoy.",
        "reminder_after_due_subject": "Vencida: Factura {invoice_number}",
        "reminder_after_due_greeting": "Hola {name},",
        "reminder_after_due_intro": (
            "Nuestros registros muestran que esta factura lleva {days} día(s) vencida."
        ),
        "reminder_invoice_number_label": "Número de factura:",
        "reminder_due_date_label": "Fecha de vencimiento:",
        "reminder_total_label": "Monto adeudado:",
        "reminder_closing": "No dude en contactarnos si tiene alguna pregunta.",
        "reminder_thanks": "Gracias.",
        "quote_title": "Presupuesto",
        "quote_no_label": "Nº de presupuesto",
        "quote_expiry_date_label": "Fecha de vencimiento",
        "quote_status_label": "Estado",
        "status_draft": "Borrador",
        "status_sent": "Enviado",
        "status_accepted": "Aceptado",
        "status_rejected": "Rechazado",
        "status_expired": "Vencido",
        "status_converted": "Convertido",
        "quote_email_subject": "Presupuesto {quote_number}",
        "quote_email_intro": "Adjuntamos su presupuesto.",
        "quote_email_number_label": "Número de presupuesto:",
        "quote_email_expiry_date_label": "Fecha de vencimiento:",
        "quote_email_accept_label": "Aceptar este presupuesto:",
        "quote_email_reject_label": "Rechazar este presupuesto:",
        "quote_reminder_before_expiry_subject": "Recordatorio: El presupuesto {quote_number} vence pronto",
        "quote_reminder_before_expiry_greeting": "Hola {name},",
        "quote_reminder_before_expiry_intro": (
            "Este es un recordatorio de que su presupuesto vence en {days} día(s)."
        ),
        "insight_quotes_pending_title": "{count} presupuestos esperando respuesta",
        "insight_quotes_pending_message": (
            "{count} presupuestos por un total de {currency} {amount} fueron enviados "
            "y siguen esperando una respuesta."
        ),
        "insight_quotes_pending_suggestion": "Considera dar seguimiento a estos clientes.",
        "insight_quotes_expiring_title": "{count} presupuestos vencen pronto en {currency}",
        "insight_quotes_expiring_message": (
            "{count} presupuestos por un total de {currency} {amount} vencen dentro "
            "de los próximos {days} días."
        ),
        "insight_quotes_expiring_suggestion": "Da seguimiento antes de que venzan estos presupuestos.",
        "insight_quote_acceptance_rate_title": "Tasa de aceptación de presupuestos: {percentage}%",
        "insight_quote_acceptance_rate_message": (
            "De tus presupuestos decididos, el {percentage}% fueron aceptados."
        ),
        "insight_quote_rejection_trend_title": "Aumento de presupuestos rechazados",
        "insight_quote_rejection_trend_message": (
            "Se rechazaron {count} presupuestos este mes, más de lo habitual."
        ),
        "insight_quote_rejection_trend_suggestion": (
            "Considera revisar los precios o condiciones de tus presupuestos recientes."
        ),
        "insight_quotes_converted_title": "{count} presupuestos convertidos a facturas este mes",
        "insight_quotes_converted_message": (
            "{count} presupuestos aceptados se convirtieron en facturas este mes."
        ),
        "insight_repeated_rejections_title": "Rechazos repetidos de {customer}",
        "insight_repeated_rejections_message": (
            "{customer} ha rechazado {count} presupuestos."
        ),
        "insight_repeated_rejections_suggestion": (
            "Considera contactarlo para entender sus inquietudes antes de volver a cotizar."
        ),
        "assistant_quotes_pending_heading": "Presupuestos Esperando Respuesta",
        "assistant_no_quotes_pending": "No hay presupuestos esperando respuesta actualmente.",
        "assistant_quotes_expired_heading": "Presupuestos Vencidos",
        "assistant_no_quotes_expired": "No hay presupuestos vencidos.",
        "assistant_quote_conversion_rate_label": (
            "Tasa de conversión de presupuestos: {percentage}% de los presupuestos decididos "
            "(aceptados vs. rechazados) fueron aceptados"
        ),
    },
}


def get_language(organization: "Organization | Invoice | None" = None) -> str:
    """Returns the language code to use. Accepts either an Organization
    (its configured default) or an Invoice (its permanently-pinned
    language) — both just need a .language attribute, so this one function
    serves both without duplication. Falls back to the safe default if
    nothing is given, or the value is somehow unrecognized."""
    language = getattr(organization, "language", None) if organization is not None else None
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def t(language: str, key: str) -> str:
    """Looks up a translated string, falling back to English if the key or
    language is somehow missing (shouldn't happen for supported languages)."""
    table = _TRANSLATIONS.get(language, _TRANSLATIONS[DEFAULT_LANGUAGE])
    return table.get(key, _TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))


def payment_status_label(language: str, status: PaymentStatus) -> str:
    return t(language, f"status_{status.value}")


def quote_status_label(language: str, status: QuoteStatus) -> str:
    return t(language, f"status_{status.value}")
