"use client";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  ArrowDown,
  ArrowUp,
  Archive,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  CircleHelp,
  FileText,
  Folder,
  LayoutGrid,
  ListTodo,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Paperclip,
  Pencil,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError, allResources, validateUpload, write } from "@/lib/api";
import { SSEParser } from "@/lib/sse";
import type {
  ActionItem,
  Capabilities,
  Document,
  Event,
  History,
  Proposal,
  Resource,
  Run,
  Source,
  User,
} from "@/lib/types";
import { Button } from "./ui/button";
import { Modal } from "./ui/dialog";
import { Markdown } from "./markdown";
import { PdfPreview } from "./pdf-preview";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) =>
        !(
          error instanceof ApiError && [401, 403, 404].includes(error.status)
        ) && count < 1,
      refetchOnWindowFocus: true,
    },
  },
});
export function Workspace() {
  return (
    <QueryClientProvider client={queryClient}>
      <Application />
    </QueryClientProvider>
  );
}
const navigation = [
  { path: "/chat", title: "Conversations", icon: MessageSquare },
  { path: "/projects", title: "Projects", icon: Folder },
  { path: "/documents", title: "Documents", icon: FileText },
  { path: "/tasks", title: "Tasks", icon: ListTodo },
  { path: "/notes", title: "Notes", icon: BookOpen },
  { path: "/memories", title: "Memories", icon: Brain },
];

let sidebarFallback = false;
function sidebarSnapshot() {
  try {
    return localStorage.getItem("nexus-sidebar-collapsed") === "true";
  } catch {
    return sidebarFallback;
  }
}
function subscribeSidebar(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("nexus-sidebar-change", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("nexus-sidebar-change", callback);
  };
}
function saveSidebar(value: boolean) {
  sidebarFallback = value;
  try {
    localStorage.setItem("nexus-sidebar-collapsed", String(value));
  } catch {
    // Keep the toggle functional when browser storage is unavailable.
  }
  window.dispatchEvent(new Event("nexus-sidebar-change"));
}

