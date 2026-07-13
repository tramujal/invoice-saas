"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { QuoteForm, type QuoteFormValues } from "@/components/quotes/QuoteForm";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Quote } from "@/lib/types";

export default function EditQuotePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();

  const [quote, setQuote] = useState<Quote | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Quote>(orgPath(`quotes/${params.id}`))
      .then((res) => {
        if (!cancelled) setQuote(res);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  async function handleSubmit(values: QuoteFormValues) {
    const payload: Record<string, unknown> = {
      line_items: values.line_items,
      tax_rate: values.tax_rate,
      customer_id: values.customer_id,
      expiry_date: values.expiry_date,
      notes: values.notes,
    };

    const loadingId = toast.loading(t("quoteForm.toastSaving"));
    setIsSubmitting(true);
    try {
      await apiFetch<Quote>(orgPath(`quotes/${params.id}`), {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast.dismiss(loadingId);
      toast.success(t("quoteForm.toastSaved"));
      router.push("/quotes");
      router.refresh();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("quoteForm.toastSaveError"))
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loading) {
    return <p className="p-6 text-sm text-slate-500">{t("quotes.loading")}</p>;
  }

  if (loadError || !quote) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
        {t("quoteForm.loadError")}
      </div>
    );
  }

  return (
    <QuoteForm
      mode="edit"
      initialQuote={quote}
      backHref="/quotes"
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
    />
  );
}
