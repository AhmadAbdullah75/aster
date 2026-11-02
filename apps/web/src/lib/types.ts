export type Resource = {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
  title: string;
  description?: string;
  instructions?: string;
  content?: string;
  project_id?: string | null;
  status?: string;
  priority?: string;
  due_date?: string | null;
  enabled?: boolean;
  category?: string;
  archived?: boolean;
  provenance?: string;
};
export type User = {
  id: string;
  version: number;
  name: string;
  email: string;
  timezone: string;
  theme: string;
  memory_enabled: boolean;
};
export type Capabilities = {
  chat: boolean;
  web: boolean;
  embeddings: boolean;
  reason: string | null;
  connection: string;
  models: { chat: string; search: string; embedding: string };
  upload_limit_mib: number;
};
export type Source = {
  type?: string;
  html?: string;
  id?: string;
  document_id?: string;
  filename?: string;
  page?: number | null;
  section?: string;
  excerpt?: string;
  url?: string;
  title?: string;
  media_type?: string;
};
export type Message = {
  id: string;
  run_id: string;
  role: string;
  content: string;
  interrupted: boolean;
  sources: Source[];
  created_at: string;
};
export type Run = {
  id: string;
  status: string;
  error?: string;
  created_at: string;
  conversation_id: string;
  input?: { mode?: string; document_ids?: string[] };
};
export type ActionItem = {
  id: string;
  version?: number;
  include: boolean;
  title?: string;
  description?: string;
  content?: string;
  due_date?: string | null;
  status?: string;
  priority?: string;
  category?: string;
  project_id?: string | null;
  enabled?: boolean;
};
export type Proposal = {
  decision?: { approve: boolean; payload: { items: ActionItem[] } };
  id: string;
  run_id: string;
  version: number;
  action: string;
  status: string;
  payload: { items: ActionItem[] };
  outcome?: { status: string; saved: unknown[] };
  expires_at: string;
};
export type History = {
  messages: Message[];
  runs: Run[];
  proposals: Proposal[];
};
export type Document = Resource & {
  filename: string;
  size: number;
  media_type: string;
  error?: string;
  embedding_model?: string;
};
export type Event = {
  id: number;
  seq: number;
  run_id: string;
  thread_id: string;
  type: string;
  payload: {
    text?: string;
    error?: string;
    name?: string;
    items?: { id: string; title: string }[];
  };
};
