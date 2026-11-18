"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApprovalCard } from "@/components/chat/approval-card";
import { type SavedAnswer, SaveButton } from "@/components/analysis/results";
import { AnnotatedAnswer } from "@/components/chat/answer";
import { answerLoaded } from "@/components/chat/live";
import { MODES, ModeBadge } from "@/components/chat/mode-badge";
import {
  ProgressLine,
  type Stage,
  WorkingDot,
} from "@/components/chat/progress-line";
import { Button } from "@/components/ui/button";
import { useDocuments } from "@/components/workspaces/document-library";
import { api, type Schemas, unwrap } from "@/lib/api/client";
import {
  type Decision,
  resumeRun,
  type RunEvent,
  sendMessage,
} from "@/lib/api/stream";

type Message = Schemas["HistoryMessageRead"];
type Conversation = Schemas["ConversationRead"];

/** After this long a run found `running` with no stream is treated as stuck (it still runs on the server). */
const STALL_MS = 3 * 60 * 1000;

/** A run started in this tab: the question, its stages so far, and where it stopped. */
type Live = {
  question?: string;
  stages: Stage[];
  busy: boolean;
  approval?: { runId: string; request: Schemas["ApprovalRequest"] };
  error?: string;
  answerId?: string;
};

const PAGE = 100;

/**
 * Research chat for one workspace. Without `conversationId` it shows the earlier conversations and
 * starts a new one on the first question, then moves the URL to it without remounting.
 */
