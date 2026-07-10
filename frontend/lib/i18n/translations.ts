/**
 * Centralized frontend translations. Namespaced by concern, not by page:
 * common.* (shared actions/fields/validation reused across pages), nav.*
 * (main navigation), sort.* / status.* (shared SortControl and payment
 * status copy), invoices.* / dashboard.* / customers.* / settings.* (page
 * chrome for each authenticated page), auth.* (login/register), landing.*
 * (public landing page).
 *
 * common.*, sort.*, and status.* are intentionally reused across pages
 * (e.g. dashboard's recent-invoices table reuses invoices.col*, Customers'
 * "Reset filters" reuses invoices.resetFilters, Settings' "Organization
 * name" reuses auth.organizationNameLabel) instead of redeclaring
 * identical strings per page.
 */

export const SUPPORTED_LANGUAGES = ["en", "es"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];
export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

/** Returns value if it's a supported language code, else the default. Shared
 * by every language-resolution source (organization setting, marketing-page
 * localStorage key, browser detection) so they all agree on what counts as
 * "supported". */
export function normalizeLanguage(value: string | null | undefined): SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value ?? "")
    ? (value as SupportedLanguage)
    : DEFAULT_LANGUAGE;
}

/** Looks up key in the given language table, falling back to English and
 * then the raw key, interpolating {placeholder} params. The single lookup
 * implementation shared by every t() function in the app, regardless of how
 * each caller resolves its active language. */
export function translate(
  language: SupportedLanguage,
  key: string,
  params?: Record<string, string | number>
): string {
  const table = TRANSLATIONS[language] ?? TRANSLATIONS[DEFAULT_LANGUAGE];
  let value = table[key] ?? TRANSLATIONS[DEFAULT_LANGUAGE][key] ?? key;
  if (params) {
    for (const [placeholder, replacement] of Object.entries(params)) {
      value = value.replaceAll(`{${placeholder}}`, String(replacement));
    }
  }
  return value;
}

