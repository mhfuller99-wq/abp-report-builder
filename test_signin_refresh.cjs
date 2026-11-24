const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/abp_server.py', 'utf8');
const html = source.split("LOGIN_HTML='''")[1].split("'''")[0];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('{{RENEW_AFTER_MS}}', '3540000');

function page(age, fetch) {
  const issued = Math.floor((Date.now() - age) / 1000);
  const token = {value: issued + '.signed-form-value'};
  const button = {disabled: false};
  const status = {textContent: ''};
  const handlers = {};
  const actions = {posts: 0, redirects: []};
  const form = {
    elements: {namedItem(name) { assert.equal(name, 'csrf'); return token; }},
    querySelector(selector) { assert.equal(selector, 'button'); return button; },
    addEventListener(type, action) { handlers[type] = action; },
    reportValidity() { return true; },
    submit() { actions.posts++; },
  };
  class DOMParser {
    parseFromString(text) {
      assert.equal(text, 'fresh HTML');
      return {querySelector(selector) {
        assert.equal(selector, 'form[action="/login"] input[name="csrf"]');
        return {value: 'fresh-signed-form-value'};
      }};
    }
  }
  vm.runInNewContext(script, {
    document: {querySelector: () => form, getElementById: () => status},
    window: {addEventListener(type, fn) { handlers[type] = fn; }},
    location: {assign(path) { actions.redirects.push(path); }},
    Date, URL, AbortController, setTimeout, clearTimeout, DOMParser, fetch
  });
  async function submit() {
    let stopped = false;
    await handlers.submit({preventDefault() { stopped = true; }});
    return stopped;
  }
  return {submit, token, button, status, actions, handlers};
}

(async () => {
  const fresh = page(60000, () => assert.fail('A fresh form should submit normally'));
  assert.equal(await fresh.submit(), false);
  let resolveResponse, gets = 0;
  const overnight = page(24 * 3600000, (path, options) => {
    gets++;
    assert.equal(path, '/login');
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.body, undefined);
    assert.equal(options.method ?? 'GET', 'GET');
    return new Promise(resolve => { resolveResponse = resolve; });
  });
  const first = overnight.submit();
  assert.equal(overnight.button.disabled, true);
  assert.equal(await overnight.submit(), true);
  resolveResponse({ok: true, redirected: false, text: async () => 'fresh HTML'});
  assert.equal(await first, true);
  assert.equal(overnight.token.value, 'fresh-signed-form-value');
  assert.equal(overnight.actions.posts, 1);
  assert.equal(gets, 1);
  overnight.handlers.pageshow();
  assert.equal(overnight.button.disabled, false);

  const offline = page(7200000, async () => { throw Error('offline'); });
  assert.equal(await offline.submit(), true);
  assert.match(offline.status.textContent, /could not refresh/);
  assert.equal(offline.button.disabled, false);
  assert.equal(offline.actions.posts, 0);
  const signedIn = page(7200000, async () => ({ok: true, redirected: true, url: 'https://example.invalid/'}));
  await signedIn.submit();
  assert.deepEqual(signedIn.actions.redirects, ['/']);
  assert.equal(signedIn.actions.posts, 0);
  console.log('Fresh, overnight, double-submit, network failure, and already-signed-in form behavior passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