function Application() {
  const client = useQueryClient();
  const router = useRouter();
  const path = usePathname();
  const user = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User | null>("/me"),
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    enabled: !!user.data,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => allResources<Resource>("/projects"),
    enabled: !!user.data,
  });
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => allResources<Resource>("/conversations"),
    enabled: !!user.data,
  });
  const [mobile, setMobile] = useState(false);
  const collapsed = useSyncExternalStore(
    subscribeSidebar,
    sidebarSnapshot,
    () => false,
  );
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [project, setProject] = useState("");
  const [archived, setArchived] = useState(false);
  const [editor, setEditor] = useState<{
    kind: string;
    value?: Resource;
  } | null>(null);
  const [confirm, setConfirm] = useState<{
    title: string;
    description: string;
    action: () => Promise<unknown>;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!mobile) return;
    const panel = document.getElementById("workspace-navigation");
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]',
        ) || [],
      ).filter((element) => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobile(false);
        document.getElementById("open-navigation")?.focus();
      } else if (event.key === "Tab") {
        const elements = focusable();
        const first = elements[0],
          last = elements.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, [mobile]);
  function report(e: unknown) {
    setError(
      e instanceof Error
        ? e.message
        : "An unexpected error occurred. Please retry.",
    );
  }
  async function refresh() {
    await client.invalidateQueries();
  }
  const createChat = useMutation<Resource, Error, boolean>({
    mutationFn: () =>
      write<Resource>("/conversations", {
        project_id:
          (path.startsWith("/chat/")
            ? conversations.data?.find((c) => path === "/chat/" + c.id)
                ?.project_id
            : project) || null,
      }),
    onSuccess: (value, navigate) => {
      setSearch("");
      setArchived(false);
      client.setQueryData<Resource[]>(["conversations"], (old) => [
        value,
        ...(old || []),
      ]);
      client.invalidateQueries({ queryKey: ["conversations"] });
      if (navigate) router.push("/chat/" + value.id);
      setMobile(false);
    },
    onError: report,
  });
  const selectedConversation = conversations.data?.find(
    (c) => path === "/chat/" + c.id,
  );
  const activeProject = selectedConversation
    ? selectedConversation.project_id || ""
    : project;
  const screen = path.split("/")[1] || "chat";
  const threadId = screen === "chat" ? path.split("/")[2] : undefined;
  const title =
    navigation.find((n) => n.path === "/" + screen)?.title || "Settings";
  useEffect(() => {
    const theme = user.data?.theme;
    if (!theme) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system"
          ? media.matches
            ? "dark"
            : "light"
          : theme || "light";
    };
    apply();
    try {
      localStorage.setItem("nexus-appearance", theme);
    } catch {
      // The current account theme still works when browser storage is unavailable.
    }
    if (theme === "system") media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [user.data?.theme]);
  if (user.isPending)
    return (
      <div className="full-center">
        <LoaderCircle className="spin" />
        <p>Opening your workspace…</p>
      </div>
    );
  if (!user.data) {
    if (
      user.data === null ||
      (user.error instanceof ApiError && user.error.status === 401)
    )
      return (
        <Auth
          onSuccess={() => {
            client.resetQueries();
          }}
        />
      );
    return (
      <div className="full-center">
        <h1>Aster is taking a moment</h1>
        <p role="alert">{user.error?.message}</p>
        <Button onClick={() => user.refetch()}>Retry connection</Button>
        <p className="muted">
          Start PostgreSQL and the Aster API using scripts/start.ps1.
        </p>
      </div>
    );
  }
  const currentUser = user.data;
  async function signOut() {
    try {
      await write("/auth/logout", {});
      await client.cancelQueries();
      client.removeQueries({
        predicate: (query) => query.queryKey[0] !== "me",
      });
      client.setQueryData(["me"], null);
      setMobile(false);
      setSearch("");
      setArchived(false);
      setProject("");
      router.replace("/");
    } catch (e) {
      report(e);
    }
  }
  const filteredConversations = conversations.data?.filter(
    (c) =>
      !!c.archived === archived &&
      c.title.toLowerCase().includes(search.toLowerCase()),
  );
  function deleteItem(kind: string, value: Resource) {
    setConfirm({
      title: "Delete " + (value.title || "item") + "?",
      description:
        kind === "projects"
          ? "This permanently deletes the project and its conversations, documents, tasks, notes and project memories."
          : "This permanently removes this item and associated processing state.",
      action: async () => {
        await api(`/${kind}/${value.id}?version=${value.version}`, {
          method: "DELETE",
        });
        if (kind === "conversations" && threadId === value.id)
          router.push("/chat");
        if (kind === "projects" && project === value.id) setProject("");
        await refresh();
      },
    });
  }
  return (
    <div className="app-shell">
      {mobile && (
        <button
          className="mobile-scrim"
          aria-label="Close navigation"
          onClick={() => {
            setMobile(false);
            document.getElementById("open-navigation")?.focus();
          }}
        />
      )}
      <aside
        id="workspace-navigation"
        aria-label="Workspace navigation"
        role={mobile ? "dialog" : undefined}
        aria-modal={mobile || undefined}
        className={
          "sidebar " +
          (mobile ? "mobile-open " : "") +
          (collapsed ? "sidebar-collapsed" : "")
        }
      >
        <Link className="brand" href="/chat">
          <span className="brand-mark">
            <Sparkles size={21} />
          </span>
          <span>
            Aster<span className="brand-sub">SPACE TO THINK</span>
          </span>
        </Link>
        <Button
          className="new-chat"
          onClick={() => {
            setProject(activeProject);
            setMobile(false);
            router.push("/chat");
          }}
          disabled={createChat.isPending}
        >
          <Plus size={17} />
          New conversation
        </Button>
        <label className="new-chat-scope">
          New chat in
          <select
            aria-label="New conversation workspace"
            value={activeProject}
            onChange={(e) => {
              setProject(e.target.value);
              router.push("/chat");
            }}
          >
            <option value="">Personal</option>
            {(projects.data || []).map((p) => (
              <option value={p.id} key={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        <nav aria-label="Main navigation">
          {navigation.map((n) => (
            <Link
              key={n.path}
              href={n.path}
              className={
                "nav-item " + (screen === n.path.slice(1) ? "active" : "")
              }
              onClick={() => setMobile(false)}
            >
              <n.icon size={18} />
              {n.title}
            </Link>
          ))}
        </nav>
        <div className="sidebar-divider" />
        <div className="sidebar-section">
          <span>
            {archived ? "ARCHIVED CONVERSATIONS" : "YOUR CONVERSATIONS"}
          </span>
          <button
            aria-label="Toggle archived conversations"
            aria-pressed={archived}
            title={
              archived
                ? "Show active conversations"
                : "Show archived conversations"
            }
            className={archived ? "accent-text" : ""}
            onClick={() => setArchived(!archived)}
          >
            <Archive size={15} />
          </button>
        </div>
        <label className="sidebar-search">
          <Search size={14} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a conversation"
            aria-label="Search conversations"
          />
        </label>
        {(search || archived) && (
          <button
            className="clear-chat-filters"
            onClick={() => {
              setSearch("");
              setArchived(false);
            }}
          >
            Clear conversation filters <X size={12} />
          </button>
        )}
        <div className="conversation-list">
          {[null, ...(projects.data || [])].map((group) => {
            const items = filteredConversations?.filter(
              (c) => (c.project_id || null) === (group?.id || null),
            );
            if (!items?.length) return null;
            return (
              <div key={group?.id || "personal"}>
                <div className="group-title">
                  {group ? <Folder size={12} /> : <MessageSquare size={12} />}
                  {group?.title || (archived ? "Archived" : "Personal")}
                </div>
                {items.map((c) => (
                  <div
                    className={
                      "conversation-link " +
                      (threadId === c.id ? "selected" : "")
                    }
                    key={c.id}
                  >
                    <Link
                      href={"/chat/" + c.id}
                      prefetch={false}
                      onClick={() => setMobile(false)}
                    >
                      {c.title}
                    </Link>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={"Rename " + c.title}
                      onClick={() =>
                        setEditor({ kind: "conversations", value: c })
                      }
                    >
                      <Pencil size={12} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={
                        (c.archived ? "Unarchive " : "Archive ") + c.title
                      }
                      onClick={async () => {
                        try {
                          await write(
                            "/conversations/" + c.id,
                            {
                              title: c.title,
                              project_id: c.project_id,
                              archived: !c.archived,
                              version: c.version,
                            },
                            "PUT",
                          );
                          await refresh();
                        } catch (e) {
                          report(e);
                        }
                      }}
                    >
                      <Archive size={12} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={"Delete " + c.title}
                      onClick={() => deleteItem("conversations", c)}
                    >
                      <Trash2 size={12} />
                    </Button>
                  </div>
                ))}
              </div>
            );
          })}
          {conversations.isPending && (
            <p className="sidebar-empty" role="status">
              Loading saved conversations…
            </p>
          )}
          {!conversations.isPending &&
            !conversations.error &&
            !filteredConversations?.length && (
              <p className="sidebar-empty">
                {search
                  ? "No matching conversations."
                  : "Your conversations will appear here."}
              </p>
            )}
        </div>
        <div className="sidebar-bottom">
          <Link
            href="/settings"
            className={
              "profile-link " + (screen === "settings" ? "active" : "")
            }
          >
            <span className="avatar">
              {currentUser.name.slice(0, 1).toUpperCase()}
            </span>
            <span>
              <strong>{currentUser.name}</strong>
              <small>Personal account</small>
            </span>
            <Settings size={17} />
          </Link>
          <Button
            variant="ghost"
            className="sidebar-logout"
            onClick={signOut}
            title="Log out"
          >
            <LogOut size={16} />
            <span>Log out</span>
          </Button>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            <Button
              variant="ghost"
              size="icon"
              className="desktop-menu"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => saveSidebar(!collapsed)}
            >
              <Menu size={19} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="mobile-menu"
              id="open-navigation"
              aria-label="Open navigation"
              aria-controls="workspace-navigation"
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </Button>
            <span className="breadcrumb">Workspace</span>
            <span className="slash">/</span>
            <strong>
              {threadId ? selectedConversation?.title || "Conversation" : title}
            </strong>
          </div>
          <div className="topbar-right">
            <span className={"connection " + (caps.data?.chat ? "online" : "")}>
              <span />
              {caps.data?.chat ? "AI configured" : "AI not connected"}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle dark mode"
              onClick={async () => {
                try {
                  await write(
                    "/me",
                    {
                      ...profileValues(currentUser),
                      theme:
                        document.documentElement.dataset.theme === "dark"
                          ? "light"
                          : "dark",
                    },
                    "PUT",
                  );
                  await refresh();
                } catch (e) {
                  report(e);
                }
              }}
            >
              <Sun size={18} className="theme-sun" />
              <Moon size={18} className="theme-moon" />
            </Button>
          </div>
        </header>
        {error && (
          <div className="alert error" role="alert">
            <span>{error}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Dismiss error"
              onClick={() => setError("")}
            >
              <X size={16} />
            </Button>
          </div>
        )}
        {(projects.error || conversations.error || caps.error) && (
          <div className="alert error" role="alert">
            Workspace data failed to load.
            <Button variant="ghost" onClick={refresh}>
              Retry
            </Button>
          </div>
        )}
        {screen === "chat" ? (
          <Chat
            key={threadId || "new"}
            threadId={threadId}
            user={currentUser}
            capabilities={caps.data}
            project={activeProject}
            setProject={setProject}
            projects={projects.data || []}
            createChat={() => createChat.mutateAsync(false)}
            report={report}
          />
        ) : screen === "settings" ? (
          <SettingsScreen
            user={currentUser}
            capabilities={caps.data}
            report={report}
            refresh={refresh}
            onLogout={signOut}
          />
        ) : (
          <Collection
            key={screen}
            kind={screen}
            projects={projects.data || []}
            project={project}
            setProject={setProject}
            edit={(kind, value) => setEditor({ kind, value })}
            remove={deleteItem}
            report={report}
            confirm={setConfirm}
            uploadLimit={caps.data?.upload_limit_mib || 10}
          />
        )}
      </main>
      {editor && (
        <Editor
          key={editor.value?.id || editor.kind}
          kind={editor.kind}
          value={editor.value}
          projects={projects.data || []}
          defaultProject={activeProject}
          onClose={() => setEditor(null)}
          onSave={async (values) => {
            await write(
              "/" + editor.kind + (editor.value ? "/" + editor.value.id : ""),
              values,
              editor.value ? "PUT" : "POST",
            );
            setEditor(null);
            await refresh();
          }}
        />
      )}
      <Modal
        open={!!confirm}
        onClose={() => !busy && setConfirm(null)}
        title={confirm?.title || "Confirm"}
        description={confirm?.description}
      >
        <div className="form-actions">
          <Button
            variant="secondary"
            onClick={() => setConfirm(null)}
            disabled={busy}
          >
            Keep it
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await confirm?.action();
                setConfirm(null);
              } catch (e) {
                report(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Deleting…" : "Delete permanently"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

const authSchema = z.object({
  email: z.email("Enter a valid email."),
  password: z.string().min(10, "Use at least 10 characters.").max(256),
  name: z
    .string()
    .trim()
    .min(1, "Enter your name.")
    .max(120, "Use at most 120 characters for your name."),
});
function Auth({ onSuccess }: { onSuccess: () => void }) {
  const [register, setRegister] = useState(false);
  const [error, setError] = useState("");
  const {
    register: field,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof authSchema>>({
    resolver: zodResolver(authSchema),
    defaultValues: { name: "Aster user", email: "", password: "" },
  });
  return (
    <main className="auth-layout">
      <Button
        className="auth-theme-toggle"
        variant="ghost"
        size="icon"
        aria-label="Toggle dark mode"
        title="Switch light or dark appearance"
        onClick={() => {
          const theme =
            document.documentElement.dataset.theme === "dark"
              ? "light"
              : "dark";
          document.documentElement.dataset.theme = theme;
          try {
            localStorage.setItem("nexus-appearance", theme);
          } catch {
            /* Appearance still works without storage. */
          }
        }}
      >
        <Sun size={18} className="theme-sun" />
        <Moon size={18} className="theme-moon" />
      </Button>
      <div className="auth-story">
        <Link href="/" className="brand">
          <span className="brand-mark">
            <Sparkles />
          </span>
          Aster
        </Link>
        <div>
          <span className="eyebrow">MAKE ROOM FOR GOOD THINKING</span>
          <h1>
            A little more clarity.
            <br />A lot more possibility.
          </h1>
          <p>
            Your conversations, knowledge and next steps.
            <br />
            Together in one thoughtful workspace.
          </p>
          <div className="auth-preview">
            <div>
              <MessageSquare size={18} />
              <span>Think it through</span>
            </div>
            <div>
              <FileText size={18} />
              <span>Connect your knowledge</span>
            </div>
            <div>
              <ListTodo size={18} />
              <span>Turn ideas into action</span>
            </div>
          </div>
        </div>
        <small>Built around your work. Controlled by you.</small>
      </div>
      <div className="auth-form">
        <div className="auth-card">
          <span className="eyebrow">YOUR SPACE TO THINK</span>
          <h2>{register ? "Make yourself at home" : "Welcome back"}</h2>
          <p className="muted">
            {register
              ? "Create a local account to start connecting the dots."
              : "Sign in and pick up where you left off."}
          </p>
          <form
            onSubmit={handleSubmit(async (data) => {
              setError("");
              try {
                await write("/auth/" + (register ? "register" : "login"), data);
                onSuccess();
              } catch (e) {
                setError((e as Error).message);
              }
            })}
          >
            {register && (
              <>
                <label>
                  Your name
                  <input
                    {...field("name")}
                    required
                    autoComplete="name"
                    aria-invalid={!!errors.name}
                    aria-describedby={
                      errors.name ? "auth-name-error" : undefined
                    }
                  />
                </label>
                {errors.name && (
                  <small id="auth-name-error" className="error-text">
                    {errors.name.message}
                  </small>
                )}
              </>
            )}
            <label>
              Email
              <input
                {...field("email")}
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
              />
            </label>
            {errors.email && (
              <small className="error-text">{errors.email.message}</small>
            )}
            <label>
              Password
              <input
                {...field("password")}
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                placeholder="At least 10 characters"
              />
            </label>
            {errors.password && (
              <small className="error-text">{errors.password.message}</small>
            )}
            {error && (
              <div className="alert error" role="alert">
                {error}
              </div>
            )}
            <Button className="full-width" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircle className="spin" size={17} />
              ) : null}
              {register ? "Create account" : "Sign in"}
              <ArrowUp size={15} className="rotate-right" />
            </Button>
          </form>
          <p className="auth-switch">
            {register ? "Already have an account?" : "New to Aster?"}{" "}
            <button
              onClick={() => {
                setRegister(!register);
                setError("");
              }}
            >
              {register ? "Sign in" : "Create an account"}
            </button>
          </p>
          <p className="fine-print">
            <ShieldCheck size={15} />
            Local email and password accounts. No email verification or email
            delivery.
          </p>
        </div>
      </div>
    </main>
  );
}

function ProjectSelect({
  value,
  onChange,
  projects,
  label = "Project",
}: {
  value: string;
  onChange: (v: string) => void;
  projects: Resource[];
  label?: string;
}) {
  return (
    <label className="select-label">
      <Folder size={15} />
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">
          {label.toLowerCase().startsWith("filter")
            ? "All projects"
            : "Personal · no project"}
        </option>
        {projects.map((p) => (
          <option value={p.id} key={p.id}>
            {p.title}
          </option>
        ))}
      </select>
      <ChevronDown size={13} />
    </label>
  );
}

function Chat({
  threadId,
  user,
  capabilities,
  project,
  setProject,
  projects,
  createChat,
  report,
}: {
  threadId?: string;
  user: User;
  capabilities?: Capabilities;
  project: string;
  setProject: (v: string) => void;
  projects: Resource[];
  createChat: () => Promise<Resource>;
  report: (e: unknown) => void;
}) {
  const client = useQueryClient();
  const router = useRouter();
  const [text, setText] = useState("");
  const [mode, setMode] = useState("auto");
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [showSources, setShowSources] = useState(false);
  const [expandedSources, setExpandedSources] = useState<string[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [activity, setActivity] = useState("");
  const [memoryUsed, setMemoryUsed] = useState<string[]>([]);
  const [jump, setJump] = useState(false);
  const [sending, setSending] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const file = useRef<HTMLInputElement>(null);
  const restoredScope = useRef(false);
  const history = useQuery({
    queryKey: ["history", threadId],
    queryFn: () => api<History>("/conversations/" + threadId + "/history"),
    enabled: !!threadId,
    refetchInterval: (query) =>
      query.state.data?.runs.some((r) =>
        ["queued", "running", "waiting"].includes(r.status),
      )
        ? 1500
        : false,
  });
  const docs = useQuery({
    queryKey: ["documents", project],
    queryFn: () =>
      allResources<Document>(
        "/documents" + (project ? "?project_id=" + project : ""),
      ),
    refetchInterval: 3000,
  });
  useEffect(() => {
    const previous = history.data?.runs.at(-1)?.input;
    const available = docs.data;
    if (!restoredScope.current && previous && available) {
      restoredScope.current = true;
      setMode(previous.mode || "auto");
      setSelectedDocs(
        (previous.document_ids || []).filter((id) =>
          available.some((doc) => doc.id === id),
        ),
      );
    }
  }, [history.data, docs.data]);
  const activeRun = history.data?.runs.find((r) =>
    ["queued", "running", "waiting"].includes(r.status),
  );
  const activeRunId = activeRun?.id;
  const activeRunStatus = activeRun?.status;
  useEffect(() => {
    if (!activeRunId || activeRunStatus === "waiting") return;
    const controller = new AbortController();
    let cursor = 0;
    let lastRefresh = 0;
    async function connect() {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(
            `/api/runs/${activeRunId}/events?cursor=${cursor}`,
            { signal: controller.signal, credentials: "same-origin" },
          );
          if (!response.ok || !response.body)
            throw new Error("Stream disconnected");
          const parser = new SSEParser((data) => {
            const event: Event = JSON.parse(data);
            cursor = Math.max(cursor, event.seq);
            if (event.type === "tool.started")
              setActivity("Using " + event.payload.name?.replaceAll("_", " "));
            if (event.type === "tool.completed")
              setActivity(
                event.payload.error ? event.payload.error : "Thinking…",
              );
            if (event.type === "memory.used")
              setMemoryUsed(event.payload.items?.map((i) => i.title) || []);
            if (
              event.type.startsWith("run.") ||
              event.type === "approval.required"
            )
              setActivity(
                event.type === "approval.required"
                  ? "Waiting for your review"
                  : "Thinking…",
              );
            if (
              Date.now() - lastRefresh > 120 ||
              event.type !== "message.delta"
            ) {
              client.invalidateQueries({ queryKey: ["history", threadId] });
              lastRefresh = Date.now();
            }
          }, cursor);
          const reader = response.body.getReader();
          while (true) {
            const result = await reader.read();
            if (result.done) {
              parser.push(new Uint8Array(), true);
              break;
            }
            parser.push(result.value);
          }
          await client.invalidateQueries({ queryKey: ["history", threadId] });
          const run = await api<Run>("/runs/" + activeRunId);
          if (!["running", "queued"].includes(run.status)) return;
        } catch {
          if (controller.signal.aborted) return;
          setActivity("Reconnecting to your saved run…");
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }
    connect();
    return () => controller.abort();
  }, [activeRunId, activeRunStatus, client, threadId]);
  useEffect(() => {
    if (!threadId || !history.data?.messages.length) {
      if (scroll.current) scroll.current.scrollTop = 0;
    } else if (nearBottom.current)
      bottom.current?.scrollIntoView({ behavior: "instant", block: "end" });
  }, [history.data, threadId]);
  async function send(message = text) {
    if (
      !message.trim() ||
      sending ||
      activeRun ||
      !capabilities?.chat ||
      pendingDocuments
    )
      return;
    setSending(true);
    try {
      let id = threadId;
      if (!id) {
        const created = await createChat();
        id = created.id;
      }
      await write("/conversations/" + id + "/runs", {
        message,
        mode,
        document_ids: selectedDocs,
      });
      setText("");
      setActivity("Queued for your assistant…");
      nearBottom.current = true;
      if (!threadId) router.push("/chat/" + id);
      // A history request started before the run was committed can return an
      // empty snapshot after invalidation. Replace it with a post-commit read.
      await client.cancelQueries({ queryKey: ["history", id], exact: true });
      await client.fetchQuery({
        queryKey: ["history", id],
        queryFn: () => api<History>("/conversations/" + id + "/history"),
      });
      client.invalidateQueries({ queryKey: ["conversations"] });
    } catch (e) {
      report(e);
    } finally {
      setSending(false);
    }
  }
  async function openSource(id: string) {
    try {
      setSource(await api<Source>("/sources/" + id));
    } catch {
      setSource({
        title: "Source unavailable",
        excerpt:
          "This source was deleted or is no longer available to your account.",
      });
    }
  }
  const messages = history.data?.messages || [];
  const pendingDocuments = selectedDocs.some(
    (id) => docs.data?.find((d) => d.id === id)?.status !== "ready",
  );
  const failedDocuments = selectedDocs.some(
    (id) => docs.data?.find((d) => d.id === id)?.status === "failed",
  );
  if (
    threadId &&
    history.error instanceof ApiError &&
    history.error.status === 404
  )
    return (
      <div className="chat-workspace">
        <div className="empty" role="alert">
          <MessageSquare size={28} />
          <h2>Conversation not found</h2>
          <p>It may have been deleted or is unavailable to your account.</p>
          <Link href="/chat" className="accent-text">
            Back to conversations
          </Link>
        </div>
      </div>
    );
  return (
    <div className="chat-workspace">
      <div className="chat-toolbar">
        <div>
          <span className="assistant-dot">
            <Sparkles size={14} />
          </span>
          <strong>Aster assistant</strong>
        </div>
        {!threadId ? (
          <ProjectSelect
            value={project}
            onChange={(value) => {
              setSelectedDocs([]);
              setProject(value);
            }}
            projects={projects}
            label="Chat project"
          />
        ) : (
          <span className="muted small-text">
            {projects.find((p) => p.id === project)?.title ||
              "Personal conversation"}
          </span>
        )}
      </div>
      <div
        className="chat-scroll"
        ref={scroll}
        onScroll={() => {
          const el = scroll.current;
          if (el) {
            nearBottom.current =
              el.scrollHeight - el.scrollTop - el.clientHeight < 120;
            setJump(!nearBottom.current);
          }
        }}
      >
        {(!threadId || (!messages.length && !history.isPending)) && (
          <Welcome name={user.name} setText={setText} />
        )}
        {threadId && history.isPending && (
          <div className="empty">
            <LoaderCircle className="spin" />
            <p>Loading saved conversation…</p>
          </div>
        )}
        {history.error && (
          <div className="alert error" role="alert">
            {history.error.message}
            <Button variant="ghost" onClick={() => history.refetch()}>
              Retry
            </Button>
          </div>
        )}
        <div className="transcript">
          {messages.map((message) => (
            <article className={"message " + message.role} key={message.id}>
              <div className={"message-avatar " + message.role}>
                {message.role === "user" ? (
                  user.name.slice(0, 1)
                ) : (
                  <Sparkles size={17} />
                )}
              </div>
              <div className="message-body">
                <div className="message-heading">
                  {message.role === "user" ? "You" : "Aster"}
                  <time
                    dateTime={message.created_at}
                    title={new Intl.DateTimeFormat("en", {
                      dateStyle: "full",
                      timeStyle: "long",
                      timeZone: user.timezone,
                    }).format(new Date(message.created_at))}
                  >
                    {new Intl.DateTimeFormat("en", {
                      hour: "2-digit",
                      minute: "2-digit",
                      hour12: true,
                      timeZone: user.timezone,
                    }).format(new Date(message.created_at))}
                  </time>
                </div>
                {message.content ? (
                  <Markdown
                    text={message.content}
                    onSource={openSource}
                    allowedSources={message.sources?.flatMap((s) =>
                      s.id ? [s.id] : [],
                    )}
                    allowedUrls={message.sources?.flatMap((s) =>
                      s.url ? [s.url] : [],
                    )}
                  />
                ) : (
                  <span className="response-placeholder">
                    Preparing a response<span className="spin"> · </span>
                  </span>
                )}
                {message.interrupted && (
                  <span className="tag">Interrupted · partial response</span>
                )}
                {message.sources?.length > 0 && (
                  <div className="source-chips">
                    {message.sources
                      .slice(
                        0,
                        expandedSources.includes(message.id) ? undefined : 6,
                      )
                      .map((s, index) =>
                        s.id ? (
                          <button
                            key={s.id}
                            className="source-chip"
                            onClick={() => openSource(s.id!)}
                          >
                            <FileText size={13} />
                            {s.filename}
                            {s.page
                              ? " · p. " + s.page
                              : s.section
                                ? " · " + s.section
                                : ""}
                          </button>
                        ) : s.url && /^https?:\/\//i.test(s.url) ? (
                          <a
                            key={index}
                            href={s.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="source-chip"
                          >
                            {s.title || new URL(s.url).hostname} ↗
                          </a>
                        ) : s.type === "google_search_suggestions" && s.html ? (
                          <iframe
                            key={index}
                            className="google-search-suggestions"
                            title="Google Search suggestions"
                            sandbox="allow-popups allow-popups-to-escape-sandbox"
                            srcDoc={
                              "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'\">" +
                              s.html
                            }
                          />
                        ) : null,
                      )}
                    {message.sources.length > 6 && (
                      <button
                        className="source-chip"
                        aria-expanded={expandedSources.includes(message.id)}
                        onClick={() =>
                          setExpandedSources((current) =>
                            current.includes(message.id)
                              ? current.filter((id) => id !== message.id)
                              : [...current, message.id],
                          )
                        }
                      >
                        {expandedSources.includes(message.id)
                          ? "Show fewer sources"
                          : `Show ${message.sources.length - 6} more sources`}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
          {history.data?.proposals
            .filter((proposal) => proposal.status === "pending")
            .map((proposal) => (
              <Approval
                key={proposal.id}
                proposal={proposal}
                onChange={() =>
                  client.invalidateQueries({ queryKey: ["history", threadId] })
                }
                report={report}
              />
            ))}
          {activeRun && (
            <div className="run-activity" role="status">
              {activeRun.status === "waiting" ? (
                <ShieldCheck size={16} />
              ) : (
                <LoaderCircle size={16} className="spin" />
              )}
              <span>
                {activeRun.status === "waiting"
                  ? "Waiting for your review"
                  : activeRun.status === "queued"
                    ? "Waiting for a worker…"
                    : activity || "Thinking…"}
              </span>
              <Elapsed since={activeRun.created_at} />
            </div>
          )}
          {memoryUsed.length > 0 && (
            <div className="memory-used">
              <Brain size={13} />
              Memory used: {memoryUsed.join(", ")}
            </div>
          )}
          {history.data?.runs
            .slice(-1)
            .filter((r) => ["failed", "canceled"].includes(r.status))
            .map((r) => (
              <div className="alert error" role="alert" key={r.id}>
                {r.status === "canceled"
                  ? "Generation stopped. Your saved messages remain."
                  : r.error}
                <Button
                  variant="ghost"
                  onClick={() => {
                    const last = messages
                      .filter((m) => m.role === "user")
                      .at(-1);
                    if (last) setText(last.content);
                  }}
                >
                  Prepare retry
                </Button>
              </div>
            ))}
          <div ref={bottom} />
        </div>
      </div>
      {jump && messages.length > 0 && (
        <Button
          className="jump"
          variant="secondary"
          onClick={() => {
            nearBottom.current = true;
            setJump(false);
            bottom.current?.scrollIntoView({ behavior: "smooth" });
          }}
        >
          <ArrowDown size={15} />
          Latest
        </Button>
      )}
      <div className="composer-area">
        {!capabilities?.chat && (
          <div className="capability-note">
            <CircleHelp size={14} />
            <span>{capabilities?.reason || "Checking AI connection…"}</span>
          </div>
        )}
        {showSources && (
          <div className="scope-panel">
            <div>
              <strong>Source scope</strong>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close sources"
                onClick={() => setShowSources(false)}
              >
                <X size={14} />
              </Button>
            </div>
            {selectedDocs.length > 0 && (
              <Button
                variant="ghost"
                size="small"
                onClick={() => setSelectedDocs([])}
              >
                Clear source selection
              </Button>
            )}
            <p className="muted">
              Select ready documents. With none selected, search covers
              authorized documents{project ? " in this project" : ""}.
            </p>
            {docs.data?.map((d) => (
              <label key={d.id}>
                <input
                  type="checkbox"
                  disabled={
                    d.status !== "ready" && !selectedDocs.includes(d.id)
                  }
                  checked={selectedDocs.includes(d.id)}
                  onChange={(e) =>
                    setSelectedDocs((prev) =>
                      e.target.checked
                        ? [...prev, d.id]
                        : prev.filter((id) => id !== d.id),
                    )
                  }
                />
                {d.filename}
                <span className="tag">{d.status}</span>
                {d.error && <span className="error-text">{d.error}</span>}
              </label>
            ))}
            {!docs.data?.length && (
              <p>No documents yet. Attach a file to add one.</p>
            )}
          </div>
        )}
        <div className="composer">
          <textarea
            aria-label="Message Aster"
            dir="auto"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ask anything, or bring your next idea…"
            rows={3}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                send();
              }
            }}
          />
          <div className="composer-controls">
            <div>
              <input
                type="file"
                ref={file}
                hidden
                accept=".pdf,.docx,.txt,.md"
                onChange={async (e) => {
                  const picked = e.target.files?.[0];
                  if (!picked) return;
                  try {
                    validateUpload(
                      picked,
                      capabilities?.upload_limit_mib || 10,
                    );
                    const body = new FormData();
                    body.append("file", picked);
                    if (project) body.append("project_id", project);
                    const attached = await api<Document>("/documents", {
                      method: "POST",
                      body,
                    });
                    setSelectedDocs((old) => [
                      ...new Set([...old, attached.id]),
                    ]);
                    await client.invalidateQueries({ queryKey: ["documents"] });
                    setShowSources(true);
                  } catch (err) {
                    report(err);
                  }
                  e.target.value = "";
                }}
              />
              <Button
                variant="ghost"
                size="icon"
                aria-label="Attach a document"
                onClick={() => file.current?.click()}
              >
                <Paperclip size={18} />
              </Button>
              <select
                aria-label="Assistant mode"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="auto">✦ Auto</option>
                <option value="documents" disabled={!capabilities?.embeddings}>
                  Documents
                </option>
                <option value="web" disabled={!capabilities?.web}>
                  Web
                </option>
              </select>
              <button
                className="scope-button"
                onClick={() => setShowSources(!showSources)}
              >
                <FileText size={14} />
                {selectedDocs.length
                  ? `${selectedDocs.length} ${selectedDocs.length === 1 ? "source" : "sources"}`
                  : "Sources"}
                <ChevronDown size={12} />
              </button>
            </div>
            {activeRun ? (
              <Button
                variant="secondary"
                size="icon"
                aria-label="Stop generation"
                onClick={async () => {
                  try {
                    await write("/runs/" + activeRun.id + "/cancel", {});
                    await history.refetch();
                  } catch (e) {
                    report(e);
                  }
                }}
              >
                <Square size={15} />
              </Button>
            ) : (
              <Button
                size="icon"
                aria-label="Send message"
                disabled={
                  !text.trim() ||
                  sending ||
                  !capabilities?.chat ||
                  pendingDocuments
                }
                onClick={() => send()}
              >
                {sending ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <ArrowUp size={20} />
                )}
              </Button>
            )}
          </div>
        </div>
        {pendingDocuments && (
          <p className="attachment-status" role="status">
            {failedDocuments
              ? "An attachment could not be processed. Open Sources to remove it, or retry indexing in Documents."
              : "Preparing attached documents. Open Sources to check progress or remove a selection."}
          </p>
        )}
        <div className="composer-footer">
          <span>Aster can make mistakes. Check important information.</span>
          <span>Shift + Enter for a new line</span>
        </div>
      </div>
      <Modal
        title={source?.filename || source?.title || "Source"}
        description={
          source?.page
            ? "Page " + source.page
            : source?.section || "Authorized source excerpt"
        }
        open={!!source}
        onClose={() => setSource(null)}
        wide
      >
        <div className="excerpt">{source?.excerpt}</div>
        {source?.media_type === "application/pdf" && (
          <PdfPreview
            key={source.document_id}
            id={source.document_id!}
            initialPage={source.page || 1}
          />
        )}
      </Modal>
    </div>
  );
}

function Welcome({
  name,
  setText,
}: {
  name: string;
  setText: (v: string) => void;
}) {
  return (
    <div className="welcome">
      <div className="welcome-symbol">
        <Sparkles size={30} strokeWidth={1.5} />
      </div>
      <span className="eyebrow">A LITTLE SPACE TO THINK BIG</span>
      <h1>What’s on your mind, {name.split(" ")[0]}?</h1>
      <p>
        Explore an idea. Understand a document. Make a plan.
        <br />
        Let’s connect the dots.
      </p>
      <div className="suggestions">
        {[
          {
            icon: Sparkles,
            title: "Explore an idea",
            text: "Help me think through an idea and ask me useful questions.",
          },
          {
            icon: FileText,
            title: "Understand a document",
            text: "Explain my selected proposal with source citations.",
          },
          {
            icon: ListTodo,
            title: "Make a plan",
            text: "Help me plan my next two weeks. Ask about my goals first.",
          },
          {
            icon: BookOpen,
            title: "Build something",
            text: "Help me write clean code. Ask what I want to build.",
          },
        ].map((item) => (
          <button key={item.title} onClick={() => setText(item.text)}>
            <item.icon size={18} />
            <strong>{item.title}</strong>
            <span>{item.text}</span>
            <ArrowUp size={14} className="suggestion-arrow" />
          </button>
        ))}
      </div>
    </div>
  );
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <small>
      {Math.max(0, Math.round((now - new Date(since).getTime()) / 1000))}s
    </small>
  );
}

function Approval({
  proposal,
  onChange,
  report,
}: {
  proposal: Proposal;
  onChange: () => Promise<unknown>;
  report: (e: unknown) => void;
}) {
  const [items, setItems] = useState<ActionItem[]>(
    proposal.decision?.payload.items || proposal.payload.items,
  );
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  async function decide(approve: boolean) {
    setBusy(true);
    try {
      await write("/proposals/" + proposal.id + "/decision", {
        approve,
        version: proposal.version,
        payload: approve ? { items } : null,
      });
      await onChange();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  function change(index: number, key: keyof ActionItem, value: unknown) {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
    );
  }
  return (
    <section className="approval-card">
      <div className="approval-heading">
        <span className="approval-icon">
          <ShieldCheck size={20} />
        </span>
        <div>
          <span className="eyebrow">YOU’RE IN CONTROL</span>
          <h3>
            {proposal.action.replace(".", " · ")}
            <span className={"tag status-" + proposal.status}>
              {proposal.status === "approved"
                ? "Saving approved changes…"
                : proposal.status}
            </span>
          </h3>
        </div>
      </div>
      <p className="muted">
        {proposal.status === "pending"
          ? "Review this proposal before Aster changes your workspace."
          : proposal.status === "completed"
            ? "Approved changes have been saved."
            : proposal.status === "rejected"
              ? "Rejected. No changes were saved."
              : "This proposal is no longer waiting for a decision."}
      </p>
      {items.map((item, index) => (
        <div
          className={"proposal-item " + (!item.include ? "excluded" : "")}
          key={item.id || index}
        >
          {proposal.status === "pending" && (
            <input
              type="checkbox"
              aria-label={"Include proposed item " + (index + 1)}
              checked={item.include}
              onChange={(e) => change(index, "include", e.target.checked)}
            />
          )}
          <div>
            {!item.include && proposal.status !== "pending" && (
              <span className="tag">Excluded · not saved</span>
            )}
            {editing && proposal.status === "pending" ? (
              <>
                <label>
                  Title
                  <input
                    value={item.title || ""}
                    onChange={(e) => change(index, "title", e.target.value)}
                  />
                </label>
                {proposal.action.startsWith("tasks") ? (
                  <>
                    <label>
                      Description
                      <textarea
                        value={item.description || ""}
                        onChange={(e) =>
                          change(index, "description", e.target.value)
                        }
                      />
                    </label>
                    <div className="field-row">
                      <label>
                        Due date
                        <input
                          type="date"
                          value={item.due_date || ""}
                          onChange={(e) =>
                            change(index, "due_date", e.target.value || null)
                          }
                        />
                      </label>
                      <label>
                        Priority
                        <select
                          value={item.priority || "medium"}
                          onChange={(e) =>
                            change(index, "priority", e.target.value)
                          }
                        >
                          <option>low</option>
                          <option>medium</option>
                          <option>high</option>
                        </select>
                      </label>
                      <label>
                        Status
                        <select
                          value={item.status || "todo"}
                          onChange={(e) =>
                            change(index, "status", e.target.value)
                          }
                        >
                          <option value="todo">To do</option>
                          <option value="in_progress">In progress</option>
                          <option value="done">Done</option>
                        </select>
                      </label>
                    </div>
                  </>
                ) : (
                  <>
                    <label>
                      Content
                      <textarea
                        value={item.content || ""}
                        onChange={(e) =>
                          change(index, "content", e.target.value)
                        }
                      />
                    </label>
                    {proposal.action.startsWith("memories") && (
                      <>
                        <label>
                          Category
                          <select
                            aria-label="Memory category"
                            value={item.category || "preference"}
                            onChange={(e) =>
                              change(index, "category", e.target.value)
                            }
                          >
                            <option value="preference">Preference</option>
                            <option value="profile">Profile fact</option>
                            <option value="goal">Goal</option>
                            <option value="project_decision">
                              Project decision
                            </option>
                          </select>
                        </label>
                        <label className="switch-label">
                          <input
                            type="checkbox"
                            checked={item.enabled ?? true}
                            onChange={(e) =>
                              change(index, "enabled", e.target.checked)
                            }
                          />
                          Enable proposed memory
                        </label>
                      </>
                    )}
                  </>
                )}
              </>
            ) : (
              <>
                <strong>{item.title || item.id}</strong>
                <p>{item.description || item.content}</p>
                <div className="item-meta">
                  {item.due_date && <span>Due {item.due_date}</span>}
                  {item.priority && <span>{item.priority} priority</span>}
                  {item.status && (
                    <span>{item.status.replaceAll("_", " ")}</span>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      ))}
      {proposal.status === "pending" && (
        <div className="approval-actions">
          <Button
            variant="ghost"
            onClick={() => setEditing(!editing)}
            disabled={busy}
          >
            <Pencil size={14} />
            {editing ? "Preview" : "Edit proposal"}
          </Button>
          <span />
          <Button
            variant="secondary"
            onClick={() => decide(false)}
            disabled={busy}
          >
            Reject
          </Button>
          <Button
            onClick={() => decide(true)}
            disabled={busy || !items.some((i) => i.include)}
          >
            <Check size={15} />
            {busy
              ? "Saving decision…"
              : editing
                ? "Approve edited selection"
                : "Approve selection"}
          </Button>
        </div>
      )}
    </section>
  );
}

const descriptions: Record<string, string> = {
  projects: "Give every idea a place to grow.",
  documents: "Your knowledge, ready when you need it.",
  tasks: "Turn the next step into progress.",
  notes: "Keep the thoughts worth coming back to.",
  memories: "Choose what Aster remembers about you.",
};
function Collection({
  kind,
  projects,
  project,
  setProject,
  edit,
  remove,
  report,
  confirm,
  uploadLimit,
}: {
  kind: string;
  projects: Resource[];
  project: string;
  setProject: (v: string) => void;
  edit: (kind: string, value?: Resource) => void;
  remove: (kind: string, value: Resource) => void;
  report: (e: unknown) => void;
  uploadLimit: number;
  confirm: (value: {
    title: string;
    description: string;
    action: () => Promise<unknown>;
  }) => void;
}) {
  const client = useQueryClient();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [board, setBoard] = useState(false);
  const [offset, setOffset] = useState(0);
  const file = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [changingTask, setChangingTask] = useState(false);
  const [preview, setPreview] = useState<{
    id: string;
    filename: string;
  } | null>(null);
  const [drag, setDrag] = useState(false);
  const data = useQuery({
    queryKey: [
      kind,
      q,
      project,
      status,
      priority,
      kind === "memories" ? 0 : offset,
    ],
    queryFn: () =>
      api<(Resource & Partial<Document>)[]>(
        `/${kind}?q=${encodeURIComponent(q)}&limit=101&offset=${offset}${kind !== "projects" && kind !== "memories" && project ? "&project_id=" + project : ""}${status ? "&status=" + status : ""}${kind === "tasks" && priority ? "&priority=" + priority : ""}`,
      ),
    refetchInterval: kind === "documents" ? 2500 : false,
  });
  async function upload(files: FileList | File[]) {
    setUploading(true);
    try {
      for (const selected of Array.from(files)) {
        validateUpload(selected, uploadLimit);
        const body = new FormData();
        body.append("file", selected);
        if (project) body.append("project_id", project);
        await api("/documents", { method: "POST", body });
      }
      await client.invalidateQueries({ queryKey: ["documents"] });
    } catch (e) {
      report(e);
    } finally {
      setUploading(false);
    }
  }
  const scopedItems =
    data.data?.filter(
      (item) => kind !== "memories" || !project || item.project_id === project,
    ) || [];
  const items =
    kind === "memories"
      ? scopedItems.slice(offset, offset + 100)
      : scopedItems.slice(0, 100);
  const hasNext =
    scopedItems.length > (kind === "memories" ? offset + 100 : 100);
  const singular = kind === "memories" ? "memory" : kind.slice(0, -1);
  function card(item: Resource & Partial<Document>) {
    return (
      <article
        className={
          "resource-card " + (kind === "projects" ? "project-card" : "")
        }
        key={item.id}
      >
        <div className="resource-top">
          <span className="resource-icon">
            {kind === "projects" ? (
              <Folder size={19} />
            ) : kind === "documents" ? (
              <FileText size={19} />
            ) : kind === "memories" ? (
              <Brain size={19} />
            ) : kind === "notes" ? (
              <BookOpen size={19} />
            ) : (
              <ListTodo size={19} />
            )}
          </span>
          <div className="card-actions">
            {kind !== "documents" && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={"Edit " + item.title}
                disabled={kind === "tasks" && changingTask}
                onClick={() => edit(kind, item)}
              >
                <Pencil size={15} />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label={"Delete " + (item.filename || item.title)}
              disabled={kind === "tasks" && changingTask}
              onClick={() => remove(kind, item)}
            >
              <Trash2 size={15} />
            </Button>
          </div>
        </div>
        <h3>{kind === "documents" ? item.filename : item.title}</h3>
        {item.description && <p className="clamp">{item.description}</p>}
        {kind === "notes" && (
          <div className="note-preview">
            <Markdown text={(item.content || "").slice(0, 400)} />
          </div>
        )}
        {kind === "memories" && (
          <>
            <p>{item.content}</p>
            <MemoryToggle item={item} report={report} />
            <small className="muted">
              {item.category?.replaceAll("_", " ")} ·{" "}
              {item.provenance?.startsWith("Conversation ")
                ? "Saved from a conversation"
                : item.provenance}
            </small>
          </>
        )}
        <div className="item-meta">
          {item.project_id && (
            <span>
              <Folder size={12} />
              {projects.find((p) => p.id === item.project_id)?.title ||
                "Project"}
            </span>
          )}
          {item.status && (
            <span className={"tag status-" + item.status}>
              {item.status.replaceAll("_", " ")}
            </span>
          )}
          {item.priority && (
            <span className={"priority-" + item.priority}>{item.priority}</span>
          )}
          {item.due_date && <span>Due {item.due_date}</span>}
          {item.size && <span>{(item.size / 1024).toFixed(1)} KB</span>}
        </div>
        {item.error && (
          <p className="error-text" role="alert">
            {item.error}
          </p>
        )}
        {kind === "documents" && (
          <>
            <small className="muted">
              {item.embedding_model ||
                "Indexing requires your configured provider key."}
            </small>
            {["failed", "ready"].includes(item.status || "") && (
              <Button
                variant="secondary"
                size="small"
                onClick={async () => {
                  try {
                    await write("/documents/" + item.id + "/retry", {});
                    await data.refetch();
                  } catch (e) {
                    report(e);
                  }
                }}
              >
                {item.status === "ready"
                  ? "Reindex document"
                  : "Retry indexing"}
              </Button>
            )}
            {item.media_type === "application/pdf" && (
              <button
                className="text-link"
                onClick={() =>
                  setPreview({ id: item.id, filename: item.filename || "PDF" })
                }
              >
                Preview PDF ↗
              </button>
            )}
          </>
        )}
        {kind === "projects" && (
          <Button
            variant="secondary"
            size="small"
            onClick={() => {
              setProject(item.id);
              router.push("/chat");
            }}
          >
            Open project workspace ↗
          </Button>
        )}
        {kind === "tasks" && (
          <Button
            variant="secondary"
            size="small"
            disabled={changingTask}
            onClick={async () => {
              setChangingTask(true);
              try {
                const updated = await write<Resource>(
                  "/tasks/" + item.id,
                  {
                    title: item.title,
                    description: item.description,
                    status: item.status === "done" ? "todo" : "done",
                    priority: item.priority,
                    due_date: item.due_date,
                    project_id: item.project_id,
                    version: item.version,
                  },
                  "PUT",
                );
                client.setQueriesData<Resource[]>(
                  { queryKey: ["tasks"] },
                  (old) =>
                    old?.map((task) =>
                      task.id === updated.id ? updated : task,
                    ),
                );
                await client.invalidateQueries({ queryKey: ["tasks"] });
              } catch (e) {
                report(e);
              } finally {
                setChangingTask(false);
              }
            }}
          >
            <Check size={13} />
            {item.status === "done" ? "Reopen task" : "Mark done"}
          </Button>
        )}
      </article>
    );
  }
  return (
    <div className="collection">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR WORKSPACE, CONNECTED</span>
          <h1>{kind[0]?.toUpperCase() + kind.slice(1)}</h1>
          <p>{descriptions[kind]}</p>
        </div>
        <Button
          onClick={() =>
            kind === "documents" ? file.current?.click() : edit(kind)
          }
        >
          <Plus size={17} />
          {kind === "documents" ? "Upload document" : "New " + singular}
        </Button>
      </div>
      <div className="collection-toolbar">
        <label className="search-field">
          <Search size={17} />
          <input
            placeholder={"Search " + kind}
            aria-label={"Search " + kind}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        {kind !== "projects" && (
          <ProjectSelect
            value={project}
            onChange={(v) => {
              setProject(v);
              setOffset(0);
            }}
            projects={projects}
            label="Filter project"
          />
        )}
        {kind === "tasks" && (
          <>
            <select
              aria-label="Filter task status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All statuses</option>
              <option value="todo">To do</option>
              <option value="in_progress">In progress</option>
              <option value="done">Done</option>
            </select>
            <select
              aria-label="Filter task priority"
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All priorities</option>
              <option value="low">Low priority</option>
              <option value="medium">Medium priority</option>
              <option value="high">High priority</option>
            </select>
            <Button
              variant="secondary"
              size="icon"
              aria-label={
                board ? "Switch to task list" : "Switch to task board"
              }
              onClick={() => setBoard(!board)}
            >
              {board ? <ListTodo size={17} /> : <LayoutGrid size={17} />}
            </Button>
          </>
        )}
      </div>
      {kind === "documents" && (
        <div
          className={"upload-zone " + (drag ? "dragging" : "")}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            upload(e.dataTransfer.files);
          }}
        >
          <span className="upload-icon">
            <FileText size={23} />
          </span>
          <strong>
            {uploading
              ? "Uploading your documents…"
              : "Bring your knowledge into the conversation"}
          </strong>
          <p>
            Drop files here, or{" "}
            <button className="text-link" onClick={() => file.current?.click()}>
              browse files
            </button>
          </p>
          <small>
            PDF, DOCX, TXT, Markdown · {uploadLimit} MiB per file · text
            extraction only, no OCR
          </small>
          <input
            ref={file}
            hidden
            type="file"
            accept=".pdf,.docx,.txt,.md"
            multiple
            onChange={(e) => {
              if (e.target.files) upload(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      )}
      {kind === "memories" && (
        <div className="info-panel">
          <Brain size={20} />
          <div>
            <strong>A memory you can manage</strong>
            <p>
              These saved preferences and facts can be used across your
              conversations. Disabling memory in Settings stops reading and
              writing it. Forgetting a memory keeps your visible chat history.
            </p>
          </div>
          <Button
            variant="ghost"
            onClick={() =>
              confirm({
                title: "Clear all saved memories?",
                description:
                  "This deletes durable memories across your account. Your conversations remain.",
                action: async () => {
                  await write("/memories/clear", {});
                  await data.refetch();
                },
              })
            }
          >
            Clear all
          </Button>
        </div>
      )}
      {data.isPending ? (
        <div className="empty">
          <LoaderCircle className="spin" />
          Loading {kind}…
        </div>
      ) : data.error ? (
        <div className="alert error" role="alert">
          {data.error.message}
          <Button variant="ghost" onClick={() => data.refetch()}>
            Retry
          </Button>
        </div>
      ) : !items.length ? (
        <div className="empty">
          <span className="empty-icon">
            <Folder size={28} />
          </span>
          <h2>{q ? "No matches yet" : "A fresh space for your " + kind}</h2>
          <p>
            {q
              ? "Try a different search or project filter."
              : "Add your first " + singular + " to get started."}
          </p>
          <Button
            variant="secondary"
            onClick={() =>
              kind === "documents" ? file.current?.click() : edit(kind)
            }
          >
            <Plus size={15} />
            Add {singular}
          </Button>
        </div>
      ) : board && kind === "tasks" ? (
        <div className="task-board">
          {["todo", "in_progress", "done"].map((s) => (
            <section key={s}>
              <h3>
                {s.replaceAll("_", " ")}
                <span className="tag">
                  {items.filter((i) => i.status === s).length}
                </span>
              </h3>
              {items.filter((i) => i.status === s).map(card)}
            </section>
          ))}
        </div>
      ) : (
        <div
          className={"resource-grid " + (kind === "tasks" ? "task-list" : "")}
        >
          {items.map(card)}
        </div>
      )}
      {(offset > 0 || hasNext) && (
        <div className="pagination">
          <Button
            variant="ghost"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 100))}
          >
            Previous
          </Button>
          <span className="muted">
            {items.length
              ? `${offset + 1}–${offset + items.length}`
              : "0 items"}
          </span>
          <Button
            variant="ghost"
            disabled={!hasNext}
            onClick={() => setOffset(offset + 100)}
          >
            Next
          </Button>
        </div>
      )}
      {preview && (
        <Modal
          open
          wide
          title={preview.filename}
          description="View your document, page by page."
          onClose={() => setPreview(null)}
        >
          <PdfPreview key={preview.id} id={preview.id} />
        </Modal>
      )}
    </div>
  );
}

function Editor({
  kind,
  value,
  projects,
  defaultProject,
  onClose,
  onSave,
}: {
  kind: string;
  value?: Resource;
  projects: Resource[];
  defaultProject: string;
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}) {
  const [title, setTitle] = useState(value?.title || "");
  const [description, setDescription] = useState(value?.description || "");
  const [content, setContent] = useState(value?.content || "");
  const [instructions, setInstructions] = useState(value?.instructions || "");
  const [projectId, setProjectId] = useState(
    value?.project_id || defaultProject || "",
  );
  const [status, setStatus] = useState(value?.status || "todo");
  const [priority, setPriority] = useState(value?.priority || "medium");
  const [due, setDue] = useState(value?.due_date || "");
  const [category, setCategory] = useState(value?.category || "preference");
  const [enabled, setEnabled] = useState(value?.enabled ?? true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const editorFields = {
    title,
    description,
    content,
    instructions,
    projectId,
    status,
    priority,
    due,
    category,
    enabled,
  };
  const [initialFields] = useState(editorFields);
  const dirty = (
    Object.keys(editorFields) as (keyof typeof editorFields)[]
  ).some((key) => editorFields[key] !== initialFields[key]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function requestClose() {
    if (busy) return;
    if (dirty) setDiscarding(true);
    else onClose();
  }
  return (
    <>
      <Modal
        title={
          (value ? "Edit " : "New ") +
          (kind === "memories"
            ? "memory"
            : kind === "conversations"
              ? "conversation"
              : kind.slice(0, -1))
        }
        open
        onClose={requestClose}
        wide={kind === "notes"}
      >
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            const values: Record<string, unknown> = {
              title,
              version: value?.version,
            };
            if (kind === "projects")
              Object.assign(values, { description, instructions });
            else Object.assign(values, { project_id: projectId || null });
            if (kind === "tasks")
              Object.assign(values, {
                description,
                status,
                priority,
                due_date: due || null,
              });
            if (kind === "notes") values.content = content;
            if (kind === "memories")
              Object.assign(values, { content, category, enabled });
            if (kind === "conversations")
              values.archived = value?.archived || false;
            try {
              await onSave(values);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Title
            <input
              required
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              data-autofocus
            />
          </label>
          {["projects", "tasks"].includes(kind) && (
            <label>
              Description
              <textarea
                aria-label="Description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                maxLength={20000}
              />
            </label>
          )}
          {kind === "projects" && (
            <label>
              Project instructions
              <textarea
                aria-label="Project instructions"
                placeholder="How should Aster help with this project?"
                rows={4}
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                maxLength={10000}
              />
            </label>
          )}
          {kind !== "projects" && (
            <ProjectSelect
              value={projectId}
              onChange={setProjectId}
              projects={projects}
              label="Item project"
            />
          )}
          {["notes", "memories"].includes(kind) && (
            <label>
              {kind === "notes"
                ? "Note · Markdown supported"
                : "What should Aster remember?"}
              <textarea
                aria-label={
                  kind === "notes"
                    ? "Note · Markdown supported"
                    : "What should Aster remember?"
                }
                required={kind === "memories"}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={kind === "notes" ? 12 : 4}
                maxLength={kind === "notes" ? 100000 : 4000}
              />
            </label>
          )}
          {kind === "tasks" && (
            <div className="field-row">
              <label>
                Status
                <select
                  aria-label="Status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="todo">To do</option>
                  <option value="in_progress">In progress</option>
                  <option value="done">Done</option>
                </select>
              </label>
              <label>
                Priority
                <select
                  aria-label="Priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                >
                  <option>low</option>
                  <option>medium</option>
                  <option>high</option>
                </select>
              </label>
              <label>
                Due date
                <input
                  aria-label="Due date"
                  type="date"
                  value={due}
                  onChange={(e) => setDue(e.target.value)}
                />
              </label>
            </div>
          )}
          {kind === "memories" && (
            <>
              <label>
                Category
                <select
                  aria-label="Category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="preference">Preference</option>
                  <option value="profile">Profile fact</option>
                  <option value="goal">Goal</option>
                  <option value="project_decision">Project decision</option>
                </select>
              </label>
              <label className="switch-label">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                Enable this memory
              </label>
            </>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <div className="form-actions">
            <Button
              type="button"
              variant="secondary"
              onClick={requestClose}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button disabled={busy || !title.trim()}>
              {busy
                ? "Saving…"
                : "Save " +
                  (kind === "memories" ? "memory" : kind.slice(0, -1))}
            </Button>
          </div>
        </form>
      </Modal>
      <Modal
        open={discarding}
        title="Discard unsaved changes?"
        description="Your edits have not been saved."
        onClose={() => setDiscarding(false)}
      >
        <div className="form-actions">
          <Button variant="secondary" onClick={() => setDiscarding(false)}>
            Keep editing
          </Button>
          <Button variant="destructive" onClick={onClose}>
            Discard changes
          </Button>
        </div>
      </Modal>
    </>
  );
}

function profileValues(user: User) {
  return {
    name: user.name,
    timezone: user.timezone,
    theme: user.theme,
    memory_enabled: user.memory_enabled,
    version: user.version,
  };
}
function SettingsScreen({
  user,
  capabilities,
  report,
  refresh,
  onLogout,
}: {
  user: User;
  capabilities?: Capabilities;
  report: (e: unknown) => void;
  refresh: () => Promise<unknown>;
  onLogout: () => Promise<void>;
}) {
  const [name, setName] = useState(user.name);
  const [timezone, setTimezone] = useState(user.timezone);
  const [appearance, setAppearance] = useState({
    version: user.version,
    value: user.theme,
  });
  const theme =
    appearance.version === user.version ? appearance.value : user.theme;
  const setTheme = async (value: string) => {
    setAppearance({ version: user.version, value });
    setBusy(true);
    try {
      await write("/me", { ...profileValues(user), theme: value }, "PUT");
      localStorage.setItem("nexus-appearance", value);
      await refresh();
    } catch (error) {
      setAppearance({ version: user.version, value: user.theme });
      report(error);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  const [memory, setMemory] = useState(user.memory_enabled);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  return (
    <div className="collection settings-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">MAKE ASTER YOURS</span>
          <h1>Settings</h1>
          <p>A few thoughtful defaults for the way you work.</p>
        </div>
      </div>
      <form
        onChangeCapture={() => setSaved(false)}
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await write(
              "/me",
              {
                name,
                timezone,
                theme,
                memory_enabled: memory,
                version: user.version,
              },
              "PUT",
            );
            await refresh();
            setSaved(true);
          } catch (err) {
            report(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <section className="settings-section">
          <div>
            <h2>Your profile</h2>
            <p className="muted">Local account · {user.email}</p>
          </div>
          <label>
            Name
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Timezone
            <input
              required
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="Asia/Karachi"
            />
          </label>
          <small className="muted">
            Relative dates use this timezone. Task due dates are local calendar
            dates.
          </small>
          <label>
            Appearance
            <select
              aria-label="Appearance"
              value={theme}
              disabled={busy}
              onChange={(e) => void setTheme(e.target.value)}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="system">System (follow device)</option>
            </select>
          </label>
        </section>
        <section className="settings-section">
          <h2>Personal memory</h2>
          <label className="switch-label">
            <input
              type="checkbox"
              checked={memory}
              onChange={(e) => setMemory(e.target.checked)}
            />
            Allow Aster to read and propose saved memories
          </label>
          <p className="muted">
            Assistant memory writes always need your approval. Turning this off
            stops reads and writes; it preserves your conversations and saved
            memories.
          </p>
          <Link className="text-link" href="/memories">
            Manage saved memories ↗
          </Link>
        </section>
        <Button disabled={busy}>{busy ? "Saving…" : "Save preferences"}</Button>
        {saved && (
          <span className="saved-message" role="status">
            Preferences saved
          </span>
        )}
      </form>
      <section className="settings-section">
        <h2>Your data</h2>
        <p className="muted">
          Messages, relevant saved memories and retrieved workspace content are
          sent to{" "}
          {capabilities?.models.chat?.startsWith("gemini")
            ? "Gemini"
            : "your configured AI provider"}{" "}
          when you use the assistant. Extracted document text is sent there to
          create its search index.
        </p>
        <p className="muted">
          Web search queries are sent to{" "}
          {capabilities?.models.search?.includes("Tavily")
            ? "Tavily"
            : capabilities?.models.search?.includes("DuckDuckGo")
              ? "DuckDuckGo"
              : "your configured search provider"}
          . Your saved workspace and original files are stored on your Aster
          server.
        </p>
      </section>
      <section className="settings-section capabilities">
        <h2>Connections & capabilities</h2>
        <p className="muted">
          {capabilities?.connection || "Checking connection…"}
        </p>
        {capabilities?.reason && (
          <div className="alert">{capabilities.reason}</div>
        )}
        {Object.entries(capabilities?.models || {}).map(([name, model]) => (
          <div key={name}>
            <span>{name}</span>
            <code>{model}</code>
            <span className="tag">
              {capabilities?.chat ? "Configured" : "Unavailable"}
            </span>
          </div>
        ))}
        <p className="muted">
          The API key is kept in the server’s .env file. Model availability and
          web-search access depend on your provider account.
        </p>
      </section>
      <Button variant="secondary" onClick={onLogout}>
        <LogOut size={16} />
        Sign out
      </Button>
    </div>
  );
}

function MemoryToggle({
  item,
  report,
}: {
  item: Resource;
  report: (e: unknown) => void;
}) {
  const client = useQueryClient();
  const [optimistic, setOptimistic] = useState<boolean | null>(null);
  const mutation = useMutation({
    mutationFn: (enabled: boolean) =>
      write(
        "/memories/" + item.id,
        {
          title: item.title,
          content: item.content,
          category: item.category,
          enabled,
          project_id: item.project_id,
          version: item.version,
        },
        "PUT",
      ),
    onMutate: (enabled: boolean) => {
      client.setQueriesData<Resource[]>({ queryKey: ["memories"] }, (old) =>
        old?.map((m) => (m.id === item.id ? { ...m, enabled } : m)),
      );
    },
    onError: report,
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: ["memories"] });
      setOptimistic(null);
    },
  });
  return (
    <label className="switch-label">
      <input
        type="checkbox"
        checked={optimistic ?? !!item.enabled}
        disabled={mutation.isPending}
        aria-label={"Enable " + item.title}
        onChange={(e) => {
          setOptimistic(e.target.checked);
          mutation.mutate(e.target.checked);
        }}
      />
      {item.enabled ? "Enabled" : "Disabled"}
    </label>
  );
}
