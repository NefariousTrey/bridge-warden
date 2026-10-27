// v6: tests for bridge_warden/static/bw-studio.js (the BW AG Grid agent chat glue). Fakes only, no network.
// Made by @Nefarious_Trey, with Grok. Copyright 2026 Douglas Gibbons III. Apache-2.0.
// Run: node tests/node/test_bw_studio.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const SRC = fs.readFileSync(new URL("../../bridge_warden/static/bw-studio.js", import.meta.url), "utf8");
let pass = 0;
const t = async (name, fn) => { await fn(); pass++; console.log("ok -", name); };

function harness({ok = true, status = 200, body} = {}) {
  const calls = [], captured = {}, focused = [], clicked = [];
  const issueBtn = {disabled: false, focus() { focused.push("btn"); }, click() { clicked.push("btn"); }};
  const doc = {
    documentElement: {getAttribute: () => "light"},
    getElementById(id) {
      if (id === "bw-studio") return captured.box = {hidden: true};
      if (id === "bw-studio-usage") return captured.note = {textContent: ""};
      if (id === "issue-abc123") return {scrollIntoView() {}, querySelector: () => issueBtn};
      return null;
    },
  };
  const data = {rows: [{month: "2026-10", group: "food", kind: "payment", amount: 12, flag: ""}],
                summary: {flag_counts: {duplicate: 1}}, subscriptions: {duplicate: 1}, issues: [], sample: true};
  const fetch = async (url, opts = {}) => {
    calls.push({url, opts});
    if (url === "/ag-studio/config.json") return {ok: true, json: async () => ({license_key: "", ai_ready: true})};
    if (url === "/ag-studio/data.json") return {ok: true, json: async () => data};
    return {ok, status, json: async () => body};
  };
  const S = {
    createStudio(el, props) { captured.props = props; },
    createAiHarness(api, f) {
      const lead = {id: "lead", tools: () => ["builtin"]}, data2 = {id: "data", tools: () => ["b2"]};
      captured.h = f({builtIn: {lead, data: data2}, tools: {studio: {}}});
      return captured.h;
    },
    directLlmRunner(def) { return def; },
    AgStudioModuleRegistry: {registerModules(m) { captured.mods = m; }}, AgStudioAiModule: {},
    AgStudioLicenseManager: {setLicenseKey(k) { captured.key = k; }},
  };
  const ctx = {window: {agStudio: S}, document: doc, fetch, JSON, Promise, Date, Math, String, Object, console};
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return {calls, captured, focused, clicked, S, data};
}
const tick = () => new Promise((r) => setTimeout(r, 10));
const api = {defineAiTool: (d) => d};
async function adapterOf(h) {
  await tick();
  const harn = h.captured.props.ai({api});
  return {adapter: harn.agents[0].adapter, harn};
}
async function drain(stream) { const out = []; for await (const e of stream) out.push(e); return out; }

await t("builds Studio with redacted data, AI module, spending chart, no licence key when none", async () => {
  const h = harness();
  await tick();
  assert.equal(h.captured.box.hidden, false);
  assert.equal(h.captured.props.data.sources[0].id, "spending");
  assert.equal(h.captured.props.initialState.pages[0].widgets["by-group"].type, "column-chart-grouped");
  assert.ok(h.captured.mods && h.captured.key === undefined);
});

await t("the lead agent gets the 4 read-only BW tools; others keep only built-ins", async () => {
  const h = harness();
  const {harn} = await adapterOf(h);
  const lead = harn.agents.find((a) => a.id === "lead"), other = harn.agents.find((a) => a.id === "data");
  const names = lead.tools().filter((x) => x.name).map((x) => x.name);
  assert.deepEqual(names, ["bw_spending_categories", "bw_subscriptions", "bw_audit_flags", "bw_show_issue"]);
  assert.deepEqual(other.tools(), ["b2"]);
  assert.equal(harn.promptStarters.length, 3);
});

await t("adapter posts only to BW's own server, no key, function tools only, and shows real usage", async () => {
  const h = harness({body: {id: "r", output: [{type: "message", content: [{type: "output_text", text: "Food is top."}]},
                                             {type: "function_call", call_id: "c1", name: "bw_subscriptions", arguments: "{}"}],
                            usage: {input_tokens: 9, output_tokens: 3}, bw_usage: "This answer used 9 in + 3 out tokens."}});
  const {adapter} = await adapterOf(h);
  const r = adapter.executeTurn({input: [{type: "message", role: "user", content: [{type: "text", text: "hi"}]}],
                                 tools: [{name: "bw_subscriptions", description: "d", parameters: {}}]}, {});
  const ev = await drain(r.stream);
  const resp = await r.complete;
  const post = h.calls.find((c) => c.url === "/ag-studio/v1/responses");
  assert.ok(post && post.opts.method === "POST" && post.opts.credentials === "same-origin");
  assert.ok(!JSON.stringify(post.opts.headers).toLowerCase().includes("authorization"));
  const sent = JSON.parse(post.opts.body);
  assert.ok(sent.tools.every((x) => x.type === "function"));
  assert.equal(sent.input[0].content, "hi");
  assert.ok(resp.output[0].content[0].text.endsWith("This answer used 9 in + 3 out tokens."));
  assert.equal(resp.output[1].callId, "c1");
  assert.deepEqual(ev.map((e) => e.type), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
                                           "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]);
  assert.equal(h.captured.note.textContent, "This answer used 9 in + 3 out tokens.");
  assert.equal(resp.usage.inputTokens, 9);
});

await t("when BW refuses (no key), the panel says so and 'No AI call, no cost.'", async () => {
  const h = harness({ok: false, status: 503, body: {error: {message: "AI not used: no xAI key set."}}});
  const {adapter} = await adapterOf(h);
  const r = adapter.executeTurn({input: []}, {});
  await drain(r.stream);
  const resp = await r.complete;
  assert.match(resp.output[0].content[0].text, /AI not used: no xAI key set\.\n\nNo AI call, no cost\./);
  assert.equal(h.captured.note.textContent, "No AI call, no cost.");
});

await t("bw_show_issue only focuses the owner's button; it never clicks", async () => {
  const h = harness();
  const {harn} = await adapterOf(h);
  const show = harn.agents[0].tools().find((x) => x.name === "bw_show_issue");
  const ctx = {success: (m, d) => ({ok: true, m, d}), error: (m) => ({ok: false, m})};
  const r = await show.execute({issue_id: "abc123"}, ctx);
  assert.ok(r.ok && /I cannot/.test(r.m));
  assert.deepEqual(h.focused, ["btn"]);
  assert.deepEqual(h.clicked, []);
  assert.equal((await show.execute({issue_id: "x\"><script>"}, ctx)).ok, false);
});

await t("the glue has no money / approve path at all", async () => {
  for (const bad of ["/act", "/decide", ".click(", "submit(", "name=\"token\"", "nonce", "api.x.ai", "Authorization"]) {
    assert.ok(!SRC.includes(bad), bad);
  }
});
console.log(`${pass} passed`);
