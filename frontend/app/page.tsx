"use client";

import Link from "next/link";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";

function buildFeatures(t: TranslateFn) {
  return [
    { title: t("landing.features.customers.title"), description: t("landing.features.customers.description") },
    { title: t("landing.features.search.title"), description: t("landing.features.search.description") },
    { title: t("landing.features.pdf.title"), description: t("landing.features.pdf.description") },
    { title: t("landing.features.email.title"), description: t("landing.features.email.description") },
    { title: t("landing.features.localization.title"), description: t("landing.features.localization.description") },
    { title: t("landing.features.analytics.title"), description: t("landing.features.analytics.description") },
  ];
}

function buildSteps(t: TranslateFn) {
  return [
    { title: t("landing.steps.step1.title"), description: t("landing.steps.step1.description") },
    { title: t("landing.steps.step2.title"), description: t("landing.steps.step2.description") },
    { title: t("landing.steps.step3.title"), description: t("landing.steps.step3.description") },
    { title: t("landing.steps.step4.title"), description: t("landing.steps.step4.description") },
  ];
}

function buildFaqs(t: TranslateFn) {
  return [
    { question: t("landing.faq.q1.question"), answer: t("landing.faq.q1.answer") },
    { question: t("landing.faq.q2.question"), answer: t("landing.faq.q2.answer") },
    { question: t("landing.faq.q3.question"), answer: t("landing.faq.q3.answer") },
    { question: t("landing.faq.q4.question"), answer: t("landing.faq.q4.answer") },
  ];
}

