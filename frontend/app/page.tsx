import Link from "next/link";

const FEATURES = [
  {
    title: "Customers & invoices",
    description:
      "Keep a clean record of every customer and invoice, scoped to your organization from day one.",
  },
  {
    title: "Search, filter, and sort",
    description:
      "Find any invoice in seconds — by customer, status, date range, or amount — without digging through pages.",
  },
  {
    title: "PDF invoices",
    description:
      "Every invoice generates a clean, printable PDF with your business details and tax ID, ready to send.",
  },
  {
    title: "Email delivery",
    description:
      "Send an invoice straight to your customer's inbox, PDF attached, in one click — no separate mail client needed.",
  },
  {
    title: "Multi-language & currency",
    description:
      "Set your organization's language and currency once — invoices, emails, and PDFs follow automatically.",
  },
  {
    title: "Dashboard analytics",
    description:
      "Revenue trends, payment status breakdown, and your top customers, updated the moment an invoice changes.",
  },
] as const;

const STEPS = [
  {
    title: "Create your organization",
    description: "Sign up and set your business name, tax ID, language, and currency.",
  },
  {
    title: "Add customers & invoices",
    description: "Build an invoice with line items — subtotal, tax, and total are calculated for you.",
  },
  {
    title: "Send it",
    description: "Download the PDF or email it directly to your customer.",
  },
  {
    title: "Track payments",
    description: "Mark invoices paid, pending, or overdue, and watch your dashboard update in real time.",
  },
] as const;

