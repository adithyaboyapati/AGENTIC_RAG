-- Supabase schema for Agentic RAG chat memory
-- Run this in Supabase SQL Editor: https://supabase.com/dashboard/project/_/sql

create table if not exists chat_messages (
  id uuid primary key default gen_random_uuid(),
  session_id text not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  mode text default '',
  created_at timestamptz not null default now()
);

create index if not exists idx_chat_messages_session
  on chat_messages (session_id, created_at);

-- Optional: enable Row Level Security (recommended for production)
-- alter table chat_messages enable row level security;
-- create policy "Allow service role full access" on chat_messages
--   for all using (true) with check (true);
