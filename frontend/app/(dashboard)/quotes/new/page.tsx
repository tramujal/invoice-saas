"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { QuoteForm, type QuoteFormValues } from "@/components/quotes/QuoteForm";
import { PlanLimitReachedDialog } from "@/components/ui/PlanLimitReachedDialog";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getPlanLimitReachedDetail, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlanLimitReachedDetail, Quote } from "@/lib/types";

export default function NewQuotePage() {
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [planLimitDetail, setPlanLimitDetail] = useState<PlanLimitReachedDetail | null>(null);

  async function handleSubmit(values: QuoteFormValues) {
    const payload: Record<string, unknown> = {
      line_items: values.line_items,
      tax_rate: values.tax_rate,
      currency_code: values.currency_code,
      expiry_date: values.expiry_date,
      notes: values.notes,
    };
    if (values.customer_id) payload.customer_id = values.customer_id;

    const loadingId = toast.loading(t("quoteForm.toastCreating"));
    setIsSubmitting(true);
    try {
      await apiFetch<Quote>(orgPath("quotes"), {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast.dismiss(loadingId);
      toast.success(t("quoteForm.toastCreated"));
      router.push("/quotes");
      router.refresh();
    } catch (err) {
      toast.dismiss(loadingId);
      const planLimit = getPlanLimitReachedDetail(err);
      if (planLimit) {
        setPlanLimitDetail(planLimit);
      } else {
        toast.error(
          isEmailNotVerifiedError(err)
            ? t("errors.emailNotVerified")
            : formatApiError(err, t("quoteForm.toastCreateError"))
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <QuoteForm mode="create" backHref="/quotes" onSubmit={handleSubmit} isSubmitting={isSubmitting} />
      <PlanLimitReachedDialog detail={planLimitDetail} onClose={() => setPlanLimitDetail(null)} />
    </>
  );
}
