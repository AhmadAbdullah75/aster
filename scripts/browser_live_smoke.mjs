// Explicit live-provider browser smoke against the running production app. Synthetic data only.
import { chromium } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const email = `nexus-smoke-${Date.now()}@example.com`;
const errors = []; page.on('pageerror', e => errors.push(e.message));
let project, user, thread;
const started = Date.now();
async function request(url, body, method = 'POST') {
  const result = await page.request.fetch('http://127.0.0.1:3000/api' + url, { method, data: body, headers: { origin: 'http://127.0.0.1:3000' } });
  if (!result.ok()) throw new Error('API failed: ' + url + ' ' + result.status());
  return result.json();
}
async function until(check, timeout = 150000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await check()) return; await new Promise(r => setTimeout(r, 750)); } throw new Error('Live browser check timed out'); }
try {
  await page.goto('http://127.0.0.1:3000');
  await page.getByRole('button', { name: 'Create an account', exact: true }).click();
  await page.getByLabel('Your name').fill('Synthetic Live'); await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill('synthetic-live-password'); await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await page.getByRole('heading', { name: /What’s on your mind/ }).waitFor();
  user = await request('/me', undefined, 'GET');
  project = await request('/projects', { title: 'Synthetic live validation', instructions: 'Use concise simple English and source citations. Do not create tasks until approved.' });
  await page.reload(); // API fixture creation does not invalidate the browser query cache.
  await page.getByRole('link', { name: 'Documents', exact: true }).click();
  await page.getByLabel('Filter project').selectOption(project.id);
  await page.locator('input[type=file]').setInputFiles(path.resolve('docs/example-proposal.md'));
  await until(async () => { const docs = await request('/documents?project_id=' + project.id, undefined, 'GET'); if (docs.some(d => d.status === 'failed')) throw new Error(docs.find(d => d.status === 'failed').error); return docs.some(d => d.status === 'ready'); });
  thread = await request('/conversations', { project_id: project.id });
  await page.goto('http://127.0.0.1:3000/chat/' + thread.id);
  await page.getByLabel('Assistant mode').selectOption('documents');
  await page.getByLabel('Message Aster').fill('Briefly explain this proposal with source citations, then propose exactly two concrete tasks for the next two weeks. Use current_datetime for relative dates. Wait for my approval before saving.');
  await page.getByLabel('Send message').click();
  await until(async () => { const h = await request('/conversations/' + thread.id + '/history', undefined, 'GET'); const last = h.runs.at(-1); if (last?.status === 'failed') throw new Error(last.error); return h.proposals.some(p => p.status === 'pending'); });
  await page.reload();
  await page.getByRole('button', { name: 'Approve selection', exact: true }).waitFor();
  const tasksBefore = await request('/tasks?project_id=' + project.id, undefined, 'GET');
  if (tasksBefore.length) throw new Error('Unexpected unapproved task');
  await page.getByRole('button', { name: 'Source ↗', exact: true }).first().click();
  await page.getByRole('dialog').waitFor(); await page.getByLabel('Close dialog').click();
  await page.getByRole('button', { name: 'Edit proposal', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).first().fill('Edited live smoke milestone');
  await page.getByLabel('Include proposed item 2').uncheck();
  await page.getByRole('button', { name: 'Approve edited selection', exact: true }).click();
  await until(async () => { const h = await request('/conversations/' + thread.id + '/history', undefined, 'GET'); const last = h.runs.at(-1); if (last?.status === 'failed') throw new Error(last.error); return last?.status === 'completed'; });
  const tasks = await request('/tasks?project_id=' + project.id, undefined, 'GET');
  if (tasks.length !== 1 || tasks[0].title !== 'Edited live smoke milestone') throw new Error('Edited approval outcome mismatch');
  await page.reload(); await page.getByText('Approved changes have been saved.').waitFor();
  await page.screenshot({ path: 'artifacts/live-browser.png', fullPage: true });
  await page.goto('http://127.0.0.1:3000/chat');
  await page.getByRole('heading', {name:/What’s on your mind/}).waitFor();
  await page.getByText('AI configured', {exact:true}).waitFor();
  await page.screenshot({ path: 'artifacts/audit-production-workspace.png', fullPage: true, animations: 'disabled' });
  if (errors.length) throw new Error(errors.join('; '));
  fs.writeFileSync('artifacts/live-browser.json', JSON.stringify({ status: 'passed', elapsed_seconds: (Date.now() - started) / 1000, checks: ['registration', 'real ingestion', 'grounded answer and citation', 'pending reload', 'edit/exclude approval', 'one task saved', 'completed reload', 'no page errors'] }, null, 2));
  console.log('Production live browser flow passed: ingestion, grounded answer, pending reload, edited approval and exactly-once save.');
} catch (error) {
  if (thread) fs.writeFileSync('artifacts/live-browser-failure.json', JSON.stringify(await request('/conversations/' + thread.id + '/history', undefined, 'GET'), null, 2));
  await page.screenshot({path:'artifacts/live-browser-failure.png',fullPage:true});
  throw error;
} finally {
  if (project) await request('/projects/' + project.id + '?version=' + project.version, undefined, 'DELETE');
  await browser.close();
  if (user) execFileSync(path.resolve('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'), ['scripts/cleanup_smoke.py', user.id, email]);
}