const FAQS = [
  {
    question: "Is my organization's data isolated from others?",
    answer:
      "Yes. Every customer, invoice, and setting is scoped to your organization — every request is checked against your membership before any data is returned.",
  },
  {
    question: "What languages and currencies are supported?",
    answer:
      "English and Spanish today, with USD, UYU, and EUR currency support. Set both in your organization settings — invoice PDFs and emails follow automatically.",
  },
  {
    question: "How do customers actually receive an invoice?",
    answer:
      "Download the generated PDF yourself, or send it directly — the same PDF goes out as an email attachment to your customer's address.",
  },
  {
    question: "Do I need a credit card to start?",
    answer:
      "No. Create an account and organization for free — no payment details required.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="min-h-dvh bg-white">
      <header className="border-b border-slate-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
          <nav className="flex items-center gap-2 sm:gap-3">
            <Link
              href="/login"
              className="rounded-lg px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Sign in
            </Link>
            <Link
              href="/login?mode=register"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6 sm:py-28">
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            Invoicing that keeps your business paid on time
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
            Create, send, and track invoices in minutes — with PDF generation, email
            delivery, and a real-time dashboard, all in one place.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/login?mode=register"
              className="inline-flex w-full items-center justify-center rounded-lg bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:w-auto"
            >
              Start free
            </Link>
            <Link
              href="/login"
              className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 sm:w-auto"
            >
              Sign in
            </Link>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                Everything you need to invoice, in one app
              </h2>
              <p className="mt-3 text-slate-600">
                No bloated feature set — just the pieces a small business actually uses.
              </p>
            </div>
            <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature) => (
                <div
                  key={feature.title}
                  className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
                >
                  <h3 className="text-base font-semibold text-slate-900">
                    {feature.title}
                  </h3>
                  <p className="mt-2 text-sm text-slate-600">{feature.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
              How it works
            </h2>
            <p className="mt-3 text-slate-600">
              From sign-up to a paid invoice, in four steps.
            </p>
          </div>
          <ol className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
                  {index + 1}
                </span>
                <h3 className="mt-4 text-base font-semibold text-slate-900">
                  {step.title}
                </h3>
                <p className="mt-1.5 text-sm text-slate-600">{step.description}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Analytics / dashboard benefits */}
        <section className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                Know where your business stands, at a glance
              </h2>
              <p className="mt-4 text-slate-600">
                The dashboard turns your invoices into answers: how much revenue came in
                this month versus last, which invoices are overdue, and which customers
                bring in the most business — updated the moment something changes.
              </p>
              <ul className="mt-6 space-y-3 text-sm text-slate-700">
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  Revenue trend over the last six months
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  Payment status breakdown: pending, paid, overdue
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  Your top customers by revenue
                </li>
              </ul>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-xl border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Total revenue
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">$12,480</p>
                </div>
                <div className="rounded-xl border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Invoices
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">37</p>
                </div>
              </div>
              <div className="mt-4 rounded-xl border border-slate-100 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Payment status
                </p>
                <div className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full w-[45%] bg-amber-400" />
                  <div className="h-full w-[40%] bg-emerald-500" />
                  <div className="h-full w-[15%] bg-red-400" />
                </div>
                <div className="mt-3 flex justify-between text-xs text-slate-500">
                  <span>Pending</span>
                  <span>Paid</span>
                  <span>Overdue</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* PDF and email invoicing */}
        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2">
            <div className="order-2 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm lg:order-1">
              <div className="rounded-xl border border-dashed border-slate-300 p-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Invoice No.
                </p>
                <p className="mt-1 font-mono text-sm text-slate-900">INV-000042</p>
                <div className="mt-4 border-t border-slate-100 pt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Bill To
                  </p>
                  <p className="mt-1 text-sm text-slate-700">Acme Corp</p>
                </div>
                <div className="mt-4 flex justify-between border-t border-slate-100 pt-4 text-sm">
                  <span className="font-semibold text-slate-800">Total</span>
                  <span className="font-semibold text-slate-900">USD 1,240.00</span>
                </div>
              </div>
            </div>
            <div className="order-1 lg:order-2">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                A clean PDF, delivered by email
              </h2>
              <p className="mt-4 text-slate-600">
                Every invoice is available as a printable PDF with your business name,
                tax ID, and line items laid out clearly. Send it with one click and it
                lands in your customer&rsquo;s inbox with the PDF already attached —
                subject and body translated to your organization&rsquo;s language.
              </p>
            </div>
          </div>
        </section>

        {/* Pricing teaser */}
        <section id="pricing" className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                Simple pricing
              </h2>
              <p className="mt-3 text-slate-600">
                Start free. Upgrade only if you outgrow it.
              </p>
            </div>
            <div className="mx-auto mt-12 grid max-w-3xl grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h3 className="text-base font-semibold text-slate-900">Free</h3>
                <p className="mt-1 text-3xl font-semibold text-slate-900">$0</p>
                <p className="mt-1 text-sm text-slate-500">For getting started</p>
                <ul className="mt-5 space-y-2 text-sm text-slate-700">
                  <li>Unlimited customers &amp; invoices</li>
                  <li>PDF generation &amp; email delivery</li>
                  <li>Dashboard analytics</li>
                </ul>
                <Link
                  href="/login?mode=register"
                  className="mt-6 inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50"
                >
                  Start free
                </Link>
              </div>
              <div className="rounded-2xl border border-slate-900 bg-slate-900 p-6 shadow-sm">
                <h3 className="text-base font-semibold text-white">Pro</h3>
                <p className="mt-1 text-3xl font-semibold text-white">Coming soon</p>
                <p className="mt-1 text-sm text-slate-300">For growing teams</p>
                <ul className="mt-5 space-y-2 text-sm text-slate-300">
                  <li>Everything in Free</li>
                  <li>Team roles &amp; permissions</li>
                  <li>Priority support</li>
                </ul>
                <button
                  type="button"
                  disabled
                  className="mt-6 inline-flex w-full cursor-not-allowed items-center justify-center rounded-lg bg-white/10 px-4 py-2.5 text-sm font-semibold text-white/60"
                >
                  Notify me
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
          <h2 className="text-center text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            Frequently asked questions
          </h2>
          <div className="mt-10 space-y-3">
            {FAQS.map((faq) => (
              <details
                key={faq.question}
                className="group rounded-xl border border-slate-200 bg-white p-4 open:shadow-sm sm:p-5"
              >
                <summary className="cursor-pointer select-none text-sm font-semibold text-slate-900">
                  {faq.question}
                </summary>
                <p className="mt-2 text-sm text-slate-600">{faq.answer}</p>
              </details>
            ))}
          </div>
        </section>

        {/* Bottom CTA */}
        <section className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto max-w-3xl px-4 py-20 text-center sm:px-6">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
              Ready to send your first invoice?
            </h2>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/login?mode=register"
                className="inline-flex w-full items-center justify-center rounded-lg bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:w-auto"
              >
                Start free
              </Link>
              <Link
                href="/login"
                className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 sm:w-auto"
              >
                Sign in
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200">
        <div className="mx-auto max-w-6xl px-4 py-8 text-center text-sm text-slate-500 sm:px-6">
          © {new Date().getFullYear()} Invoicing. All rights reserved.
        </div>
      </footer>
    </div>
  );
}