export function Chat({
  workspaceId,
  conversationId: initialId,
}: {
  workspaceId: string;
  conversationId?: string;
}) {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState(initialId);
  const [live, setLive] = useState<Live | null>(null);
  const [freshId, setFreshId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const workspace = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}", {
          params: { path: { workspace_id: workspaceId } },
        }),
      ),
  });
  const documents = useDocuments(workspaceId);
  const conversations = useQuery({
    queryKey: ["conversations", workspaceId],
    // ponytail: the 100 most recent conversations only (API maximum page).
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations", {
          params: {
            path: { workspace_id: workspaceId },
            query: { limit: PAGE },
          },
        }),
      ),
  });
  const messages = useQuery({
    queryKey: ["messages", conversationId],
    enabled: conversationId !== undefined,
    // ponytail: the first 100 messages (50 turns) only; page further if threads grow longer.
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/conversations/{conversation_id}/messages", {
          params: {
            path: { conversation_id: conversationId ?? "" },
            query: { limit: PAGE },
          },
        }),
      ),
  });

  const history = useMemo(() => messages.data ?? [], [messages.data]);
  const last = history.at(-1);
  // A question with no answer after it: its run is still going, paused, or failed (getRun).
  const pendingRunId =
    !live && last?.role === "user" ? (last.run_id ?? undefined) : undefined;
  const pendingRun = useQuery({
    queryKey: ["run", pendingRunId],
    enabled: pendingRunId !== undefined,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/runs/{run_id}", {
          params: { path: { run_id: pendingRunId ?? "" } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });
  const pendingStatus = pendingRun.data?.status;
  // A run another tab or a restart left `running` may never finish; stop locking the box after a while.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (pendingStatus !== "running") return;
    const timer = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, [pendingStatus]);
  const stalled =
    pendingRun.data?.status === "running" &&
    now - Date.parse(pendingRun.data.created_at) > STALL_MS;
  useEffect(() => {
    if (pendingStatus === "completed")
      void queryClient.invalidateQueries({
        queryKey: ["messages", conversationId],
      });
  }, [pendingStatus, conversationId, queryClient]);

  const conversation = conversations.data?.find((c) => c.id === conversationId);
  const docsById = useMemo(
    () => new Map((documents.data ?? []).map((d) => [d.id, d])),
    [documents.data],
  );
  const readyCount = documents.data?.filter((d) => d.status === "ready").length;
  // Once the answer is in the refetched history, the live block is done (no duplicate frame).
  const showLive = live && !answerLoaded(live.answerId, history);
  const approval =
    (showLive && live.approval) ||
    (pendingRun.data?.status === "interrupted" && pendingRun.data.approval
      ? { runId: pendingRun.data.id, request: pendingRun.data.approval }
      : undefined);
  const busy = Boolean(showLive && live.busy);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [history.length, live?.question, live?.approval, live?.error]);

  async function follow(events: AsyncGenerator<RunEvent>, cid: string) {
    try {
      for await (const event of events) {
        if (event.type === "status") {
          setLive((l) =>
            l && !l.stages.includes(event.stage)
              ? { ...l, stages: [...l.stages, event.stage] }
              : l,
          );
          setAnnouncement(event.stage);
        } else if (event.type === "approval_required") {
          setLive(
            (l) =>
              l && {
                ...l,
                busy: false,
                approval: { runId: event.run_id, request: event.request },
              },
          );
          setAnnouncement(
            "Your papers don't fully cover this. Choose how to continue.",
          );
        } else if (event.type === "error") {
          setLive((l) => l && { ...l, busy: false, error: event.message });
          setAnnouncement(event.message);
        } else if (event.type === "done") {
          const answerId = event.message.id;
          setFreshId(answerId);
          setLive((l) => l && { ...l, answerId });
          setAnnouncement("Answer ready.");
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["messages", cid] }),
            queryClient.invalidateQueries({
              queryKey: ["conversations", workspaceId],
            }),
          ]);
          setLive(null);
        }
      }
    } catch (error) {
      // Leaving the page stops listening only; the run still finishes and is saved.
      if ((error as Error).name !== "AbortError") throw error;
    }
  }

  async function ask(question: string, mode: Conversation["mode"]) {
    abort.current = new AbortController();
    setLive({ question, stages: [], busy: true });
    setDraft("");
    let cid = conversationId;
    try {
      if (!cid) {
        const created = await unwrap(
          api.POST("/api/v1/workspaces/{workspace_id}/conversations", {
            params: { path: { workspace_id: workspaceId } },
            body: { title: question.slice(0, 200), mode },
          }),
        );
        cid = created.id;
        setConversationId(cid);
        window.history.replaceState(
          null,
          "",
          `/workspaces/${workspaceId}/chat/${cid}`,
        );
        void queryClient.invalidateQueries({
          queryKey: ["conversations", workspaceId],
        });
      }
      const events = sendMessage(
        cid,
        { content: question },
        abort.current.signal,
      );
      // The first event (or the rejection) arrives here; a rejected question goes back to the box.
      await follow(events, cid);
    } catch (error) {
      setDraft(question);
      setLive({ stages: [], busy: false, error: (error as Error).message });
    }
  }

  async function decide(runId: string, decision: Decision) {
    if (!conversationId) return;
    abort.current = new AbortController();
    setLive((l) => ({
      question: l?.question,
      stages: [],
      busy: true,
    }));
    queryClient.removeQueries({ queryKey: ["run", runId] });
    try {
      await follow(
        resumeRun(runId, { decision }, abort.current.signal),
        conversationId,
      );
    } catch (error) {
      setLive(
        (l) => l && { ...l, busy: false, error: (error as Error).message },
      );
    }
  }

  const started = conversationId !== undefined;
  const title = started
    ? (conversation?.title ?? live?.question ?? "Conversation")
    : "Ask your papers";

  return (
    <div className="flex min-h-[calc(100dvh-10rem)] flex-col">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <nav className="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
          <Link
            href={`/workspaces/${workspaceId}`}
            className="link-draw tap-target"
          >
            ← {workspace.data?.name ?? "Library"}
          </Link>
          {started && (
            <>
              <span aria-hidden>/</span>
              <Link
                href={`/workspaces/${workspaceId}/chat`}
                className="link-draw tap-target"
              >
                Conversations
              </Link>
            </>
          )}
        </nav>
        {conversation && <ModeBadge mode={conversation.mode} />}
      </header>
      {/* In a thread the questions are the visible headings; the title would repeat the first. */}
      <h1
        className={
          started ? "sr-only" : "mt-3 min-w-0 text-3xl font-medium break-words"
        }
      >
        {title}
      </h1>
      {!started && (
        <p className="mt-2 max-w-prose text-muted-foreground">
          Answers come only from the papers in this workspace
          {readyCount !== undefined && ` (${readyCount} ready)`}. Every claim is
          checked against its source and cites the page it came from.
        </p>
      )}

      <div className="flex-1">
        {messages.isError && (
          <p role="alert" className="mt-8 text-destructive">
            Couldn&apos;t load this conversation: {messages.error.message}
          </p>
        )}
        {messages.isPending && started && !live && (
          <p className="mt-8 text-muted-foreground">Loading conversation…</p>
        )}

        <div className="mt-8 space-y-10">
          {history.map((m, i) =>
            m.role === "user" ? (
              <Question key={m.id} text={m.content} />
            ) : (
              <Answer
                key={m.id}
                workspaceId={workspaceId}
                question={history[i - 1]?.content ?? ""}
                message={m}
                documents={docsById}
                fresh={m.id === freshId}
              />
            ),
          )}

          {showLive && live.question && <Question text={live.question} />}
          {showLive && live.busy && (
            <div className="border-l-2 border-border pl-4">
              <ProgressLine stages={live.stages} />
            </div>
          )}
          {!live && pendingRun.data?.status === "running" && (
            <p
              role="status"
              className="inline-flex items-center gap-2 border-l-2 border-border pl-4 font-mono text-xs text-muted-foreground"
            >
              {!stalled && <WorkingDot />}
              {stalled
                ? "This is taking longer than expected and may not finish. You can ask again."
                : "Still working on this question…"}
            </p>
          )}
          {!live && pendingRun.data?.status === "failed" && (
            <p
              role="alert"
              className="border-l-2 border-destructive pl-4 text-destructive"
            >
              This question couldn&apos;t be answered
              {pendingRun.data.error ? `: ${pendingRun.data.error}` : "."} Try
              asking again.
            </p>
          )}
          {approval && (
            <ApprovalCard
              request={approval.request}
              busy={busy}
              onDecide={(d) => void decide(approval.runId, d)}
            />
          )}
          {showLive && live.error && (
            <p
              role="alert"
              className="border-l-2 border-destructive pl-4 text-destructive"
            >
              {live.error}
            </p>
          )}
        </div>

        {!started && !live && (
          <EarlierConversations
            workspaceId={workspaceId}
            conversations={conversations.data}
          />
        )}
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <div ref={bottom} />

      <Composer
        draft={draft}
        onDraft={setDraft}
        disabled={
          busy ||
          approval !== undefined ||
          (pendingRun.data?.status === "running" && !stalled)
        }
        placeholder={
          approval
            ? "Choose how to continue above first"
            : started
              ? "Ask a follow-up question"
              : "What do you want to know from these papers?"
        }
        chooseMode={!started}
        onAsk={(q, mode) => void ask(q, mode)}
      />
    </div>
  );
}

