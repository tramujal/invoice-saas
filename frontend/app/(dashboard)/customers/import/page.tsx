"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, apiFetchForm, ApiError, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type {
  ImportConfirmResponse,
  ImportConfirmRowResult,
  ImportPreviewResponse,
  ImportPreviewRowResult,
  ImportTargetField,
  OrganizationProfile,
} from "@/lib/types";

type Step = "upload" | "mapping" | "preview" | "confirm" | "result";

const TARGET_FIELDS: ImportTargetField[] = ["name", "email", "phone", "address", "tax_id", "ignore"];
const ACCEPTED_EXTENSIONS = [".csv", ".xlsx"];
const MAX_DISPLAY_SIZE = "5 MB";
// Defense-in-depth client-side cap, mirroring the backend's
// IMPORT_MAX_PREVIEW_ROWS (app/imports/limits.py) -- the backend already
// never returns more than this, but rendering is capped independently
// rather than trusting that invariant to hold forever.
const PREVIEW_ROW_DISPLAY_CAP = 50;

function targetFieldLabel(t: TranslateFn, field: ImportTargetField): string {
  if (field === "ignore") return t("import.mappingIgnore");
  if (field === "name") return t("import.fieldName");
  if (field === "email") return t("import.fieldEmail");
  if (field === "phone") return t("import.fieldPhone");
  if (field === "address") return t("import.fieldAddress");
  return t("import.fieldTaxId");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function reasonLabel(t: TranslateFn, reasonCode: string | null): string {
  if (!reasonCode) return "";
  const key = `import.reason.${reasonCode}`;
  const translated = t(key);
  return translated === key ? reasonCode : translated;
}

function statusLabel(t: TranslateFn, status: string): string {
  const key = `import.status${status.charAt(0).toUpperCase()}${status.slice(1)}`;
  const translated = t(key);
  return translated === key ? status : translated;
}

// Inline SVG icons matching this app's existing icon style (stroke-based,
// viewBox 0 0 24 24 — see e.g. the empty-state icon on the Customers page)
// rather than emoji, so the wizard feels consistent with the rest of the
// product.
function FileIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

function CheckCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <path d="M22 4 12 14.01l-3-3" />
    </svg>
  );
}

function WarningTriangleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

type PreviewOutcome = "all-valid" | "partial" | "none-valid";

function previewOutcome(preview: ImportPreviewResponse): PreviewOutcome {
  const importable = preview.valid_count + preview.warning_count;
  if (importable === 0) return "none-valid";
  if (preview.invalid_count === 0 && preview.duplicate_count === 0) return "all-valid";
  return "partial";
}

function StatusBadge({ status, t }: { status: string; t: TranslateFn }) {
  const styles: Record<string, string> = {
    valid: "bg-emerald-100 text-emerald-800",
    imported: "bg-emerald-100 text-emerald-800",
    warning: "bg-amber-100 text-amber-800",
    duplicate: "bg-slate-200 text-slate-700",
    skipped: "bg-slate-200 text-slate-700",
    invalid: "bg-red-100 text-red-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        styles[status] ?? "bg-slate-100 text-slate-700"
      }`}
    >
      {statusLabel(t, status)}
    </span>
  );
}

function StepIndicator({ step, t }: { step: Step; t: TranslateFn }) {
  const steps: { key: Step; labelKey: string }[] = [
    { key: "upload", labelKey: "import.stepUpload" },
    { key: "mapping", labelKey: "import.stepMapping" },
    { key: "preview", labelKey: "import.stepPreview" },
    { key: "confirm", labelKey: "import.stepConfirm" },
    { key: "result", labelKey: "import.stepResult" },
  ];
  const currentIndex = steps.findIndex((s) => s.key === step);

  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs font-medium text-slate-500">
      {steps.map((s, index) => (
        <li key={s.key} className="flex items-center gap-2">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full ${
              index <= currentIndex ? "bg-slate-900 text-white" : "bg-slate-200 text-slate-500"
            }`}
          >
            {index + 1}
          </span>
          <span className={index === currentIndex ? "text-slate-900" : ""}>{t(s.labelKey)}</span>
          {index < steps.length - 1 ? <span className="text-slate-300">→</span> : null}
        </li>
      ))}
    </ol>
  );
}

