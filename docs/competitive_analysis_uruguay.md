# Competitive analysis — Invoicing vs ZenSei (Uruguay market)

**Date:** 2026-08-11
**Type:** Strategic research. No code, schema, or configuration was changed.

Everything about ZenSei here comes from their public site (fetched
2026-08-11) and is labelled with a confidence level. Everything about
Invoicing comes from reading this repository, not from a feature list.
Where the two disagree, the repository wins.

---

## 1. The single fact that dominates this analysis

Since **1 January 2025**, every VAT (IVA) contributor in Uruguay must be
enrolled in the electronic invoicing regime. Resolution 2548/2023 closed
the phased calendar that Resolution 3012/015 began; new registrations and
resumptions of activity enter the regime immediately. Narrow exclusions
remain (monotributo and monotributo MIDES, small rural operations under
4M UI, IRNR, exempt entities, PPL).
([Forvis Mazars](https://www.forvismazars.com/uy/es/insights/nuestras-publicaciones/impuestos/inclusion-en-facturacion-electronica))

The consequence for this product is blunt:

> **A PDF is not an invoice in Uruguay.** For a VAT-registered business,
> a legally valid sales document is a CFE: an XML in DGI's schema, signed
> with a qualified digital certificate, carrying a CAE-authorised number,
> reported to DGI. Invoicing today produces a PDF. Those are not
> different qualities of the same thing — they are different objects.

Invoicing is therefore **not currently sellable as a primary invoicing
system to a VAT-registered Uruguayan business**, regardless of how good
the rest of the product is. It is sellable to the excluded segments, and
sellable as a layer alongside a CFE issuer.

The second commercial fact is nearly as important: DGI's **UI80 benefit**
credits up to 80 UI/month (~UYU 470) against the cost of an electronic
invoicing system. ZenSei prices its three tiers at UYU 190 / 290 / 490 +
IVA and markets all of them as **"$0/month"** after the credit. The
practical effect is that the compliance layer is free to the customer,
and any price we charge sits entirely outside that subsidy.

---

## 2. ZenSei — verified capabilities

Source for all rows unless noted: <https://zensoluciones.uy/> and linked
pages, fetched 2026-08-11.

| Feature | Public wording | Type | Confidence |
|---|---|---|---|
| Electronic invoicing (CFE) | "Emití e-Facturas, e-Tickets y comprobantes con validación y trazabilidad completa" | Core | **High** |
| Received-invoice management | "Centralizá comprobantes recibidos, controlá estados" | Core | **High** |
| Customers & products | "Gestioná fichas comerciales, precios y condiciones" | Core | **High** |
| Purchasing & inventory | "Controlá stock, costos y abastecimiento" | Core | **High** |
| Reports | "indicadores de ventas, cobranzas y rentabilidad en tiempo real" | Core | **High** |
| Automation | "Definí reglas y flujos para reducir tareas manuales" | Core | **Medium** — no detail on what rules exist |
| CAE management | "Incluye vigencia, rangos, solicitud en DGI y carga del XML" | Core | **High** |
| Digital certificate handling | Documented install/management process | Core | **High** |
| DGI issuer onboarding support | "Primer paso formal ante DGI para ingresar al régimen" | Service | **High** |
| UI80 benefit assistance | Dedicated documentation page | Service | **High** |
| Mercado Pago | "Cobranza automatizada y conciliación instantánea" | Integration (top tier) | **High** |
| Mercado Libre | "Sincronización y facturación automática" | Integration (top tier) | **High** |
| WhatsApp Business Bot | Customers "consultan productos, hacen pedidos y pagan" | Integration (top tier) | **High** |
| API | "Conectá ZenSei a tus sistemas" — support email, no public docs | Integration | **Medium** — exists, undocumented publicly |
| Multi-device access | "Facturación desde cualquier dispositivo" | Core | **High** |
| Accountant-office module | "Gestion de clientes para estudios contables" | Add-on (top tier) | **High** |
| Multi-company isolation | Mentioned in documentation | Core | **Medium** |

**Not found anywhere on the public site** (absence of evidence, not
evidence of absence): forecasting, anomaly detection, AI-generated
financial analysis, public webhooks, public API reference, audit log,
granular RBAC, multi-currency handling, exchange rates.

---

## 3. Invoicing — capabilities verified from this repository

Classification: **COMPLETE** (works end to end, tested), **PARTIAL**
(works but materially narrower than the label suggests), **SCAFFOLDED**
(code exists, not production-usable), **NOT IMPLEMENTED**.

### Core documents

| Capability | Status | Evidence |
|---|---|---|
| Customers | COMPLETE | `customers` table, CRUD, import, duplicate detection |
| Products/services | COMPLETE | `products`, archive-not-delete, `default_tax_rate` |
| Quotes | COMPLETE | `quotes` + line items, status, expiry, public share link, convert-to-invoice |
| Invoices | COMPLETE | `invoices` + `invoice_line_items`, numbering per org |
| PDF generation | COMPLETE | `app/invoice_pdf.py`, `app/quote_pdf.py` |
| Email sending | COMPLETE | Resend provider, queued via `notification.email` |
| Invoice status | **PARTIAL** | `PaymentStatus` is exactly three values: `pending`, `paid`, `overdue` (derived) |
| Payment tracking | **PARTIAL** | A status flag on the invoice. **No `payments` table** — no partial payments, no payment dates, no amounts received, no ledger |
| Credit notes | **NOT IMPLEMENTED** | No model, no route, no reference in codebase |
| Debit notes | **NOT IMPLEMENTED** | Same |
| Recurring invoices | **NOT IMPLEMENTED** | Grep for `recurring` finds only a forecasting seasonality comment |
| WhatsApp sending | **SCAFFOLDED** | See below — this one matters |

### The WhatsApp caveat

`docs/whatsapp.md` states it plainly: *"Experimental. Unofficial.
Disabled by default. Not production-ready."* It is built on
`whatsapp-web.js` driving a headless Chromium session — **not** the Meta
WhatsApp Business Platform — and the doc warns the connected number can
be banned. `WHATSAPP_ENABLED` defaults to false.

This is not comparable to ZenSei's WhatsApp Business Bot and must not be
described as a WhatsApp integration in any commercial material.

### Tax handling — a structural limitation

Invoice tax is a **single invoice-level `tax_rate`**. `models.py` says so
explicitly: *"invoices remain single, invoice-level-tax_rate … which
never reads this column"* (referring to `Product.default_tax_rate`, which
is a UI prefill convenience only).

Uruguay routinely needs **mixed IVA rates on one document** — 22% basic,
10% minimum, and exempt lines. A single-rate invoice cannot represent
that correctly. This is a schema-level constraint, not a UI gap, and it
sits on the critical path to any CFE work.

### Uruguay-relevant things that already exist

Worth stating, because they are better than a generic product:

- **UYU is a first-class supported currency** — `SUPPORTED_CURRENCIES = ("USD", "UYU", "EUR")`.
- **`Organization.tax_label` is configurable**, so the UI can say "RUT" rather than a hardcoded foreign label.
- **`Customer.tax_id` exists**, and `normalize_tax_id()` deliberately treats `"RUT 12.345.678-9"` and `"123456789"` as the same identifier for duplicate detection.
- **Spanish localization is real** — full EN/ES across UI and notifications, with a per-user → per-org → default resolution chain.
- **Multi-currency is handled honestly**: analytics never sum across currencies, and the AI prompt explicitly forbids it absent a real rate.

What is missing is RUT *validation* (no check-digit verification) and any
notion of DGI.

### Automation, integrations, developer surface

| Capability | Status | Evidence |
|---|---|---|
| Notifications (in-app) | COMPLETE | `emit_event` fans out to all active members |
| Email notifications | COMPLETE | Queued job, per-recipient language |
| **Automatic payment reminders** | **COMPLETE** | `send_due_invoice_reminders`, org-level before/on/after-due offsets, claim-then-send so no double sends |
| Quote expiry reminders | COMPLETE | `send_expiring_quote_reminders` |
| Webhooks | COMPLETE | Endpoints, signing, delivery, retry chain, SSRF guards, audit |
| API keys | COMPLETE | Scoped keys, rotation, audit log |
| Public REST API v1 | COMPLETE | customers / invoices / products / quotes |
| Background jobs | COMPLETE | 5 job types, leases, retries, idempotency (verified in Phase 26.1) |
| Google OAuth | COMPLETE | Server-side code flow, state+nonce, one-time handoff |
| Stripe billing | COMPLETE (config gap) | Provider + webhooks; `STRIPE_PRICE_ID__*` vars not yet in the manifest |
| Mercado Pago | **NOT IMPLEMENTED** | — |
| Mercado Libre | **NOT IMPLEMENTED** | — |
| Payment links | **NOT IMPLEMENTED** | Stripe is for *our* subscriptions, not tenants' customer collections |

### Analytics

| Capability | Status |
|---|---|
| Dashboard | COMPLETE |
| Sales / customer / product / quote analytics | COMPLETE |
| Receivables ageing | COMPLETE |
| Cash-flow visibility | COMPLETE (deterministic, from invoice data) |
| Revenue forecasting | COMPLETE — 4 candidate models, rolling-origin backtesting, confidence tiers, scenarios |
| Anomaly flags | COMPLETE |
| AI Financial Advisor | COMPLETE — interprets deterministic metrics under a strict schema, never computes figures |
| Bank reconciliation | NOT IMPLEMENTED |
| Accounting export | **PARTIAL** — CSV export exists; no accountant-format export (no chart of accounts, no journal entries) |
| Tax reports | **NOT IMPLEMENTED** — no IVA return support, no DGI-format reporting |

### Team, security, platform

Organizations, RBAC, invitations, audit log, platform admin, plan limits,
subscription management — all **COMPLETE**. This layer is genuinely
strong and is more than most SMB invoicing tools ship.

---

## 4. Feature matrix

Importance is judged for a **Uruguayan SMB**, not in the abstract.

### Invoicing

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Quotes | COMPLETE | Likely (not advertised) | We may lead | Medium |
| Invoices (management) | COMPLETE | COMPLETE | None | Critical |
| **Invoices (legally valid CFE)** | **NOT IMPLEMENTED** | COMPLETE | **Total** | **Critical** |
| Credit notes | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| Debit notes | NOT IMPLEMENTED | COMPLETE | Total | High |
| Recurring invoices | NOT IMPLEMENTED | Possibly ("automatización") | Likely | High |
| PDF | COMPLETE | COMPLETE | None | Medium |
| Email sending | COMPLETE | COMPLETE | None | High |
| WhatsApp sending | SCAFFOLDED | COMPLETE | Large | Medium |
| Invoice status | PARTIAL (3 states) | COMPLETE | Moderate | High |
| Payment tracking | PARTIAL (no ledger) | COMPLETE ("cobranzas") | Large | High |

### Uruguay tax

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| DGI integration | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| CFE issuance | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| e-Factura (111) | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| e-Ticket (101) | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| CAE management | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| Electronic signature | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |
| Tax identification (RUT) | PARTIAL (stored, normalized, not validated) | COMPLETE | Moderate | High |
| VAT/IVA | **PARTIAL — single rate per invoice** | COMPLETE | **Large** | **Critical** |
| Tax reporting | NOT IMPLEMENTED | Partial (reports) | Large | High |
| Currency handling | COMPLETE (UYU/USD/EUR) | Unknown | Possible lead | High |
| Exchange rates | NOT IMPLEMENTED | Unknown | Unknown | High |
| Regulatory compliance | NOT IMPLEMENTED | COMPLETE | Total | **Critical** |

### Customers / products

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Customer management | COMPLETE | COMPLETE | None | Critical |
| RUT storage | PARTIAL | COMPLETE | Small | High |
| Duplicate detection | COMPLETE | Not advertised | **We lead** | Medium |
| Customer import | COMPLETE | Unknown | Possible lead | Medium |
| Customer history | COMPLETE | COMPLETE | None | Medium |
| Products/services | COMPLETE | COMPLETE | None | Critical |
| Pricing | COMPLETE | COMPLETE | None | High |
| Product taxes | PARTIAL (default only) | COMPLETE | Moderate | High |
| Inventory / stock | NOT IMPLEMENTED | COMPLETE | Total | Medium |
| Categories | NOT IMPLEMENTED | Likely | Moderate | Low |

### Payments

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Payment recording | PARTIAL | COMPLETE | Large | High |
| Mercado Pago | NOT IMPLEMENTED | COMPLETE | Total | **High** |
| Payment links | NOT IMPLEMENTED | COMPLETE (via MP) | Total | High |
| Stripe (tenant collections) | NOT IMPLEMENTED | n/a | — | Low in UY |
| Reconciliation | NOT IMPLEMENTED | COMPLETE ("conciliación instantánea") | Total | Medium |

### Automation / ecommerce / developer

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Recurring documents | NOT IMPLEMENTED | Likely | Likely | High |
| Payment reminders | **COMPLETE** | Not explicitly advertised | **We likely lead** | High |
| Notifications | COMPLETE | Unknown | Possible lead | Medium |
| WhatsApp automation | SCAFFOLDED | COMPLETE | Large | Medium |
| Webhooks | **COMPLETE** | Not advertised | **We lead** | Low (SMB) / High (partners) |
| Public API | **COMPLETE + documented** | Exists, undocumented | **We likely lead** | Medium |
| Background jobs | COMPLETE | Unknown | — | Internal |
| Mercado Libre | NOT IMPLEMENTED | COMPLETE | Total | Medium |

### Reporting & advanced analytics

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Sales reports | COMPLETE | COMPLETE | None | High |
| Receivables | COMPLETE | COMPLETE | None | High |
| Customer analytics | COMPLETE | Partial | We likely lead | Medium |
| Product analytics | COMPLETE | Partial | We likely lead | Medium |
| Cash-flow visibility | COMPLETE | Partial | We likely lead | High |
| Financial dashboard | COMPLETE | Partial | **We lead** | Medium |
| Revenue forecast | **COMPLETE (backtested)** | Not advertised | **We lead** | Medium |
| Anomaly detection | **COMPLETE** | Not advertised | **We lead** | Low→Medium |
| AI financial recommendations | **COMPLETE** | Not advertised | **We lead** | Medium |

### Team / security

| Capability | Invoicing | ZenSei | Gap | Importance |
|---|---|---|---|---|
| Multiple users | COMPLETE | Likely | None | High |
| Permissions (RBAC) | **COMPLETE, granular** | Unknown | Possible lead | Medium |
| Audit log | **COMPLETE** | Not advertised | **We likely lead** | Medium |
| Multi-tenant orgs | COMPLETE | COMPLETE ("multiempresa") | None | High |
| Google OAuth | COMPLETE | Unknown | Possible lead | Low |

---

## 5. DGI / CFE — what issuing legally actually requires

Scope research only. Nothing here is a commitment to build.

### Document types (official DGI codes)

| Code | Document |
|---|---|
| 101 | e-Ticket |
| 102 | Nota de Crédito de e-Ticket |
| 103 | Nota de Débito de e-Ticket |
| 111 | e-Factura |
| 112 | Nota de Crédito de e-Factura |
| 113 | Nota de Débito de e-Factura |
| 181 | e-Remito |
| 182 | e-Resguardo |

Contingency paper equivalents exist in a parallel 201–282 series. The
**minimum mandatory set** to enter the regime is e-Factura and e-Ticket
*plus their credit and debit notes* — which is precisely why our missing
credit/debit notes are not an optional nicety but part of the entry
ticket.
([efactura.info](https://efactura.info/tipos-de-comprobantes-fiscales-electronicos/),
[DGI](https://www.efactura.dgi.gub.uy/principal/ampliacion_de_contenido/4-cuales-son-los-codigos-asignados-por-tipo-de-comprobante))

### The pipeline

1. Generate the CFE as **XML** in DGI's published schema (`formato_cfe`, currently v22-ish; DGI versions it and we would have to track versions).
2. **Sign** it with a qualified digital certificate. Certificates are issued by accredited authorities — Abitab, Correo Uruguayo (CorreoSign), Antel — under Ley 18.600, and cost roughly UYU 890–4,543 + IVA per issuance/renewal.
3. Attach a number from a **CAE**-authorised range. The CAE is DGI's authorisation of numbering ranges per CFE type, with an expiry and a finite range that must be renewed *before* exhaustion.
4. Wrap in the **"sobre"** envelope and submit to DGI.
5. Handle **acknowledgement / rejection** asynchronously.
6. Emit periodic **reports** to DGI.
7. Deliver a legal representation to the buyer (PDF/printed with QR).
8. **Contingency**: a documented fallback when DGI or our system is unreachable — the business must still be able to sell.
9. **Storage**: signed XML retained and retrievable.

### Onboarding is a certification process, not an API key

DGI's own staged process:

- **Testing** environment — request a testing key, freely exercise documents, envelopes and reports against realistic operations, debug the implementation.
- **Homologación** — request a homologation key; DGI runs the formal issuer-authorisation and per-CFE-type certification processes here.
- **Producción** — only then.

This is per *issuer*. Each tenant must also be registered with DGI as an
electronic issuer, hold their own certificate, and hold their own CAEs.
So the work is not only "build the integration" — it is also "operate a
per-tenant onboarding funnel involving certificates and a tax authority",
which is a **support and operations** business, not just an engineering
one. ZenSei clearly understands this: a meaningful share of their public
documentation is onboarding guidance, not software.

### Prerequisites inside our own product

Before any DGI work is feasible, three repository-level gaps must close:

1. **Per-line-item tax rates.** A single invoice-level rate cannot encode a mixed 22%/10%/exempt document. Schema change.
2. **Credit and debit notes** as first-class documents referencing an original — required in the minimum mandatory set.
3. **Structured RUT** with validation, plus issuer/receiver fiscal fields the XML requires.

Any plan that skips these and starts with XML generation is building on
sand.

---

## 6. Build vs integrate for DGI

| Dimension | A. Direct DGI | B. Provider API | C. Stay non-fiscal |
|---|---|---|---|
| Complexity | Very high — XML schema versions, signing, CAE lifecycle, envelopes, ack/reject, contingency, reports | Medium — one REST integration + our domain mapping | None |
| Effort | Months, plus a full homologation cycle at DGI's pace | Weeks for the integration; provider handles certification | Zero |
| Maintenance | We track every DGI schema/regulation change forever | Provider absorbs most of it | None |
| Regulatory risk | **We carry it.** A signing or numbering bug is our customer's tax problem | Shared; provider is contractually the specialist | None — but we're unsellable to IVA payers |
| Operational risk | Certificate custody, CAE exhaustion monitoring, contingency, 24/7 expectations | Mostly delegated; provider outage becomes our outage | None |
| Time to market | Longest | Much shorter | Immediate |
| Cost | High fixed engineering, low marginal | Per-document or per-tenant fees compressing margin — **and the UI80 subsidy caps what we can charge** | Zero |
| Scalability | Best margins *if* volume ever justifies the fixed cost | Fine; margin thins at scale | n/a |

**Assessment.** Option A is not defensible for a product at this stage:
it converts an engineering team into a compliance team, and the UI80
subsidy means the resulting capability cannot be priced at a premium —
customers expect it to cost roughly nothing. Option C is honest but caps
the addressable market to the excluded segments.

**Option B is the right shape** — but the next step is *research*, not
integration. We have no verified vendor list, no published pricing, and
no contract terms. I did not find publicly documented per-document
pricing for Uruguayan CFE providers during this audit, and I am not going
to invent numbers.

---

## 7. Where Invoicing is genuinely stronger

Stated carefully: these are areas where our capability is verified in the
repository **and** absent from ZenSei's public marketing. Absence from
marketing is weaker evidence than absence from a product, so these are
"likely advantages", not proven ones.

1. **Backtested revenue forecasting.** Four candidate models selected by rolling-origin backtesting, with confidence tiers and scenarios. This is a real quantitative capability, not a trend line. No competitor equivalent advertised.
2. **AI Financial Advisor with a hard architectural guarantee** — the model interprets deterministic metrics under a strict schema and never computes a figure. That guarantee is a genuine trust differentiator in a finance product, and it is defensible in a sales conversation.
3. **Anomaly detection** on financial series.
4. **Receivables and cash-flow depth** beyond "reports".
5. **Developer surface**: documented REST API v1, scoped API keys with rotation and audit, signed webhooks with retry chains and SSRF protection. ZenSei mentions an API but publishes no documentation.
6. **Auditability**: an immutable audit log plus a per-event pipeline. Not advertised by ZenSei.
7. **Granular RBAC and multi-org** with invitations and platform administration.
8. **Automatic payment reminders** with per-organization before/on/after-due schedules and double-send protection.
9. **Customer duplicate detection**, including tax-id normalization.

Honest counterweight: **none of these nine matter to a business that
cannot legally invoice with us.** They are differentiators *after* the
compliance gate, not instead of it.

---

## 8. What we should deliberately not copy

- **Full inventory / purchasing / stock control.** ZenSei is becoming an ERP. That is a large, low-margin surface that pulls us away from intelligence and automation. `models.py` already declares the boundary: *"NOT inventory: no stock, no suppliers, no purchase orders."* Keep it.
- **Accountant-office multi-client module.** A different customer and a different product.
- **Mercado Libre marketplace sync.** Narrow segment, high maintenance, marketplace API churn. Only if a specific customer concentration demands it.
- **Received-invoice (compras) management.** Adjacent to accounting, not to our thesis.
- **Being cheapest.** The UI80 subsidy makes the compliance layer effectively free; competing on that price floor is a losing game. We must sell something the subsidy doesn't cover.
- **Generic "automatización"** as a marketing word. Ours should be specific and provable: reminders, webhooks, API, forecasting.

---

## 9. Positioning options

### A. Uruguay-first electronic invoicing SaaS

- **Customer:** any VAT-registered Uruguayan SMB.
- **Proposition:** legal compliance plus a far better product than incumbents.
- **Missing:** CFE issuance, credit/debit notes, per-line tax, RUT validation, Mercado Pago.
- **Advantage:** analytics depth, once you're past the gate.
- **Cost:** Very high. Compliance, certification, per-tenant onboarding operations.
- **Monetization:** Capped at the bottom by UI80; we'd be selling the tier *above* free.

### B. Financial intelligence layer for SMBs

- **Customer:** businesses already issuing CFE elsewhere who want to understand their money.
- **Proposition:** "Your invoicing system tells you what you sold. We tell you what happens next." Forecasting, receivables, anomalies, AI analysis.
- **Missing:** ingestion from existing CFE systems; without it there's no data. This is the whole risk.
- **Advantage:** strongest verified differentiators, no compliance liability.
- **Cost:** Medium — integrations/imports rather than tax law.
- **Monetization:** Good. Sits outside the UI80 subsidy entirely, so it's priced on value.

### C. Automation / API-first invoicing platform

- **Customer:** technical teams, agencies, SaaS businesses embedding invoicing.
- **Proposition:** the API and webhooks are the product.
- **Missing:** still CFE for Uruguayan use; the segment is small locally.
- **Advantage:** genuinely differentiated developer surface.
- **Cost:** Low — mostly already built.
- **Monetization:** Narrow in Uruguay; better as an international play.

### Recommendation: **B, sequenced toward A**

Lead with financial intelligence, because it is the part we have actually
built and the part no competitor advertises — and it is priced outside
the subsidy. Treat CFE as the gate that converts B into A, and approach
it via a provider (Option 6-B), not directly.

The sequencing matters: doing A first means spending months on compliance
before we know whether the differentiator sells. Doing B first tests the
value proposition against real customers while the compliance path is
researched in parallel.

---

## 10. Roadmap

### P0 — required before selling seriously to VAT-registered businesses

| Item | Problem | Competitor has it | Complexity | Depends on | Approach |
|---|---|---|---|---|---|
| CFE provider research + selection | We cannot legally invoice | Yes | MEDIUM (research) | — | **INTEGRATE (research first)** |
| Per-line-item tax rates | Cannot represent mixed IVA | Yes | MEDIUM | — | **BUILD** |
| Credit & debit notes | In DGI's minimum mandatory set | Yes | MEDIUM | Per-line tax | **BUILD** |
| Structured RUT + validation | Fiscal identity must be correct | Yes | LOW | — | **BUILD** |
| Payment ledger (partial payments) | 3-state flag can't model reality | Yes | MEDIUM | — | **BUILD** |

### P1 — high commercial impact

| Item | Problem | Competitor | Complexity | Depends on | Approach |
|---|---|---|---|---|---|
| CFE issuance via provider | Legal issuance | Yes | HIGH | All P0 | **INTEGRATE** |
| Mercado Pago | Dominant UY payment rail | Yes | MEDIUM | Payment ledger | **INTEGRATE** |
| Recurring invoices | Manual re-entry every month | Likely | MEDIUM | — | **BUILD** |
| Exchange rates (BCU) | UYU/USD is everyday reality | Unknown | LOW–MEDIUM | — | **BUILD** (BCU rates) |
| Real WhatsApp (Business Platform) | Current one is unshippable | Yes | MEDIUM–HIGH | — | **INTEGRATE** |

### P2 — useful expansion

| Item | Complexity | Approach |
|---|---|---|
| Payment links | MEDIUM | INTEGRATE (via MP) |
| Customer portal | MEDIUM | BUILD |
| Accounting export (accountant formats) | MEDIUM | BUILD |
| IVA/tax reports | MEDIUM | BUILD (after CFE) |
| PWA / mobile | MEDIUM | BUILD |

### P3 — later or optional

| Item | Approach |
|---|---|
| Bank reconciliation | DEFER |
| Inventory / stock | **DON'T BUILD** |
| Mercado Libre | DEFER |
| e-Remito / e-Resguardo | DEFER (beyond minimum set) |
| Received-invoice management | DEFER |

---

## 11. Explicit verdicts

| Feature | Verdict | Justification |
|---|---|---|
| **DGI / CFE** | **BUILD NEXT — via provider; research now** | The market gate. Direct build isn't defensible at this stage. |
| **Mercado Pago** | **INTEGRATE** | Dominant collection rail; unlocks payment links and reconciliation. |
| **Mercado Libre** | **DEFER** | Narrow segment, high upkeep. |
| **Recurring invoices** | **BUILD NEXT** | Common SMB need, fits the job scheduler we already run. |
| **Automatic payment reminders** | **ALREADY BUILT** | Verify it's actually running in production (needs the worker). |
| **Credit / debit notes** | **BUILD NOW** | Part of DGI's minimum mandatory set — not optional. |
| **Exchange rates** | **BUILD NEXT** | Cheap; removes a limitation the AI currently has to apologise for. |
| **Inventory** | **DON'T BUILD** | Deliberate boundary; ERP drift. |
| **Bank reconciliation** | **DEFER** | Needs the payment ledger first. |
| **Payment links** | **INTEGRATE** (with MP) | Falls out of the MP work. |
| **Customer portal** | **BUILD NEXT (small)** | Public quote links already prove the pattern. |
| **Mobile / PWA** | **DEFER** | Responsive layout already verified 320–1920px. |
| **WhatsApp automation** | **INTEGRATE** (replace current) | Current implementation is unshippable. |
| **Accounting exports** | **BUILD NEXT** | Cheap retention lever; the accountant is a real influencer in this market. |
| **Tax reports** | **DEFER until CFE** | Meaningless without fiscal data. |

---

## 12. Commercial readiness

### Five reasons a Uruguayan SMB might choose us

1. Financial intelligence nobody else advertises — forecasting with confidence, receivables depth, anomaly flags.
2. An AI advisor that provably never invents numbers.
3. Automatic payment reminders that get invoices paid sooner.
4. A modern, fast, fully Spanish product.
5. A real API, signed webhooks and an audit log — for the minority who need them.

### Five reasons they would reject us

1. **We cannot issue a legally valid CFE.** For most, the conversation ends here.
2. **No Mercado Pago.** Payment collection is a daily need.
3. **One tax rate per invoice** — cannot represent a normal mixed-IVA document.
4. **No credit notes.** Every business eventually cancels or corrects an invoice.
5. **Competitors are effectively free** under UI80, and we'd be asking for money on top.

Honest summary: **reasons to reject are structural; reasons to choose are
enhancements.** That asymmetry is the whole strategic problem.

---

## 13. Marketing claims — what is honest today

**CAN CLAIM TODAY**
Multi-tenant invoicing and quotes with PDF and email; customers and
products; automatic payment reminders; receivables and cash-flow
analytics; backtested revenue forecasting; AI financial analysis that
never invents figures; REST API, API keys, signed webhooks; audit log;
roles and permissions; EN/ES; UYU/USD/EUR support.

**CAN CLAIM AFTER CURRENT PRODUCTION CONFIGURATION** (needs the worker
deployed — see `docs/production_readiness.md`)
Notification emails actually delivered; AI Advisor reports actually
generated; webhooks actually delivered.

**CAN CLAIM AFTER DGI/CFE**
Electronic invoicing; e-Factura / e-Ticket; DGI compliance; "legally
valid"; credit and debit notes.

**DO NOT CLAIM YET**
Anything about DGI, CFE, e-Factura, e-Ticket, CAE or "legal" invoicing.
WhatsApp integration (experimental and unofficial). Mercado Pago or
Mercado Libre. Inventory or stock. Bank reconciliation. Tax reports or
IVA returns. Accounting integration. "Complete invoicing solution for
Uruguay."

---

## 14. Sources

- <https://zensoluciones.uy/> — features, plans, integrations (fetched 2026-08-11)
- <https://zensoluciones.uy/documentacion> — CAE, certificates, DGI onboarding
- <https://zensoluciones.uy/guias/que-es-cfe-tipos-comprobantes> — CFE definition and types
- <https://zensoluciones.uy/integraciones> — Mercado Pago, Mercado Libre, WhatsApp, API
- <https://www.efactura.dgi.gub.uy/> — official DGI e-Factura portal
- <https://www.efactura.dgi.gub.uy/principal/ampliacion_de_contenido/4-cuales-son-los-codigos-asignados-por-tipo-de-comprobante> — CFE type codes
- <https://efactura.info/tipos-de-comprobantes-fiscales-electronicos/> — CFE codes, contingency series
- <https://www.forvismazars.com/uy/es/insights/nuestras-publicaciones/impuestos/inclusion-en-facturacion-electronica> — Resolution 2548/2023, mandatory inclusion, exclusions, costs
- <https://edicomgroup.com/es/blog/como-es-la-factura-electronica-en-uruguay> — CFE process overview
- <https://memory.com.uy/blog/obligaciones-fiscales/normativa-sobre-facturacion-electronica/> — regulatory framework, Ley 18.600, testing/homologation
- This repository — `app/models.py`, `app/currency.py`, `app/payment_status.py`, `app/customer_validation.py`, `app/jobs/`, `app/routers/api_v1/`, `docs/whatsapp.md`