function Question({ text }: { text: string }) {
  return (
    <h2 className="border-t pt-8 font-serif text-2xl leading-snug font-medium break-words whitespace-pre-line first:border-t-0 first:pt-0">
      {text}
    </h2>
  );
}

function Answer({
  workspaceId,
  question,
  message,
  documents,
  fresh,
}: {
  workspaceId: string;
  question: string;
  message: Message;
  documents: Map<string, Schemas["DocumentRead"]>;
  fresh: boolean;
}) {
  return (
    <motion.article
      initial={fresh ? { opacity: 0, y: 12 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.23, 1, 0.32, 1] }}
      className="-mt-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ModeBadge mode={message.mode} />
        {message.claims.length > 0 && (
          <SaveButton
            workspaceId={workspaceId}
            finding={() => ({
              type: "answer",
              title: (question || "Answer").slice(0, 300),
              content: {
                question,
                mode: message.mode,
                claims: message.claims,
              } satisfies SavedAnswer,
            })}
          />
        )}
      </div>
      <div className="mt-3">
        <AnnotatedAnswer
          messageId={message.id}
          content={message.content}
          claims={message.claims}
          documents={documents}
          animate={fresh}
        />
      </div>
    </motion.article>
  );
}

function EarlierConversations({
  workspaceId,
  conversations,
}: {
  workspaceId: string;
  conversations: Conversation[] | undefined;
}) {
  if (!conversations?.length) return null;
  const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
  return (
    <section className="mt-12" aria-labelledby="earlier">
      <h2 id="earlier" className="text-xl font-medium">
        Earlier conversations
      </h2>
      <ul className="mt-3 divide-y border-y">
        {conversations.map((c) => (
          <li
            key={c.id}
            className="flex items-baseline justify-between gap-4 py-3"
          >
            <Link
              href={`/workspaces/${workspaceId}/chat/${c.id}`}
              className="link-draw tap-target min-w-0 font-serif text-lg break-words"
            >
              {c.title ?? "Untitled conversation"}
            </Link>
            <span className="flex shrink-0 items-center gap-3">
              {c.mode !== "corpus_only" && <ModeBadge mode={c.mode} />}
              <time
                dateTime={c.updated_at}
                className="font-mono text-xs text-muted-foreground tabular-nums"
              >
                {date.format(new Date(c.updated_at))}
              </time>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Composer({
  draft,
  onDraft,
  disabled,
  placeholder,
  chooseMode,
  onAsk,
}: {
  draft: string;
  onDraft: (value: string) => void;
  disabled: boolean;
  placeholder: string;
  chooseMode: boolean;
  onAsk: (question: string, mode: Conversation["mode"]) => void;
}) {
  const question = draft.trim();

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (question && !disabled) onAsk(question, "corpus_only");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={submit}
      className="sticky bottom-0 -mx-1 mt-8 bg-background px-1 pt-3 pb-4"
    >
      <div className="rounded-[10px] border bg-card transition-colors duration-[120ms] has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-foreground">
        <label htmlFor="question" className="sr-only">
          Question
        </label>
        <textarea
          id="question"
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          rows={2}
          className="block max-h-48 min-h-16 w-full resize-none bg-transparent px-3 pt-3 text-base outline-none focus-visible:outline-none field-sizing-content placeholder:text-muted-foreground"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 px-2 pb-2">
          {chooseMode ? <ModeChoice /> : <span />}
          <Button
            type="submit"
            disabled={disabled || !question}
            className="h-10 px-4"
          >
            Ask
            <ArrowUp aria-hidden />
          </Button>
        </div>
      </div>
      <p className="mt-1.5 px-1 text-xs text-muted-foreground">
        Enter to ask · Shift+Enter for a new line
      </p>
    </form>
  );
}

/** New-conversation mode: Corpus + Web arrives in Phase 5, so only Corpus only can be chosen. */
function ModeChoice() {
  return (
    <fieldset className="flex items-center gap-1">
      <legend className="sr-only">Knowledge mode</legend>
      {(["corpus_only", "corpus_web"] as const).map((mode) => {
        const { label, Icon } = MODES[mode];
        const soon = mode === "corpus_web";
        return (
          <label
            key={mode}
            className="inline-flex h-10 items-center gap-1.5 rounded-[6px] px-2.5 text-xs font-medium has-checked:bg-muted has-disabled:text-muted-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring"
          >
            <input
              type="radio"
              name="mode"
              value={mode}
              defaultChecked={!soon}
              disabled={soon}
              className="sr-only"
            />
            <Icon aria-hidden className="size-3.5" />
            {label}
            {soon && (
              <span className="font-mono text-[0.6875rem]">· Phase 5</span>
            )}
          </label>
        );
      })}
    </fieldset>
  );
}
