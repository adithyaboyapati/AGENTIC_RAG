-- Supabase schema for Agentic RAG chat memory.
-- Run in the Supabase SQL Editor: https://supabase.com/dashboard/project/_/sql
--
-- This table holds user-authored conversation content. RLS is enabled and the
-- default is deny: the API connects with the service role, which bypasses RLS,
-- so nothing else (anon key, a leaked client token) can read other people's
-- chats.

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

-- Supports the retention sweep below.
create index if not exists idx_chat_messages_created_at
  on chat_messages (created_at);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
-- Enabling RLS with no permissive policy denies every request that is not made
-- with the service role. That is the intended posture: the API is the only
-- writer, and it authenticates its own users before touching a session.
alter table chat_messages enable row level security;

-- Explicitly revoke the browser-facing roles so an exposed anon key cannot
-- enumerate sessions even if a policy is added carelessly later.
revoke all on chat_messages from anon, authenticated;

-- If you later let clients talk to Supabase directly, scope access to the
-- caller's own rows rather than re-opening the table:
--
--   alter table chat_messages add column user_id uuid
--     references auth.users (id) on delete cascade;
--
--   create policy "own rows" on chat_messages
--     for all to authenticated
--     using (user_id = auth.uid())
--     with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Retention
-- ---------------------------------------------------------------------------
-- PRIVACY_RETENTION_DAYS documents the intent; this enforces it. Without a
-- sweep, "30 day retention" is a constant in a config file, not a fact.
create or replace function purge_expired_chat_messages(retention_days int default 30)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted bigint;
begin
  delete from chat_messages
   where created_at < now() - make_interval(days => retention_days);
  get diagnostics deleted = row_count;
  return deleted;
end;
$$;

-- Schedule it daily (requires the pg_cron extension):
--   create extension if not exists pg_cron;
--   select cron.schedule(
--     'purge-chat-messages',
--     '0 4 * * *',
--     $$select purge_expired_chat_messages(30)$$
--   );
--
-- Or call it from your own scheduler:
--   select purge_expired_chat_messages(30);

-- ---------------------------------------------------------------------------
-- GDPR / CCPA erasure
-- ---------------------------------------------------------------------------
create or replace function delete_chat_session(target_session_id text)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted bigint;
begin
  delete from chat_messages where session_id = target_session_id;
  get diagnostics deleted = row_count;
  return deleted;
end;
$$;