export const TRANSLATIONS: Record<SupportedLanguage, Record<string, string>> = {
  en: {
    "nav.dashboard": "Dashboard",
    "nav.invoices": "Invoices",
    "nav.customers": "Customers",
    "nav.settings": "Settings",
    "nav.logout": "Log out",

    "invoices.title": "Invoices",
    "invoices.subtitle": "Newest first. Update payment status inline.",
    "invoices.newInvoice": "New invoice",
    "invoices.searchPlaceholder": "Search by invoice number or customer name…",
    "invoices.searchAriaLabel": "Search invoices",
    "invoices.filterStatusAriaLabel": "Filter by payment status",
    "invoices.allStatuses": "All statuses",
    "invoices.filterDateAriaLabel": "Filter by date range",
    "invoices.dateAll": "All time",
    "invoices.dateToday": "Today",
    "invoices.dateWeek": "This week",
    "invoices.dateMonth": "This month",
    "invoices.dateYear": "This year",
    "invoices.minTotalPlaceholder": "Min total",
    "invoices.maxTotalPlaceholder": "Max total",
    "invoices.minTotalAriaLabel": "Minimum total",
    "invoices.maxTotalAriaLabel": "Maximum total",
    "invoices.sortCreatedDate": "Created date",
    "invoices.sortInvoiceNumber": "Invoice number",
    "invoices.sortTotalAmount": "Total amount",
    "invoices.sortCustomerName": "Customer name",
    "invoices.resetFilters": "Reset filters",
    "invoices.colInvoice": "Invoice",
    "invoices.colCustomer": "Customer",
    "invoices.colStatus": "Status",
    "invoices.colSubtotal": "Subtotal",
    "invoices.colTax": "Tax",
    "invoices.colTotal": "Total",
    "invoices.colCreated": "Created",
    "invoices.colActions": "Actions",
    "invoices.loading": "Loading…",
    "invoices.noMatch": "No invoices match your filters.",
    "invoices.noneYet": "No invoices yet.",
    "invoices.downloadPdf": "Download PDF",
    "invoices.preparing": "Preparing…",
    "invoices.sendEmail": "Send Email",
    "invoices.sending": "Sending…",
    "invoices.pagination": "Page {page} of {totalPages} · {total} total",
    "invoices.previous": "Previous",
    "invoices.next": "Next",
    "invoices.toastPreparingPdf": "Preparing PDF…",
    "invoices.toastPdfDownloaded": "PDF downloaded.",
    "invoices.toastPdfError": "Could not download PDF.",
    "invoices.toastSendingEmail": "Sending email…",
    "invoices.toastEmailSent": "Invoice {number} emailed to {email}.",
    "invoices.toastEmailError": "Could not send invoice email.",

    "sort.by": "Sort by",
    "sort.prefix": "Sort",
    "sort.direction": "Sort direction",
    "sort.ascending": "Ascending",
    "sort.descending": "Descending",

    "status.pending": "Pending",
    "status.paid": "Paid",
    "status.overdue": "Overdue",
    "status.ariaLabel": "Payment status",
    "status.updating": "Updating payment status…",
    "status.updated": "Status set to {status}.",
    "status.updateError": "Could not update payment status.",

    "common.languageAriaLabel": "Language",
    "common.refresh": "Refresh",
    "common.refreshing": "Refreshing…",
    "common.saveChanges": "Save changes",
    "common.saving": "Saving…",
    "common.clear": "Clear",
    "common.loadingLabel": "Loading {label}",
    "common.name": "Name",
    "common.email": "Email",
    "common.phone": "Phone",
    "common.address": "Address",
    "common.errorRequired": "{field} is required.",
    "common.errorMaxLength": "{field} must be at most {max} characters.",
    "common.errorInvalidEmail": "Enter a valid email address.",

    "landing.nav.signIn": "Sign in",
    "landing.nav.getStarted": "Get started",

    "landing.hero.headline": "Invoicing that keeps your business paid on time",
    "landing.hero.subtitle":
      "Create, send, and track invoices in minutes — with PDF generation, email delivery, and a real-time dashboard, all in one place.",
    "landing.hero.startFree": "Start free",
    "landing.hero.signIn": "Sign in",

    "landing.features.heading": "Everything you need to invoice, in one app",
    "landing.features.subtitle":
      "No bloated feature set — just the pieces a small business actually uses.",
    "landing.features.customers.title": "Customers & invoices",
    "landing.features.customers.description":
      "Keep a clean record of every customer and invoice, scoped to your organization from day one.",
    "landing.features.search.title": "Search, filter, and sort",
    "landing.features.search.description":
      "Find any invoice in seconds — by customer, status, date range, or amount — without digging through pages.",
    "landing.features.pdf.title": "PDF invoices",
    "landing.features.pdf.description":
      "Every invoice generates a clean, printable PDF with your business details and tax ID, ready to send.",
    "landing.features.email.title": "Email delivery",
    "landing.features.email.description":
      "Send an invoice straight to your customer's inbox, PDF attached, in one click — no separate mail client needed.",
    "landing.features.localization.title": "Multi-language & currency",
    "landing.features.localization.description":
      "Set your organization's language and currency once — invoices, emails, and PDFs follow automatically.",
    "landing.features.analytics.title": "Dashboard analytics",
    "landing.features.analytics.description":
      "Revenue trends, payment status breakdown, and your top customers, updated the moment an invoice changes.",

    "landing.steps.heading": "How it works",
    "landing.steps.subtitle": "From sign-up to a paid invoice, in four steps.",
    "landing.steps.step1.title": "Create your organization",
    "landing.steps.step1.description":
      "Sign up and set your business name, tax ID, language, and currency.",
    "landing.steps.step2.title": "Add customers & invoices",
    "landing.steps.step2.description":
      "Build an invoice with line items — subtotal, tax, and total are calculated for you.",
    "landing.steps.step3.title": "Send it",
    "landing.steps.step3.description": "Download the PDF or email it directly to your customer.",
    "landing.steps.step4.title": "Track payments",
    "landing.steps.step4.description":
      "Mark invoices paid, pending, or overdue, and watch your dashboard update in real time.",

    "landing.analytics.heading": "Know where your business stands, at a glance",
    "landing.analytics.description":
      "The dashboard turns your invoices into answers: how much revenue came in this month versus last, which invoices are overdue, and which customers bring in the most business — updated the moment something changes.",
    "landing.analytics.point1": "Revenue trend over the last six months",
    "landing.analytics.point2": "Payment status breakdown: pending, paid, overdue",
    "landing.analytics.point3": "Your top customers by revenue",
    "landing.analytics.mock.totalRevenue": "Total revenue",
    "landing.analytics.mock.invoices": "Invoices",
    "landing.analytics.mock.paymentStatus": "Payment status",

    "landing.pdfEmail.heading": "A clean PDF, delivered by email",
    "landing.pdfEmail.description":
      "Every invoice is available as a printable PDF with your business name, tax ID, and line items laid out clearly. Send it with one click and it lands in your customer's inbox with the PDF already attached — subject and body translated to your organization's language.",
    "landing.pdfEmail.mock.invoiceNo": "Invoice No.",
    "landing.pdfEmail.mock.billTo": "Bill To",

    "landing.pricing.heading": "Simple pricing",
    "landing.pricing.subtitle": "Start free. Upgrade only if you outgrow it.",
    "landing.pricing.free.title": "Free",
    "landing.pricing.free.tagline": "For getting started",
    "landing.pricing.free.feature1": "Unlimited customers & invoices",
    "landing.pricing.free.feature2": "PDF generation & email delivery",
    "landing.pricing.pro.title": "Pro",
    "landing.pricing.pro.comingSoon": "Coming soon",
    "landing.pricing.pro.tagline": "For growing teams",
    "landing.pricing.pro.feature1": "Everything in Free",
    "landing.pricing.pro.feature2": "Team roles & permissions",
    "landing.pricing.pro.feature3": "Priority support",
    "landing.pricing.pro.notifyMe": "Notify me",

    "landing.faq.heading": "Frequently asked questions",
    "landing.faq.q1.question": "Is my organization's data isolated from others?",
    "landing.faq.q1.answer":
      "Yes. Every customer, invoice, and setting is scoped to your organization — every request is checked against your membership before any data is returned.",
    "landing.faq.q2.question": "What languages and currencies are supported?",
    "landing.faq.q2.answer":
      "English and Spanish today, with USD, UYU, and EUR currency support. Set both in your organization settings — invoice PDFs and emails follow automatically.",
    "landing.faq.q3.question": "How do customers actually receive an invoice?",
    "landing.faq.q3.answer":
      "Download the generated PDF yourself, or send it directly — the same PDF goes out as an email attachment to your customer's address.",
    "landing.faq.q4.question": "Do I need a credit card to start?",
    "landing.faq.q4.answer":
      "No. Create an account and organization for free — no payment details required.",

    "landing.cta.heading": "Ready to send your first invoice?",

    "landing.footer.rights": "All rights reserved.",

    "auth.signIn": "Sign in",
    "auth.createAccount": "Create account",
    "auth.headingRegister": "Create your organization",
    "auth.subtitleSignIn": "Sign in with your email and password.",
    "auth.subtitleRegister": "This creates your account and a new organization.",
    "auth.emailPlaceholder": "you@example.com",
    "auth.passwordLabel": "Password",
    "auth.passwordPlaceholderRegister": "At least 8 characters",
    "auth.organizationNameLabel": "Organization name",
    "auth.organizationNamePlaceholder": "Acme Inc.",
    "auth.advancedSummary": "Advanced: API base URL",
    "auth.errorFillAllFields": "Please fill in all fields.",
    "auth.errorOrganizationNameRequired": "Please enter an organization name.",
    "auth.errorPasswordLength": "Password must be at least 8 characters.",
    "auth.errorNoOrganization": "No organization found for this account.",
    "auth.errorSignInFailed": "Could not sign in.",
    "auth.errorRegisterFailed": "Could not create account.",
    "auth.errorGeneric": "Something went wrong. Please try again.",
    "auth.signingIn": "Signing in…",
    "auth.creatingAccount": "Creating account…",

    "dashboard.title": "Dashboard",
    "dashboard.subtitle": "Overview of invoices, revenue, and customers for your organization.",
    "dashboard.loadError": "Failed to load dashboard",
    "dashboard.summaryAriaLabel": "Summary",
    "dashboard.revenueLabel": "Revenue",
    "dashboard.totalRevenueTitle": "Total revenue",
    "dashboard.totalRevenueDescription": "Sum of all invoice totals",
    "dashboard.totalInvoicesTitle": "Total invoices",
    "dashboard.totalInvoicesDescription": "All invoices in this organization",
    "dashboard.totalCustomersTitle": "Total customers",
    "dashboard.totalCustomersDescription": "Active customer records",
    "dashboard.emptyTitle": "No invoices yet",
    "dashboard.emptyDescription":
      "Create your first invoice to see revenue trends, status breakdowns, and activity on this dashboard.",
    "dashboard.createInvoiceCta": "Create invoice",
    "dashboard.revenueStatusAriaLabel": "Revenue and status breakdown",
    "dashboard.analyticsHeading": "Analytics",
    "dashboard.recentInvoicesHeading": "Recent invoices",
    "dashboard.recentInvoicesSubtitle": "Latest 5 invoices, newest first.",
    "dashboard.viewAll": "View all →",
    "dashboard.revenueTrendTitle": "Revenue trend",
    "dashboard.revenueTrendNoPriorData": "No prior data",
    "dashboard.revenueTrendThisMonth": "This month",
    "dashboard.revenueTrendLastMonth": "Last month",
    "dashboard.revenueTrendChartTitle": "Revenue trend (6 months)",
    "dashboard.chartEmptyNoRevenue": "No revenue yet. This chart fills in as invoices are created.",
    "dashboard.invoiceVolumeTitle": "Invoice volume (6 months)",
    "dashboard.chartEmptyNoInvoices": "No invoices yet. This chart fills in as invoices are created.",
    "dashboard.paymentStatusChartTitle": "Invoices by status",
    "dashboard.paymentStatusBreakdownTitle": "Payment status",
    "dashboard.paymentStatusBreakdownEmpty":
      "No invoices yet. Status breakdown will appear here once you create one.",
    "dashboard.topCustomersTitle": "Top customers by revenue",
    "dashboard.topCustomersEmpty":
      "No customer revenue yet. Attach a customer to an invoice to see them here.",

    "customers.title": "Customers",
    "customers.subtitle": "Members of the selected organization.",
    "customers.loadError": "Failed to load customers",
    "customers.searchAriaLabel": "Search customers",
    "customers.searchPlaceholder": "Search by name, email, or phone…",
    "customers.loading": "Loading customers…",
    "customers.emptyFilteredTitle": "No customers match your search",
    "customers.emptyFilteredDescription": "Try a different name, email, or phone number.",
    "customers.emptyTitle": "No customers yet",
    "customers.emptyDescription":
      "Add your first customer using the form above. They will appear in this list and can be selected when you create invoices.",
    "customers.addTitle": "Add customer",
    "customers.addSubtitle": "New customers are scoped to your current organization.",
    "customers.createButton": "Create customer",
    "customers.toastCreating": "Creating customer…",
    "customers.toastCreated": "Customer created.",
    "customers.toastCreateError": "Could not create customer.",

    "settings.title": "Settings",
    "settings.subtitle": "Your organization's profile. This information appears on invoice PDFs.",
    "settings.loadError": "Failed to load organization profile",
    "settings.organizationSectionTitle": "Organization",
    "settings.orgNameHelp": "Shown in the sidebar and used to identify your organization.",
    "settings.businessDetailsSectionTitle": "Business details",
    "settings.businessDetailsSubtitle": "Shown on invoice PDFs. Leave blank to omit a field.",
    "settings.businessNameLabel": "Business name",
    "settings.businessNamePlaceholder": "Defaults to organization name",
    "settings.taxIdLabel": "Tax ID",
    "settings.logoUrlLabel": "Logo URL",
    "settings.logoUrlHelp": "Stored for future use. Not currently shown on invoice PDFs.",
    "settings.localizationSectionTitle": "Localization",
    "settings.localizationSubtitle": "Controls the language and currency used on invoice PDFs and emails.",
    "settings.languageFieldLabel": "Language",
    "settings.currencyFieldLabel": "Currency",
    "settings.currencyUSD": "USD — US Dollar",
    "settings.currencyUYU": "UYU — Uruguayan Peso",
    "settings.currencyEUR": "EUR — Euro",
    "settings.taxLabelFieldLabel": "Tax ID label",
    "settings.taxLabelHelp": "Shown next to your Tax ID on invoice PDFs.",
    "settings.toastSaving": "Saving profile…",
    "settings.toastSaved": "Organization profile saved.",
    "settings.toastSaveError": "Could not save organization profile.",
  },
  es: {
    "nav.dashboard": "Panel",
    "nav.invoices": "Facturas",
    "nav.customers": "Clientes",
    "nav.settings": "Configuración",
    "nav.logout": "Cerrar sesión",

    "invoices.title": "Facturas",
    "invoices.subtitle": "Más recientes primero. Actualiza el estado de pago en línea.",
    "invoices.newInvoice": "Nueva factura",
    "invoices.searchPlaceholder": "Buscar por número de factura o nombre de cliente…",
    "invoices.searchAriaLabel": "Buscar facturas",
    "invoices.filterStatusAriaLabel": "Filtrar por estado de pago",
    "invoices.allStatuses": "Todos los estados",
    "invoices.filterDateAriaLabel": "Filtrar por rango de fechas",
    "invoices.dateAll": "Todo el tiempo",
    "invoices.dateToday": "Hoy",
    "invoices.dateWeek": "Esta semana",
    "invoices.dateMonth": "Este mes",
    "invoices.dateYear": "Este año",
    "invoices.minTotalPlaceholder": "Total mín.",
    "invoices.maxTotalPlaceholder": "Total máx.",
    "invoices.minTotalAriaLabel": "Total mínimo",
    "invoices.maxTotalAriaLabel": "Total máximo",
    "invoices.sortCreatedDate": "Fecha de creación",
    "invoices.sortInvoiceNumber": "Número de factura",
    "invoices.sortTotalAmount": "Monto total",
    "invoices.sortCustomerName": "Nombre del cliente",
    "invoices.resetFilters": "Restablecer filtros",
    "invoices.colInvoice": "Factura",
    "invoices.colCustomer": "Cliente",
    "invoices.colStatus": "Estado",
    "invoices.colSubtotal": "Subtotal",
    "invoices.colTax": "Impuesto",
    "invoices.colTotal": "Total",
    "invoices.colCreated": "Creada",
    "invoices.colActions": "Acciones",
    "invoices.loading": "Cargando…",
    "invoices.noMatch": "Ninguna factura coincide con tus filtros.",
    "invoices.noneYet": "Aún no hay facturas.",
    "invoices.downloadPdf": "Descargar PDF",
    "invoices.preparing": "Preparando…",
    "invoices.sendEmail": "Enviar correo",
    "invoices.sending": "Enviando…",
    "invoices.pagination": "Página {page} de {totalPages} · {total} en total",
    "invoices.previous": "Anterior",
    "invoices.next": "Siguiente",
    "invoices.toastPreparingPdf": "Preparando PDF…",
    "invoices.toastPdfDownloaded": "PDF descargado.",
    "invoices.toastPdfError": "No se pudo descargar el PDF.",
    "invoices.toastSendingEmail": "Enviando correo…",
    "invoices.toastEmailSent": "Factura {number} enviada por correo a {email}.",
    "invoices.toastEmailError": "No se pudo enviar el correo de la factura.",

    "sort.by": "Ordenar por",
    "sort.prefix": "Ordenar",
    "sort.direction": "Dirección de orden",
    "sort.ascending": "Ascendente",
    "sort.descending": "Descendente",

    "status.pending": "Pendiente",
    "status.paid": "Pagada",
    "status.overdue": "Vencida",
    "status.ariaLabel": "Estado de pago",
    "status.updating": "Actualizando estado de pago…",
    "status.updated": "Estado actualizado a {status}.",
    "status.updateError": "No se pudo actualizar el estado de pago.",

    "common.languageAriaLabel": "Idioma",
    "common.refresh": "Actualizar",
    "common.refreshing": "Actualizando…",
    "common.saveChanges": "Guardar cambios",
    "common.saving": "Guardando…",
    "common.clear": "Limpiar",
    "common.loadingLabel": "Cargando {label}",
    "common.name": "Nombre",
    "common.email": "Correo electrónico",
    "common.phone": "Teléfono",
    "common.address": "Dirección",
    "common.errorRequired": "{field} es obligatorio.",
    "common.errorMaxLength": "{field} debe tener como máximo {max} caracteres.",
    "common.errorInvalidEmail": "Ingresa un correo electrónico válido.",

    "landing.nav.signIn": "Iniciar sesión",
    "landing.nav.getStarted": "Comenzar",

    "landing.hero.headline": "Facturación que mantiene tu negocio al día con los pagos",
    "landing.hero.subtitle":
      "Crea, envía y controla facturas en minutos, con generación de PDF, envío por correo y un panel en tiempo real, todo en un solo lugar.",
    "landing.hero.startFree": "Empezar gratis",
    "landing.hero.signIn": "Iniciar sesión",

    "landing.features.heading": "Todo lo que necesitas para facturar, en una sola app",
    "landing.features.subtitle":
      "Sin funciones innecesarias: solo lo que una pequeña empresa realmente usa.",
    "landing.features.customers.title": "Clientes y facturas",
    "landing.features.customers.description":
      "Mantén un registro claro de cada cliente y factura, organizado por tu empresa desde el primer día.",
    "landing.features.search.title": "Buscar, filtrar y ordenar",
    "landing.features.search.description":
      "Encuentra cualquier factura en segundos, por cliente, estado, fecha o monto, sin buscar entre páginas.",
    "landing.features.pdf.title": "Facturas en PDF",
    "landing.features.pdf.description":
      "Cada factura genera un PDF claro y listo para imprimir, con los datos de tu empresa y tu identificación fiscal.",
    "landing.features.email.title": "Envío por correo",
    "landing.features.email.description":
      "Envía una factura directo al correo de tu cliente, con el PDF adjunto, en un clic, sin usar otro programa de correo.",
    "landing.features.localization.title": "Multilenguaje y multimoneda",
    "landing.features.localization.description":
      "Configura el idioma y la moneda de tu empresa una sola vez: facturas, correos y PDFs se adaptan automáticamente.",
    "landing.features.analytics.title": "Panel de análisis",
    "landing.features.analytics.description":
      "Tendencias de ingresos, estado de pagos y tus mejores clientes, actualizados al instante con cada factura.",

    "landing.steps.heading": "Cómo funciona",
    "landing.steps.subtitle": "Del registro a una factura pagada, en cuatro pasos.",
    "landing.steps.step1.title": "Crea tu empresa",
    "landing.steps.step1.description":
      "Regístrate y configura el nombre de tu empresa, identificación fiscal, idioma y moneda.",
    "landing.steps.step2.title": "Agrega clientes y facturas",
    "landing.steps.step2.description":
      "Crea una factura con líneas de detalle: el subtotal, impuesto y total se calculan por ti.",
    "landing.steps.step3.title": "Envíala",
    "landing.steps.step3.description":
      "Descarga el PDF o envíala directamente por correo a tu cliente.",
    "landing.steps.step4.title": "Controla los pagos",
    "landing.steps.step4.description":
      "Marca facturas como pagadas, pendientes o vencidas, y observa tu panel actualizarse en tiempo real.",

    "landing.analytics.heading": "Conoce el estado de tu negocio de un vistazo",
    "landing.analytics.description":
      "El panel convierte tus facturas en respuestas: cuánto ingresaste este mes frente al anterior, qué facturas están vencidas y qué clientes generan más negocio, todo actualizado al instante.",
    "landing.analytics.point1": "Tendencia de ingresos de los últimos seis meses",
    "landing.analytics.point2": "Desglose de estado de pago: pendiente, pagada, vencida",
    "landing.analytics.point3": "Tus mejores clientes por ingresos",
    "landing.analytics.mock.totalRevenue": "Ingresos totales",
    "landing.analytics.mock.invoices": "Facturas",
    "landing.analytics.mock.paymentStatus": "Estado de pago",

    "landing.pdfEmail.heading": "Un PDF claro, entregado por correo",
    "landing.pdfEmail.description":
      "Cada factura está disponible como un PDF imprimible, con el nombre de tu empresa, identificación fiscal y detalle de líneas claramente organizados. Envíala con un clic y llega al correo de tu cliente con el PDF ya adjunto, con asunto y cuerpo traducidos al idioma de tu empresa.",
    "landing.pdfEmail.mock.invoiceNo": "Nº de factura",
    "landing.pdfEmail.mock.billTo": "Cliente",

    "landing.pricing.heading": "Precios simples",
    "landing.pricing.subtitle": "Empieza gratis. Mejora tu plan solo si lo necesitas.",
    "landing.pricing.free.title": "Gratis",
    "landing.pricing.free.tagline": "Para comenzar",
    "landing.pricing.free.feature1": "Clientes y facturas ilimitados",
    "landing.pricing.free.feature2": "Generación de PDF y envío por correo",
    "landing.pricing.pro.title": "Pro",
    "landing.pricing.pro.comingSoon": "Próximamente",
    "landing.pricing.pro.tagline": "Para equipos en crecimiento",
    "landing.pricing.pro.feature1": "Todo lo del plan Gratis",
    "landing.pricing.pro.feature2": "Roles y permisos de equipo",
    "landing.pricing.pro.feature3": "Soporte prioritario",
    "landing.pricing.pro.notifyMe": "Notificarme",

    "landing.faq.heading": "Preguntas frecuentes",
    "landing.faq.q1.question": "¿Los datos de mi empresa están aislados de otras?",
    "landing.faq.q1.answer":
      "Sí. Cada cliente, factura y configuración pertenece a tu empresa: cada solicitud se verifica contra tu membresía antes de devolver cualquier dato.",
    "landing.faq.q2.question": "¿Qué idiomas y monedas son compatibles?",
    "landing.faq.q2.answer":
      "Por ahora, inglés y español, con soporte de monedas USD, UYU y EUR. Configura ambos en los ajustes de tu empresa: los PDF y correos de factura se adaptan automáticamente.",
    "landing.faq.q3.question": "¿Cómo reciben los clientes una factura?",
    "landing.faq.q3.answer":
      "Descarga el PDF generado tú mismo, o envíalo directamente: el mismo PDF se adjunta en un correo a la dirección de tu cliente.",
    "landing.faq.q4.question": "¿Necesito una tarjeta de crédito para empezar?",
    "landing.faq.q4.answer":
      "No. Crea una cuenta y una empresa gratis, sin necesidad de datos de pago.",

    "landing.cta.heading": "¿Listo para enviar tu primera factura?",

    "landing.footer.rights": "Todos los derechos reservados.",

    "auth.signIn": "Iniciar sesión",
    "auth.createAccount": "Crear cuenta",
    "auth.headingRegister": "Crea tu empresa",
    "auth.subtitleSignIn": "Inicia sesión con tu correo y contraseña.",
    "auth.subtitleRegister": "Esto crea tu cuenta y una nueva empresa.",
    "auth.emailPlaceholder": "tucorreo@ejemplo.com",
    "auth.passwordLabel": "Contraseña",
    "auth.passwordPlaceholderRegister": "Al menos 8 caracteres",
    "auth.organizationNameLabel": "Nombre de la empresa",
    "auth.organizationNamePlaceholder": "Acme S.A.",
    "auth.advancedSummary": "Avanzado: URL base de la API",
    "auth.errorFillAllFields": "Por favor completa todos los campos.",
    "auth.errorOrganizationNameRequired": "Por favor ingresa un nombre de empresa.",
    "auth.errorPasswordLength": "La contraseña debe tener al menos 8 caracteres.",
    "auth.errorNoOrganization": "No se encontró ninguna empresa para esta cuenta.",
    "auth.errorSignInFailed": "No se pudo iniciar sesión.",
    "auth.errorRegisterFailed": "No se pudo crear la cuenta.",
    "auth.errorGeneric": "Algo salió mal. Por favor intenta de nuevo.",
    "auth.signingIn": "Iniciando sesión…",
    "auth.creatingAccount": "Creando cuenta…",

    "dashboard.title": "Panel",
    "dashboard.subtitle": "Resumen de facturas, ingresos y clientes de tu empresa.",
    "dashboard.loadError": "No se pudo cargar el panel",
    "dashboard.summaryAriaLabel": "Resumen",
    "dashboard.revenueLabel": "Ingresos",
    "dashboard.totalRevenueTitle": "Ingresos totales",
    "dashboard.totalRevenueDescription": "Suma de todos los totales de factura",
    "dashboard.totalInvoicesTitle": "Facturas totales",
    "dashboard.totalInvoicesDescription": "Todas las facturas de esta empresa",
    "dashboard.totalCustomersTitle": "Clientes totales",
    "dashboard.totalCustomersDescription": "Registros de clientes activos",
    "dashboard.emptyTitle": "Aún no hay facturas",
    "dashboard.emptyDescription":
      "Crea tu primera factura para ver tendencias de ingresos, desgloses de estado y actividad en este panel.",
    "dashboard.createInvoiceCta": "Crear factura",
    "dashboard.revenueStatusAriaLabel": "Ingresos y desglose de estado",
    "dashboard.analyticsHeading": "Análisis",
    "dashboard.recentInvoicesHeading": "Facturas recientes",
    "dashboard.recentInvoicesSubtitle": "Últimas 5 facturas, más recientes primero.",
    "dashboard.viewAll": "Ver todas →",
    "dashboard.revenueTrendTitle": "Tendencia de ingresos",
    "dashboard.revenueTrendNoPriorData": "Sin datos previos",
    "dashboard.revenueTrendThisMonth": "Este mes",
    "dashboard.revenueTrendLastMonth": "Mes anterior",
    "dashboard.revenueTrendChartTitle": "Tendencia de ingresos (6 meses)",
    "dashboard.chartEmptyNoRevenue": "Aún no hay ingresos. Este gráfico se completa a medida que creas facturas.",
    "dashboard.invoiceVolumeTitle": "Volumen de facturas (6 meses)",
    "dashboard.chartEmptyNoInvoices": "Aún no hay facturas. Este gráfico se completa a medida que creas facturas.",
    "dashboard.paymentStatusChartTitle": "Facturas por estado",
    "dashboard.paymentStatusBreakdownTitle": "Estado de pago",
    "dashboard.paymentStatusBreakdownEmpty":
      "Aún no hay facturas. El desglose de estado aparecerá aquí cuando crees una.",
    "dashboard.topCustomersTitle": "Mejores clientes por ingresos",
    "dashboard.topCustomersEmpty":
      "Aún no hay ingresos de clientes. Asocia un cliente a una factura para verlo aquí.",

    "customers.title": "Clientes",
    "customers.subtitle": "Miembros de la empresa seleccionada.",
    "customers.loadError": "No se pudieron cargar los clientes",
    "customers.searchAriaLabel": "Buscar clientes",
    "customers.searchPlaceholder": "Buscar por nombre, correo o teléfono…",
    "customers.loading": "Cargando clientes…",
    "customers.emptyFilteredTitle": "Ningún cliente coincide con tu búsqueda",
    "customers.emptyFilteredDescription": "Prueba con otro nombre, correo o número de teléfono.",
    "customers.emptyTitle": "Aún no hay clientes",
    "customers.emptyDescription":
      "Agrega tu primer cliente con el formulario de arriba. Aparecerán en esta lista y podrás seleccionarlos al crear facturas.",
    "customers.addTitle": "Agregar cliente",
    "customers.addSubtitle": "Los clientes nuevos pertenecen a tu empresa actual.",
    "customers.createButton": "Crear cliente",
    "customers.toastCreating": "Creando cliente…",
    "customers.toastCreated": "Cliente creado.",
    "customers.toastCreateError": "No se pudo crear el cliente.",

    "settings.title": "Configuración",
    "settings.subtitle": "El perfil de tu empresa. Esta información aparece en los PDF de factura.",
    "settings.loadError": "No se pudo cargar el perfil de la empresa",
    "settings.organizationSectionTitle": "Empresa",
    "settings.orgNameHelp": "Se muestra en la barra lateral y se usa para identificar tu empresa.",
    "settings.businessDetailsSectionTitle": "Datos del negocio",
    "settings.businessDetailsSubtitle": "Se muestran en los PDF de factura. Deja en blanco para omitir un campo.",
    "settings.businessNameLabel": "Nombre del negocio",
    "settings.businessNamePlaceholder": "Usa el nombre de la empresa por defecto",
    "settings.taxIdLabel": "Identificación fiscal",
    "settings.logoUrlLabel": "URL del logo",
    "settings.logoUrlHelp": "Se guarda para uso futuro. Por ahora no se muestra en los PDF de factura.",
    "settings.localizationSectionTitle": "Localización",
    "settings.localizationSubtitle": "Controla el idioma y la moneda usados en los PDF de factura y los correos.",
    "settings.languageFieldLabel": "Idioma",
    "settings.currencyFieldLabel": "Moneda",
    "settings.currencyUSD": "USD — Dólar estadounidense",
    "settings.currencyUYU": "UYU — Peso uruguayo",
    "settings.currencyEUR": "EUR — Euro",
    "settings.taxLabelFieldLabel": "Etiqueta de identificación fiscal",
    "settings.taxLabelHelp": "Se muestra junto a tu identificación fiscal en los PDF de factura.",
    "settings.toastSaving": "Guardando perfil…",
    "settings.toastSaved": "Perfil de la empresa guardado.",
    "settings.toastSaveError": "No se pudo guardar el perfil de la empresa.",
  },
};
