-- Applied to Supabase as migration "daily_6am_post_trigger" (2026-09-30). Kept here for reference/re-creation.
-- Starts the GitHub "Daily posts" workflow (publish.yml) at ~5:55 and ~6:25 AM Los Angeles time every day.
-- GitHub's own cron runs hours late on this repo; a workflow_dispatch starts within seconds.
-- Needs a Vault secret named 'github_dispatch_token': a fine-grained GitHub token for this repo only with
-- "Actions: Read and write" (Supabase → Project Settings → Vault, or: select vault.create_secret('<token>',
-- 'github_dispatch_token'); run it in the SQL editor, never commit the token).
create extension if not exists pg_cron;
create extension if not exists pg_net;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.dispatch_daily_posts()
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  la_time time := (now() at time zone 'America/Los_Angeles')::time;
  token text;
  req_id bigint;
begin
  if la_time < time '05:50' or la_time > time '06:40' then
    return null;
  end if;
  select decrypted_secret into token from vault.decrypted_secrets where name = 'github_dispatch_token' limit 1;
  if token is null or btrim(token) = '' then
    raise warning 'dispatch_daily_posts: Vault secret github_dispatch_token is missing';
    return null;
  end if;
  select net.http_post(
    url := 'https://api.github.com/repos/ChaseLGrant/The-Athlete-Market-Telegram-Agent-for-Roster-Updates/actions/workflows/publish.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || btrim(token),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'tam-roster-intel-cron',
      'Content-Type', 'application/json'),
    body := jsonb_build_object('ref', 'claude/wizardly-knuth-ls4oxl')
  ) into req_id;
  return req_id;
end;
$$;
revoke all on function private.dispatch_daily_posts() from public, anon, authenticated;

-- UTC times; the function only acts at ~5:55 / ~6:25 AM Los Angeles (PDT: a+b, PST: c+d).
select cron.schedule('tam-daily-posts-a', '55 12 * * *', 'select private.dispatch_daily_posts()');
select cron.schedule('tam-daily-posts-b', '25 13 * * *', 'select private.dispatch_daily_posts()');
select cron.schedule('tam-daily-posts-c', '55 13 * * *', 'select private.dispatch_daily_posts()');
select cron.schedule('tam-daily-posts-d', '25 14 * * *', 'select private.dispatch_daily_posts()');

-- Check: select * from net._http_response order by created desc limit 5;  (status_code 204 = workflow started)