export default function LandingPage() {
  const { t, language, setLanguage } = useMarketingTranslation();
  const features = buildFeatures(t);
  const steps = buildSteps(t);
  const faqs = buildFaqs(t);

  return (
    <div className="min-h-dvh bg-white">
      <header className="border-b border-slate-200">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Link href="/" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
          <nav className="flex flex-wrap items-center gap-2 sm:gap-3">
            <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
            <Link
              href="/login"
              className="rounded-lg px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              {t("landing.nav.signIn")}
            </Link>
            <Link
              href="/login?mode=register"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            >
              {t("landing.nav.getStarted")}
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6 sm:py-28">
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            {t("landing.hero.headline")}
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
            {t("landing.hero.subtitle")}
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/login?mode=register"
              className="inline-flex w-full items-center justify-center rounded-lg bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:w-auto"
            >
              {t("landing.hero.startFree")}
            </Link>
            <Link
              href="/login"
              className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 sm:w-auto"
            >
              {t("landing.hero.signIn")}
            </Link>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                {t("landing.features.heading")}
              </h2>
              <p className="mt-3 text-slate-600">{t("landing.features.subtitle")}</p>
            </div>
            <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {features.map((feature) => (
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
              {t("landing.steps.heading")}
            </h2>
            <p className="mt-3 text-slate-600">{t("landing.steps.subtitle")}</p>
          </div>
          <ol className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((step, index) => (
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
                {t("landing.analytics.heading")}
              </h2>
              <p className="mt-4 text-slate-600">{t("landing.analytics.description")}</p>
              <ul className="mt-6 space-y-3 text-sm text-slate-700">
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  {t("landing.analytics.point1")}
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  {t("landing.analytics.point2")}
                </li>
                <li className="flex gap-2">
                  <span className="text-slate-400">—</span>
                  {t("landing.analytics.point3")}
                </li>
              </ul>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-xl border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("landing.analytics.mock.totalRevenue")}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">$12,480</p>
                </div>
                <div className="rounded-xl border border-slate-100 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("landing.analytics.mock.invoices")}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">37</p>
                </div>
              </div>
              <div className="mt-4 rounded-xl border border-slate-100 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {t("landing.analytics.mock.paymentStatus")}
                </p>
                <div className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full w-[45%] bg-amber-400" />
                  <div className="h-full w-[40%] bg-emerald-500" />
                  <div className="h-full w-[15%] bg-red-400" />
                </div>
                <div className="mt-3 flex justify-between text-xs text-slate-500">
                  <span>{t("status.pending")}</span>
                  <span>{t("status.paid")}</span>
                  <span>{t("status.overdue")}</span>
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
                  {t("landing.pdfEmail.mock.invoiceNo")}
                </p>
                <p className="mt-1 font-mono text-sm text-slate-900">INV-000042</p>
                <div className="mt-4 border-t border-slate-100 pt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("landing.pdfEmail.mock.billTo")}
                  </p>
                  <p className="mt-1 text-sm text-slate-700">Acme Corp</p>
                </div>
                <div className="mt-4 flex justify-between border-t border-slate-100 pt-4 text-sm">
                  <span className="font-semibold text-slate-800">{t("invoices.colTotal")}</span>
                  <span className="font-semibold text-slate-900">USD 1,240.00</span>
                </div>
              </div>
            </div>
            <div className="order-1 lg:order-2">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                {t("landing.pdfEmail.heading")}
              </h2>
              <p className="mt-4 text-slate-600">{t("landing.pdfEmail.description")}</p>
            </div>
          </div>
        </section>

        {/* Pricing teaser */}
        <section id="pricing" className="border-t border-slate-100 bg-slate-50/80">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                {t("landing.pricing.heading")}
              </h2>
              <p className="mt-3 text-slate-600">{t("landing.pricing.subtitle")}</p>
            </div>
            <div className="mx-auto mt-12 grid max-w-3xl grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h3 className="text-base font-semibold text-slate-900">
                  {t("landing.pricing.free.title")}
                </h3>
                <p className="mt-1 text-3xl font-semibold text-slate-900">$0</p>
                <p className="mt-1 text-sm text-slate-500">{t("landing.pricing.free.tagline")}</p>
                <ul className="mt-5 space-y-2 text-sm text-slate-700">
                  <li>{t("landing.pricing.free.feature1")}</li>
                  <li>{t("landing.pricing.free.feature2")}</li>
                  <li>{t("landing.features.analytics.title")}</li>
                </ul>
                <Link
                  href="/login?mode=register"
                  className="mt-6 inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50"
                >
                  {t("landing.hero.startFree")}
                </Link>
              </div>
              <div className="rounded-2xl border border-slate-900 bg-slate-900 p-6 shadow-sm">
                <h3 className="text-base font-semibold text-white">
                  {t("landing.pricing.pro.title")}
                </h3>
                <p className="mt-1 text-3xl font-semibold text-white">
                  {t("landing.pricing.pro.comingSoon")}
                </p>
                <p className="mt-1 text-sm text-slate-300">{t("landing.pricing.pro.tagline")}</p>
                <ul className="mt-5 space-y-2 text-sm text-slate-300">
                  <li>{t("landing.pricing.pro.feature1")}</li>
                  <li>{t("landing.pricing.pro.feature2")}</li>
                  <li>{t("landing.pricing.pro.feature3")}</li>
                </ul>
                <button
                  type="button"
                  disabled
                  className="mt-6 inline-flex w-full cursor-not-allowed items-center justify-center rounded-lg bg-white/10 px-4 py-2.5 text-sm font-semibold text-white/60"
                >
                  {t("landing.pricing.pro.notifyMe")}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
          <h2 className="text-center text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            {t("landing.faq.heading")}
          </h2>
          <div className="mt-10 space-y-3">
            {faqs.map((faq) => (
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
              {t("landing.cta.heading")}
            </h2>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/login?mode=register"
                className="inline-flex w-full items-center justify-center rounded-lg bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:w-auto"
              >
                {t("landing.hero.startFree")}
              </Link>
              <Link
                href="/login"
                className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 sm:w-auto"
              >
                {t("landing.hero.signIn")}
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200">
        <div className="mx-auto max-w-6xl px-4 py-8 text-center text-sm text-slate-500 sm:px-6">
          © {new Date().getFullYear()} Invoicing. {t("landing.footer.rights")}
        </div>
      </footer>
    </div>
  );
}
