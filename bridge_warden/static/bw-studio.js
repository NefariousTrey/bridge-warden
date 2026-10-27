/* Bridge Warden v6: the BW AG Grid agent chat panel, built on AG Studio's Agent Framework.
   Made by @Nefarious_Trey, with Grok. Copyright 2026 Douglas Gibbons III. Apache-2.0 (this file only).
   AG Studio itself is commercial software by AG Grid Ltd; it is NOT part of this repo (scripts/fetch_ag_studio.sh).
   - The model is xAI, reached ONLY through Bridge Warden's own server (/ag-studio/v1/responses). No xAI key here.
   - Data is redacted (groups, months, amounts, flag kinds). No merchant names, emails or ids.
   - Our tools are read-only. bw_show_issue only scrolls to the owner's button; it never clicks it.
     Nothing in this file can approve, ignore, acknowledge, turn green, release a hold or move money. */
(function () {
  'use strict';
  var box = document.getElementById('bw-studio');
  var S = window.agStudio;
  if (!box || !S || !S.createStudio) { return; }
  var note = document.getElementById('bw-studio-usage');
  // This file runs inside the panel's own frame (/ag-studio/panel). History is the parent page (same site).
  var page = document;
  try { if (window.parent && window.parent !== window && window.parent.document) { page = window.parent.document; } } catch (e) { page = document; }
  function j(url) {
    return fetch(url, {credentials: 'same-origin', cache: 'no-store'}).then(function (r) { return r.ok ? r.json() : null; });
  }
  function text(parts) {
    return (parts || []).map(function (c) { return c && typeof c.text === 'string' ? c.text : ''; }).join('');
  }
  // ---- AG conversation items -> Responses API input (our own small encoder)
  function encode(items) {
    var out = [];
    (items || []).forEach(function (it) {
      if (it.type === 'message') {
        out.push({role: it.kind === 'output' ? 'assistant' : (it.role === 'system' ? 'system' : 'user'),
                  content: text(it.content)});
      } else if (it.type === 'function_call') {
        out.push({type: 'function_call', call_id: it.callId, name: it.name, arguments: it.arguments || '{}'});
      } else if (it.type === 'function_call_output') {
        out.push({type: 'function_call_output', call_id: it.callId,
                  output: typeof it.output === 'string' ? it.output : JSON.stringify(it.output)});
      }   // reasoning items are not replayed
    });
    return out;
  }
  function decode(r, usageLine) {
    var output = [];
    (r.output || []).forEach(function (o) {
      if (o.type === 'message') {
        output.push({id: o.id || '', kind: 'output', type: 'message', role: 'assistant', status: o.status || 'completed',
                     content: [{type: 'text', text: text(o.content) + (usageLine ? '\n\n' + usageLine : ''), annotations: []}]});
        usageLine = '';
      } else if (o.type === 'function_call') {
        output.push({id: o.id || '', kind: 'output', type: 'function_call', callId: o.call_id, name: o.name,
                     arguments: o.arguments || '{}', status: o.status || 'completed'});
      }
    });
    var u = r.usage || {};
    return {id: r.id || ('bw-' + Date.now()), createdAt: r.created_at || Math.floor(Date.now() / 1000), model: r.model,
            output: output, status: 'completed',
            usage: {inputTokens: u.input_tokens || 0, outputTokens: u.output_tokens || 0, totalTokens: u.total_tokens || 0}};
  }
  function events(resp) {
    var ev = [];
    resp.output.forEach(function (o, i) {
      if (o.type === 'message') {
        var id = o.id || ('m' + i);
        ev.push({type: 'TEXT_MESSAGE_START', messageId: id, role: 'assistant'});
        ev.push({type: 'TEXT_MESSAGE_CONTENT', messageId: id, delta: o.content[0].text});
        ev.push({type: 'TEXT_MESSAGE_END', messageId: id});
      } else {
        ev.push({type: 'TOOL_CALL_START', toolCallId: o.callId, toolCallName: o.name});
        ev.push({type: 'TOOL_CALL_ARGS', toolCallId: o.callId, delta: o.arguments});
        ev.push({type: 'TOOL_CALL_END', toolCallId: o.callId});
      }
    });
    return ev;
  }
  // Non-streaming adapter: one POST to our own server per turn, then the events are replayed.
  var adapter = {
    executeTurn: function (request, opts) {
      var signal = opts && opts.signal;
      var p = fetch('/ag-studio/v1/responses', {
        method: 'POST', credentials: 'same-origin', signal: signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          input: encode(request.input), instructions: request.instructions || '',
          tools: (request.tools || []).map(function (t) {
            return {type: 'function', name: t.name, description: t.description, parameters: t.parameters};
          }),
          tool_choice: !request.toolChoice ? undefined :
            (typeof request.toolChoice === 'string' ? request.toolChoice : {type: 'function', name: request.toolChoice.name}),
          parallel_tool_calls: false
        })
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          if (r.ok) {
            if (note && b.bw_usage) { note.textContent = b.bw_usage; }
            return decode(b, b.bw_usage);
          }
          // Not sent to xAI (no key, ZDR, budget, size): say so honestly, no cost.
          var msg = (b.error && b.error.message) || ('HTTP ' + r.status);
          var line = 'No AI call, no cost.';
          if (note) { note.textContent = line; }
          return decode({output: [{type: 'message', content: [{text: msg}]}]}, line);
        });
      });
      var stream = (async function* () { var resp = await p; for (var e of events(resp)) { yield e; } })();
      return {stream: stream, complete: p};
    }
  };
  function tools(api, data) {
    var t = [];
    t.push(api.defineAiTool({
      name: 'bw_spending_categories',
      description: 'Read-only. Totals for bills, subscriptions, gas, food and other, by month, plus refunds and failed payments.',
      params: function (s) { return s.object({}); },
      execute: async function (_a, ctx) { return ctx.success('Spending by group.', data.summary); }
    }));
    t.push(api.defineAiTool({
      name: 'bw_subscriptions',
      description: 'Read-only. How many subscriptions look paid twice (duplicate), maybe unused (still_use) or went up in price (price_up).',
      params: function (s) { return s.object({}); },
      execute: async function (_a, ctx) { return ctx.success('Subscription checks.', data.subscriptions); }
    }));
    t.push(api.defineAiTool({
      name: 'bw_audit_flags',
      description: 'Read-only. Money flags by kind, and the BW AG Grid agent issues with their status (red, yellow, fixed, ignored).',
      params: function (s) { return s.object({}); },
      execute: async function (_a, ctx) {
        return ctx.success('Audit flags.', {flag_counts: data.summary.flag_counts, issues: data.issues});
      }
    }));
    t.push(api.defineAiTool({
      name: 'bw_show_issue',
      description: 'Scroll the page to one issue and put focus on the OWNER\'s button for it. It does NOT click. Only the owner can see, fix or ignore an issue.',
      params: function (s) { return s.object({issue_id: s.string({description: 'Issue id from bw_audit_flags.'})}); },
      execute: async function (a, ctx) {
        var id = String(a.issue_id || '').replace(/[^A-Za-z0-9_-]/g, '');
        var el = id && page.getElementById('issue-' + id);
        if (!el) { return ctx.error('No open issue with that id.'); }
        el.scrollIntoView({block: 'center'});
        var b = el.querySelector('button:not([disabled])');
        if (b) { b.focus(); }
        return ctx.success('Showed it. Only the owner can click the button. I cannot.', {issue_id: id});
      }
    }));
    return t;
  }
  Promise.all([j('/ag-studio/config.json'), j('/ag-studio/data.json')]).then(function (res) {
    var cfg = res[0], data = res[1];
    if (!cfg || !data) { return; }
    if (cfg.license_key && S.AgStudioLicenseManager) { S.AgStudioLicenseManager.setLicenseKey(cfg.license_key); }
    if (S.AgStudioModuleRegistry && S.AgStudioAiModule) { S.AgStudioModuleRegistry.registerModules([S.AgStudioAiModule]); }
    var dark = page.documentElement.getAttribute('data-theme') === 'dark';
    var props = {
      mode: 'edit',
      data: {sources: [{id: 'spending', data: data.rows}]},
      initialState: {
        pages: [{
          id: 'main', name: 'Where my money goes',
          widgets: {
            'by-group': {type: 'column-chart-grouped',
              dataMapping: {categoryKey: [{id: 'spending.group'}], valueKey: [{id: 'spending.amount', aggregation: 'sum'}]},
              format: {caption: {enabled: true, text: 'Spending by group' + (data.sample ? ' (SAMPLE)' : '')}}},
            'lines': {type: 'grid',
              dataMapping: {cols: [{id: 'spending.month'}, {id: 'spending.group'}, {id: 'spending.kind'},
                                   {id: 'spending.amount', aggregation: 'sum'}, {id: 'spending.flag'}]},
              format: {caption: {enabled: true, text: 'By month and group'}}}
          },
          widgetLayout: {'by-group': {xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 14},
                         'lines': {xTrack: 0, yTrack: 14, xSpan: 24, ySpan: 16}}
        }],
        selectedPageId: 'main',
        panels: {ai: {collapsed: false}}
      },
      ai: function (o) {
        var api = o.api, mine = tools(api, data);
        return S.createAiHarness(api, function (b) {
          return {
            agents: Object.keys(b.builtIn).map(function (k) {
              var d = b.builtIn[k];
              var extra = d.id === 'lead' || k === 'lead';
              return S.directLlmRunner(Object.assign({}, d, {adapter: adapter,
                tools: extra ? function () { return d.tools.apply(null, arguments).concat(mine); } : d.tools}));
            }),
            primary: 'lead',
            promptStarters: [
              {label: 'Where does my money go?', prompt: 'Using bw_spending_categories, which group costs me the most this month? 2 sentences.'},
              {label: 'Duplicate subscriptions?', prompt: 'Using bw_subscriptions, do I pay for any subscription twice or not use one?'},
              {label: 'What needs me?', prompt: 'Using bw_audit_flags, list open issues and show me the first one with bw_show_issue.'}
            ]
          };
        });
      }
    };
    if (S.studioTheme) {
      props.theme = S.studioTheme.withParams(dark ? {accentColor: '#22D3EE', backgroundColor: '#1A2333', foregroundColor: '#E5E7EB', browserColorScheme: 'dark'}
                                                  : {accentColor: '#0E7490', backgroundColor: '#FFFFFF', foregroundColor: '#0B1220', browserColorScheme: 'light'});
    }
    box.hidden = false;
    S.createStudio(box, props);
  }).catch(function () { /* keep Bridge Warden's own History chat */ });
})();