function buildErrorReportCsv(rows: ImportConfirmRowResult[], t: TranslateFn): string {
  const problemRows = rows.filter((r) => r.status !== "imported");
  const header = ["row", "status", "reason", "name", "email", "phone", "address", "tax_id"];
  const lines = [header.join(",")];
  for (const row of problemRows) {
    const cells = [
      String(row.row_number),
      statusLabel(t, row.status),
      reasonLabel(t, row.reason_code),
      row.values.name ?? "",
      row.values.email ?? "",
      row.values.phone ?? "",
      row.values.address ?? "",
      row.values.tax_id ?? "",
    ].map((cell) => `"${String(cell).replace(/"/g, '""')}"`);
    lines.push(cells.join(","));
  }
  return lines.join("\r\n");
}

export default function CustomerImportPage() {
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();

  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [mapping, setMapping] = useState<Record<string, ImportTargetField>>({});
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [confirmResult, setConfirmResult] = useState<ImportConfirmResponse | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [orgProfile, setOrgProfile] = useState<OrganizationProfile | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch<OrganizationProfile>(orgPath())
      .then(setOrgProfile)
      .catch(() => {});
  }, []);

  function isAcceptedFile(candidate: File): boolean {
    const name = candidate.name.toLowerCase();
    return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
  }

  function pickFile(candidate: File) {
    if (!isAcceptedFile(candidate)) {
      toast.error(t("import.uploadWrongType"));
      return;
    }
    setFile(candidate);
    setUploadError(null);
  }

  function handleErrorResponse(err: unknown, fallbackKey: string) {
    if (err instanceof ApiError) {
      const body = err.body as { detail?: { code?: string; message?: string } } | undefined;
      const code = body?.detail?.code;
      if (err.status === 429) {
        setUploadError(t("import.errorRateLimited"));
        return;
      }
      if (code) {
        const translated = t(`import.reason.${code}`);
        if (translated !== `import.reason.${code}`) {
          setUploadError(translated);
          return;
        }
      }
      if (body?.detail?.message) {
        setUploadError(body.detail.message);
        return;
      }
    }
    setUploadError(t(fallbackKey));
  }

  async function runPreview(currentMapping: Record<string, ImportTargetField> | null) {
    if (!file) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (currentMapping) {
        formData.append("mapping", JSON.stringify(currentMapping));
      }
      const response = await apiFetchForm<ImportPreviewResponse>(
        orgPath("customers/import/preview"),
        formData
      );
      setPreview(response);
      if (!currentMapping) {
        setMapping(response.auto_mapping as Record<string, ImportTargetField>);
      }
      setStep(response.requires_manual_mapping || !currentMapping ? "mapping" : "preview");
    } catch (err) {
      handleErrorResponse(err, "import.errorUploadFailed");
    } finally {
      setIsUploading(false);
    }
  }

  function mappingHasDuplicateTargets(): boolean {
    const used = new Set<string>();
    for (const target of Object.values(mapping)) {
      if (target === "ignore") continue;
      if (used.has(target)) return true;
      used.add(target);
    }
    return false;
  }

  function mappingHasName(): boolean {
    return Object.values(mapping).includes("name");
  }

  async function confirmMappingAndPreview() {
    await runPreview(mapping);
  }

  async function runConfirm() {
    if (!file || isConfirming) return;
    setStep("confirm");
    setIsConfirming(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("mapping", JSON.stringify(mapping));
      const response = await apiFetchForm<ImportConfirmResponse>(
        orgPath("customers/import/confirm"),
        formData
      );
      setConfirmResult(response);
      setStep("result");
    } catch (err) {
      handleErrorResponse(err, "import.errorGeneric");
      setStep("preview");
    } finally {
      setIsConfirming(false);
    }
  }

  function downloadErrorReport() {
    if (!confirmResult) return;
    const csv = buildErrorReportCsv(confirmResult.row_results, t);
    const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "customer-import-errors.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function resetWizard() {
    setStep("upload");
    setFile(null);
    setMapping({});
    setPreview(null);
    setConfirmResult(null);
    setUploadError(null);
  }

  const importableCount = preview ? preview.valid_count + preview.warning_count : 0;

  return (
    <div className="mx-auto max-w-4xl space-y-6 pb-12">
      <div>
        <Link
          href="/customers"
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          {t("import.backToCustomers")}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
          {t("import.title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{t("import.subtitle")}</p>
      </div>

      <StepIndicator step={step} t={t} />

      {step === "upload" ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) pickFile(dropped);
            }}
            onClick={() => fileInputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${
              isDragging ? "border-slate-500 bg-slate-50" : "border-slate-300 hover:bg-slate-50/60"
            }`}
          >
            {/* Visually hidden (not display:none) so it stays tab-reachable
                and Enter/Space opens the native file picker -- a plain
                `hidden` input is removed from the accessibility tree
                entirely, which previously left no keyboard path to this
                control at all. The "Browse" label below is a peer sibling
                so its focus-visible ring reflects this input's real
                focus state. */}
            <input
              ref={fileInputRef}
              id="customers-import-file-input"
              type="file"
              accept=".csv,.xlsx"
              className="peer sr-only"
              onChange={(e) => {
                const picked = e.target.files?.[0];
                if (picked) pickFile(picked);
              }}
            />
            <FileIcon className="h-10 w-10 text-slate-400" />
            <p className="mt-3 text-sm font-medium text-slate-700">
              {t("import.uploadDropzoneTitle")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {t("import.uploadDropzoneOr")}
            </p>
            <label
              htmlFor="customers-import-file-input"
              // Stops the click from also bubbling to the dropzone div's
              // own onClick (which also opens the picker) -- the label's
              // native for/id association already opens it once.
              onClick={(e) => e.stopPropagation()}
              className="mt-1 cursor-pointer rounded text-sm font-medium text-slate-700 underline peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-slate-400"
            >
              {t("import.uploadBrowseAction")}
            </label>
            <p className="mt-3 text-xs text-slate-400">
              {t("import.uploadAcceptedTypes", { size: MAX_DISPLAY_SIZE })}
            </p>
          </div>

          {file ? (
            <div className="mt-4 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-slate-700">
                  {t("import.uploadSelectedFile")}
                </p>
                <p className="text-sm text-slate-600">
                  {file.name} · {formatBytes(file.size)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setFile(null)}
                disabled={isUploading}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed"
              >
                {t("import.uploadClearFile")}
              </button>
            </div>
          ) : null}

          {uploadError ? (
            <div
              className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {uploadError}
            </div>
          ) : null}

          <div className="mt-5 flex justify-end">
            <button
              type="button"
              onClick={() => void runPreview(null)}
              disabled={!file || isUploading}
              className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isUploading ? t("import.uploadUploading") : t("import.uploadPreviewButton")}
            </button>
          </div>
        </section>
      ) : null}

      {step === "mapping" && preview ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("import.mappingTitle")}
          </h2>
          <p className="mt-1 text-sm text-slate-500">{t("import.mappingSubtitle")}</p>

          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>{t("import.mappingSourceColumn")}</span>
              <span>{t("import.mappingTargetField")}</span>
            </div>
            {preview.headers.map((header) => (
              <div key={header} className="grid grid-cols-2 items-center gap-4">
                <span className="truncate text-sm text-slate-800">{header}</span>
                <select
                  value={mapping[header] ?? "ignore"}
                  onChange={(e) =>
                    setMapping((prev) => ({
                      ...prev,
                      [header]: e.target.value as ImportTargetField,
                    }))
                  }
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                >
                  {TARGET_FIELDS.map((field) => (
                    <option key={field} value={field}>
                      {targetFieldLabel(t, field)}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          {!mappingHasName() ? (
            <p className="mt-4 text-sm text-amber-700" role="alert">
              {t("import.mappingMissingNameWarning")}
            </p>
          ) : null}
          {mappingHasDuplicateTargets() ? (
            <p className="mt-2 text-sm text-red-600" role="alert">
              {t("import.mappingDuplicateTargetError")}
            </p>
          ) : null}
          {uploadError ? (
            <p className="mt-2 text-sm text-red-600" role="alert">
              {uploadError}
            </p>
          ) : null}

          <div className="mt-5 flex justify-between">
            <button
              type="button"
              onClick={() => setStep("upload")}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
            >
              {t("import.mappingBackButton")}
            </button>
            <button
              type="button"
              onClick={() => void confirmMappingAndPreview()}
              disabled={!mappingHasName() || mappingHasDuplicateTargets() || isUploading}
              className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isUploading ? t("import.uploadUploading") : t("import.mappingContinueButton")}
            </button>
          </div>
        </section>
      ) : null}

      {step === "preview" && preview ? (
        <section className="space-y-4">
          {(() => {
            const outcome = previewOutcome(preview);
            if (outcome === "all-valid") {
              return (
                <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-800">
                  <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold">{t("import.previewAllValidTitle")}</p>
                    <p className="mt-0.5 text-sm">
                      {t("import.previewAllValidMessage", { count: importableCount })}
                    </p>
                  </div>
                </div>
              );
            }
            if (outcome === "partial") {
              return (
                <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800">
                  <WarningTriangleIcon className="mt-0.5 h-5 w-5 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold">
                      {t("import.previewPartialTitle", { count: importableCount })}
                    </p>
                    <p className="mt-0.5 text-sm">
                      {t("import.previewPartialMessage", {
                        count: preview.duplicate_count + preview.invalid_count,
                      })}
                    </p>
                  </div>
                </div>
              );
            }
            return (
              <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-red-800">
                <WarningTriangleIcon className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold">{t("import.previewNoneValidTitle")}</p>
                  <p className="mt-0.5 text-sm">{t("import.previewNoImportableRows")}</p>
                </div>
              </div>
            );
          })()}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: t("import.previewSummaryTotal"), value: preview.total_rows },
              { label: t("import.previewSummaryValid"), value: preview.valid_count },
              { label: t("import.previewSummaryDuplicate"), value: preview.duplicate_count },
              { label: t("import.previewSummaryInvalid"), value: preview.invalid_count },
            ].map((card) => (
              <div
                key={card.label}
                className="rounded-xl border border-slate-200 bg-white p-4 text-center shadow-sm"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {card.label}
                </p>
                <p className="mt-1 text-xl font-semibold text-slate-900">{card.value}</p>
              </div>
            ))}
          </div>
          <p className="text-sm text-slate-500">
            {t("import.previewSummaryLine", {
              total: preview.total_rows,
              valid: importableCount,
              duplicate: preview.duplicate_count,
              invalid: preview.invalid_count,
            })}
          </p>

          <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 p-4 sm:p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                {t("import.previewTitle")}
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                {t("import.previewSubtitle", {
                  shown: Math.min(preview.preview_rows.length, PREVIEW_ROW_DISPLAY_CAP),
                  total: preview.total_rows,
                })}
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-4 py-3">{t("import.previewColRow")}</th>
                    <th className="px-4 py-3">{t("import.fieldName")}</th>
                    <th className="px-4 py-3">{t("import.fieldEmail")}</th>
                    <th className="hidden px-4 py-3 md:table-cell">{t("common.phone")}</th>
                    <th className="hidden px-4 py-3 lg:table-cell">{t("common.address")}</th>
                    <th className="hidden px-4 py-3 lg:table-cell">
                      {orgProfile?.tax_label || t("customers.taxIdColumn")}
                    </th>
                    <th className="px-4 py-3">{t("import.previewColStatus")}</th>
                    <th className="px-4 py-3">{t("import.previewColReason")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.preview_rows.slice(0, PREVIEW_ROW_DISPLAY_CAP).map((row: ImportPreviewRowResult) => (
                    <tr key={row.row_number}>
                      <td className="px-4 py-2 font-mono text-xs text-slate-500">
                        {row.row_number}
                      </td>
                      <td className="px-4 py-2 text-slate-800">{row.values.name || "—"}</td>
                      <td className="px-4 py-2 text-slate-600">{row.values.email || "—"}</td>
                      <td className="hidden px-4 py-2 text-slate-600 md:table-cell">
                        {row.values.phone || "—"}
                      </td>
                      <td className="hidden max-w-xs truncate px-4 py-2 text-slate-600 lg:table-cell">
                        {row.values.address || "—"}
                      </td>
                      <td className="hidden px-4 py-2 text-slate-600 lg:table-cell">
                        {row.values.tax_id || "—"}
                      </td>
                      <td className="px-4 py-2">
                        <StatusBadge status={row.status} t={t} />
                      </td>
                      <td className="px-4 py-2 text-xs text-slate-500">
                        {reasonLabel(t, row.reason_code)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {uploadError ? (
            <div
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {uploadError}
            </div>
          ) : null}

          <p className="text-xs text-slate-500">{t("import.confirmNote")}</p>

          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep("mapping")}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
            >
              {t("import.previewBackButton")}
            </button>
            <button
              type="button"
              onClick={() => void runConfirm()}
              disabled={importableCount === 0 || isConfirming}
              className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("import.previewConfirmButton", { count: importableCount })}
            </button>
          </div>
          {importableCount === 0 ? (
            <p className="text-right text-xs text-amber-700">
              {t("import.previewNoImportableRows")}
            </p>
          ) : null}
        </section>
      ) : null}

      {step === "confirm" ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <svg
            className="mx-auto h-8 w-8 animate-spin text-slate-400"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          <h2 className="mt-4 text-base font-semibold text-slate-900">
            {t("import.confirmingTitle")}
          </h2>
          <p className="mt-1 text-sm text-slate-500">{t("import.confirmingSubtitle")}</p>
        </section>
      ) : null}

      {step === "result" && confirmResult ? (
        <section className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
            <CheckCircleIcon className="mx-auto h-10 w-10 text-emerald-600" />
            <h2 className="mt-4 text-lg font-semibold text-slate-900">
              {t("import.resultHeading")}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {confirmResult.imported_count > 0
                ? t("import.resultBodyMessage", { count: confirmResult.imported_count })
                : t("import.resultBodyMessageNone")}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4 text-center shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("import.resultImported")}
              </p>
              <p className="mt-1 text-2xl font-semibold text-emerald-700">
                {confirmResult.imported_count}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 text-center shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("import.resultSkipped")}
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-700">
                {confirmResult.skipped_duplicate_count}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 text-center shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("import.resultFailed")}
              </p>
              <p className="mt-1 text-2xl font-semibold text-red-700">
                {confirmResult.failed_count}
              </p>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            {confirmResult.failed_count + confirmResult.skipped_duplicate_count > 0 ? (
              <button
                type="button"
                onClick={downloadErrorReport}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
              >
                {t("import.resultDownloadErrorReport")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={resetWizard}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
            >
              {t("import.resultImportAnotherButton")}
            </button>
            <button
              type="button"
              onClick={() => router.push("/customers")}
              className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            >
              {t("import.resultDoneButton")}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
