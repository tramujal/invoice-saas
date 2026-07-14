"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

import { ActionProposalCard } from "@/components/assistant/ActionProposalCard";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetchStream, orgPath } from "@/lib/api";
import { assistantErrorMessageForCode } from "@/lib/assistant-errors";
import { isEmailNotVerifiedError, isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AssistantChatMessage, AssistantStreamEvent } from "@/lib/types";

// Mirrors the backend's AI_MAX_HISTORY_MESSAGES default (app/ai/limits.py)
// so we never even try to send more than the server will accept.
const MAX_HISTORY_MESSAGES = 12;

// How close to the bottom (px) the user must already be scrolled for a
// new message to auto-scroll the view -- otherwise someone scrolled up to
// reread earlier history isn't yanked back down by every streamed token.
const AUTO_SCROLL_THRESHOLD_PX = 120;

// react-markdown + remark-gfm are only ever needed on this one route --
// loading them dynamically (client-only, no SSR) keeps them out of this
// route's initial JS until the first assistant reply actually renders.
const MarkdownMessage = dynamic(
  () => import("@/components/assistant/MarkdownMessage").then((mod) => mod.MarkdownMessage),
  { ssr: false, loading: () => <p className="whitespace-pre-wrap opacity-70">…</p> }
);

function AssistantContent() {
  const { t } = useTranslation();
  const toast = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<AssistantChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isAwaitingFirstEvent, setIsAwaitingFirstEvent] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Only auto-scroll when the user is already near the bottom -- otherwise
  // someone scrolled up to reread earlier messages would get yanked back
  // down on every streamed token.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < AUTO_SCROLL_THRESHOLD_PX) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  // Cancels any in-flight stream when navigating away mid-response --
  // without this, the fetch/reader from sendMessage() below is simply
  // abandoned rather than actually cancelled.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // A dashboard insight's "Ask Assistant" CTA links here with ?q=<question>
  // prefilled -- read it once on mount, then strip it from the URL so a
  // later manual refresh of this page doesn't keep re-seeding the input.
  useEffect(() => {
    const question = searchParams.get("q");
    if (question) {
      setInput(question);
      router.replace("/assistant");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function clearConversation() {
    if (isStreaming) return;
    setMessages([]);
  }

  function stopGenerating() {
    abortRef.current?.abort();
  }

  function updateProposalMessage(
    proposalId: string,
    patch: Partial<Extract<AssistantChatMessage, { kind: "proposal" }>>
  ) {
    setMessages((prev) =>
      prev.map((m) => (m.kind === "proposal" && m.proposalId === proposalId ? { ...m, ...patch } : m))
    );
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    const history = messages
      .filter((m): m is Extract<AssistantChatMessage, { kind: "text" }> => m.kind === "text")
      .slice(-MAX_HISTORY_MESSAGES)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { kind: "text", role: "user", content: text }]);
    setIsStreaming(true);
    setIsAwaitingFirstEvent(true);

    const controller = new AbortController();
    abortRef.current = controller;

    // Tracks the array index of the assistant text bubble currently being
    // filled in by text_delta events, if any — a plain closure variable
    // (not React state), reset to null whenever a proposal/clarification
    // event starts a new message, so any text that follows one in the
    // same turn opens a fresh bubble after it rather than merging into it.
    let currentTextIndex: number | null = null;

    function handleEvent(event: AssistantStreamEvent) {
      if (event.type === "text_delta") {
        if (!event.text) return;
        setMessages((prev) => {
          const existing = currentTextIndex !== null ? prev[currentTextIndex] : undefined;
          if (existing !== undefined && existing.kind === "text" && existing.role === "assistant") {
            const next = [...prev];
            next[currentTextIndex as number] = {
              ...existing,
              content: existing.content + event.text,
            };
            return next;
          }
          const next: AssistantChatMessage[] = [
            ...prev,
            { kind: "text", role: "assistant", content: event.text },
          ];
          currentTextIndex = next.length - 1;
          return next;
        });
      } else if (event.type === "action_proposal") {
        currentTextIndex = null;
        setMessages((prev) => [
          ...prev,
          {
            kind: "proposal",
            proposalId: event.proposal_id,
            action: event.action,
            summary: event.summary,
            expiresAt: event.expires_at,
            status: "pending",
          },
        ]);
      } else if (event.type === "clarification_needed") {
        currentTextIndex = null;
        setMessages((prev) => [
          ...prev,
          { kind: "clarification", code: event.code, candidates: event.candidates },
        ]);
      } else if (event.type === "error") {
        currentTextIndex = null;
        toast.error(assistantErrorMessageForCode(t, event.code));
      }
    }

    try {
      const response = await apiFetchStream(orgPath("assistant/chat"), {
        method: "POST",
        body: JSON.stringify({ message: text, history }),
        signal: controller.signal,
      });
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Streaming is not supported in this browser.");

      const decoder = new TextDecoder();
      let buffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          setIsAwaitingFirstEvent(false);
          try {
            handleEvent(JSON.parse(line) as AssistantStreamEvent);
          } catch {
            // Malformed NDJSON line -- skip rather than crash the stream.
          }
        }
      }
      if (buffer.trim()) {
        setIsAwaitingFirstEvent(false);
        try {
          handleEvent(JSON.parse(buffer) as AssistantStreamEvent);
        } catch {
          // Malformed trailing fragment -- ignore.
        }
      }
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (!isAbort) {
        // Every error caught here happens before any streaming starts
        // (see app/routers/assistant.py — auth/rate-limit/config checks
        // all run before the response begins), so only the optimistic
        // user message needs to be rolled back, never any assistant-side
        // message (none can exist yet at this point).
        setMessages((prev) => prev.slice(0, -1));
        if (isEmailNotVerifiedError(err)) {
          toast.error(t("errors.emailNotVerified"));
        } else if (isRateLimitedError(err)) {
          toast.error(t("errors.rateLimitedAssistant"));
        } else if (err instanceof ApiError && err.status === 503) {
          toast.error(t("assistant.errorNotConfigured"));
        } else if (err instanceof ApiError && err.status === 504) {
          toast.error(t("assistant.errorTimeout"));
        } else {
          toast.error(t("assistant.errorGeneric"));
        }
      }
    } finally {
      setIsStreaming(false);
      setIsAwaitingFirstEvent(false);
      abortRef.current = null;
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-6rem)] max-w-4xl flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {t("assistant.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("assistant.subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={clearConversation}
          disabled={isStreaming || messages.length === 0}
          className="self-start rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 sm:self-auto"
        >
          {t("assistant.clear")}
        </button>
      </header>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
        {t("assistant.disclaimer")}
      </div>

      <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4 sm:p-6">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <h2 className="text-base font-semibold text-slate-900">
                {t("assistant.emptyTitle")}
              </h2>
              <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">
                {t("assistant.emptyDescription")}
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message, index) => {
                const isUser = message.kind === "text" && message.role === "user";
                return (
                  <div key={index} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                    {message.kind === "text" ? (
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                          isUser ? "bg-slate-900 text-white" : "bg-surface-muted text-slate-900"
                        }`}
                      >
                        {message.role === "assistant" ? (
                          <MarkdownMessage content={message.content} />
                        ) : (
                          <p className="whitespace-pre-wrap">{message.content}</p>
                        )}
                      </div>
                    ) : message.kind === "proposal" ? (
                      <ActionProposalCard
                        message={message}
                        onStateChange={(patch) => updateProposalMessage(message.proposalId, patch)}
                      />
                    ) : (
                      <div className="max-w-[85%] rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                        <p className="font-semibold">{t("assistant.clarification.title")}</p>
                        <p className="mt-1 text-xs">
                          {t("assistant.clarification.ambiguousCustomerHint")}
                        </p>
                        <ul className="mt-2 list-disc space-y-0.5 pl-5">
                          {message.candidates.map((name) => (
                            <li key={name}>{name}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                );
              })}
              {isAwaitingFirstEvent ? (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl bg-surface-muted px-4 py-2.5 text-sm text-slate-900">
                    <span className="inline-flex items-center gap-1 text-slate-500" aria-hidden>
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0.2s]" />
                    </span>
                    {/* One announcement per state transition (streaming
                        starts), not per streamed token -- this element
                        unmounts the moment the first real event arrives. */}
                    <span role="status" className="sr-only">
                      {t("assistant.thinking")}
                    </span>
                  </div>
                </div>
              ) : null}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <div className="border-t border-slate-200 p-3 sm:p-4">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={t("assistant.placeholder")}
              rows={2}
              disabled={isStreaming}
              className="flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            />
            {isStreaming ? (
              <button
                type="button"
                onClick={stopGenerating}
                className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
              >
                {t("assistant.stop")}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void sendMessage()}
                disabled={!input.trim()}
                className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("assistant.send")}
              </button>
            )}
          </div>
          <p className="mt-1.5 text-xs text-slate-400">{t("assistant.enterHint")}</p>
        </div>
      </div>
    </div>
  );
}

export default function AssistantPage() {
  return (
    <Suspense fallback={null}>
      <AssistantContent />
    </Suspense>
  );
}
