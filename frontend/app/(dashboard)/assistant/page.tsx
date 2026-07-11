"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetchStream, orgPath } from "@/lib/api";
import { isEmailNotVerifiedError, isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";

type Role = "user" | "assistant";
type ChatMessage = { role: Role; content: string };

// Mirrors the backend's AI_MAX_HISTORY_MESSAGES default (app/ai/limits.py)
// so we never even try to send more than the server will accept.
const MAX_HISTORY_MESSAGES = 12;

// No @tailwindcss/typography plugin in this project (and no other markdown
// rendering exists to reuse) — rather than adding another dependency just
// for "prose" styling, element-level classes are applied directly here.
// react-markdown never renders raw HTML by default (no rehype-raw plugin
// is used), so this stays safe regardless of what the model outputs.
const markdownComponents: Components = {
  p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline">
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-slate-200/70 px-1 py-0.5 text-xs">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-800 p-3 text-xs text-slate-100">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="px-2 py-1 text-left font-semibold text-slate-700">{children}</th>
  ),
  td: ({ children }) => <td className="px-2 py-1">{children}</td>,
};

export default function AssistantPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function clearConversation() {
    if (isStreaming) return;
    setMessages([]);
  }

  function stopGenerating() {
    abortRef.current?.abort();
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    const history = messages.slice(-MAX_HISTORY_MESSAGES);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await apiFetchStream(orgPath("assistant/chat"), {
        method: "POST",
        body: JSON.stringify({ message: text, history }),
        signal: controller.signal,
      });
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Streaming is not supported in this browser.");

      const decoder = new TextDecoder();
      let accumulated = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        accumulated += decoder.decode(value, { stream: true });
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { role: "assistant", content: accumulated };
          return next;
        });
      }
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (!isAbort) {
        // Every error here happens before any streaming starts (see
        // app/routers/assistant.py — auth/rate-limit/config checks all
        // run before the response begins), so it's safe to drop the
        // optimistic empty exchange rather than leave a dangling bubble.
        setMessages((prev) => prev.slice(0, -2));
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
      abortRef.current = null;
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  const isThinking =
    isStreaming &&
    messages.length > 0 &&
    messages[messages.length - 1].role === "assistant" &&
    messages[messages.length - 1].content === "";

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
        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
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
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                      message.role === "user"
                        ? "bg-slate-900 text-white"
                        : "bg-surface-muted text-slate-900"
                    }`}
                  >
                    {message.role === "assistant" ? (
                      message.content ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {message.content}
                        </ReactMarkdown>
                      ) : isThinking && index === messages.length - 1 ? (
                        <span className="inline-flex items-center gap-1 text-slate-500">
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0.2s]" />
                        </span>
                      ) : null
                    ) : (
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    )}
                  </div>
                </div>
              ))}
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
