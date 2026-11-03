/* Bridge Warden v3 (Light/Dark theme, Oct 26 2026): Guard History grid (every buy, payment and refund the Warden checked) with Market price, Difference % and Risk ring (AG Grid Community, MIT,
   self-hosted). Made by @Nefarious_Trey, with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
   Progressive enhancement: if this file or AG Grid does not load, the plain table stays. No outside calls.
   Market prices are EXAMPLE demo prices unless the owner turns on a real source. They only warn. */
(function () {
  var box = document.getElementById('bw-grid');
  var plain = document.getElementById('bw-plain');
  var tog = document.getElementById('bw-grid-toggle');
  if (!box || !plain || !tog || !window.agGrid) { return; }
  var RANK = {red: 2, yellow: 1, green: 0};
  function safeDot(u) { return typeof u === 'string' && u.indexOf('/assets/dots/') === 0 ? u : ''; }
  function safeLink(u) { return typeof u === 'string' && u.indexOf('/history/move?id=') === 0 ? u : ''; }
  fetch('/moves.json', {credentials: 'same-origin', cache: 'no-store'}).then(function (r) {
    return r.ok ? r.json() : null;
  }).then(function (d) {
    if (!d || !d.rows || !d.rows.length) { return; }
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';   // set by the server, no flash
    var theme = agGrid.themeQuartz.withParams(dark ? {
      fontFamily: 'inherit', fontSize: 16, headerFontSize: 15, headerFontWeight: 700,
      foregroundColor: '#E5E7EB', textColor: '#E5E7EB', backgroundColor: '#1A2333',
      headerBackgroundColor: '#243042', headerTextColor: '#F3F4F6', accentColor: '#22D3EE',
      borderColor: '#334155', rowBorder: {color: '#334155'}, oddRowBackgroundColor: '#1E293B',
      rowHoverColor: '#0B2A33', selectedRowBackgroundColor: '#0B2A33', spacing: 8,
      wrapperBorderRadius: 12, browserColorScheme: 'dark', focusShadow: {radius: 3, color: '#93C5FD'}
    } : {
      fontFamily: 'inherit', fontSize: 16, headerFontSize: 15, headerFontWeight: 700,
      foregroundColor: '#0B1220', textColor: '#0B1220', backgroundColor: '#FFFFFF',
      headerBackgroundColor: '#EEF0F3', headerTextColor: '#0B1220', accentColor: '#0E7490',
      borderColor: '#DCE1E8', rowBorder: {color: '#DCE1E8'}, oddRowBackgroundColor: '#FFFFFF',
      rowHoverColor: '#ECFEFF', selectedRowBackgroundColor: '#ECFEFF', spacing: 8,
      wrapperBorderRadius: 12, browserColorScheme: 'light', focusShadow: {radius: 3, color: '#1D4ED8'}
    });
    function result(p) {
      var s = document.createElement('span');
      s.className = 'tag ' + (p.data.kind || 'gray');
      s.textContent = p.value || '';
      return s;
    }
    function risk(p) {
      var w = document.createElement('span');
      w.className = 'risk';
      var src = safeDot(p.data.dot);
      if (src) {
        var img = document.createElement('img');
        var big = d.cvd === true;     // colour-blind mode: Trey's X / ! / check orbs, bigger so the mark reads
        img.className = big ? 'dot cvd' : 'dot'; img.width = big ? 36 : 24; img.height = img.width; img.alt = '';
        img.src = src;
        if (safeDot(p.data.dot2x)) { img.srcset = p.data.dot2x + ' 2x'; }
        w.appendChild(img);
      }
      var t = document.createElement('span');
      t.textContent = p.data.risk_label || '';
      w.appendChild(t);
      w.title = p.data.risk_why || '';
      return w;
    }
    function market(p) {
      var w = document.createElement('span');
      w.textContent = p.data.market_text || '-';
      if (p.data.market_source === 'example') {
        var x = document.createElement('small');
        x.className = 'ex'; x.textContent = 'EXAMPLE price';
        w.appendChild(x);
      }
      return w;
    }
    function diff(p) {
      var s = document.createElement('span');
      var v = p.data.diff_pct;
      if (v === null || v === undefined) { s.textContent = '-'; return s; }
      s.textContent = (v > 0 ? '+' : '') + v.toFixed(1) + '%';
      var ring = p.data.risk === 'green' ? 'green' : null;
      if (Math.abs(v) >= 25) { ring = Math.abs(v) >= 60 || v >= 100 ? 'red' : 'yellow'; }
      s.className = 'diff-' + (ring || 'green');
      return s;
    }
    function why(p) {
      var u = safeLink(p.data.link);
      if (!u) { return document.createTextNode(''); }
      var a = document.createElement('a');
      a.href = u; a.className = 'why-link'; a.textContent = 'Why?';
      a.setAttribute('aria-label', 'Why this light: ' + (p.data.side || '') + ' ' + (p.data.counterparty || ''));
      return a;
    }
    // Quick ring filter: All / Red / Yellow / Green buttons above the grid.
    var only = '';
    var bar = document.createElement('div');
    bar.className = 'row'; bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Show by risk');
    var api;
    [['', 'All'], ['red', 'Red only'], ['yellow', 'Yellow only'], ['green', 'Green only']].forEach(function (b) {
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'btn btn-quiet'; btn.textContent = b[1];
      btn.setAttribute('aria-pressed', b[0] === '' ? 'true' : 'false');
      btn.addEventListener('click', function () {
        only = b[0];
        Array.prototype.forEach.call(bar.children, function (c) { c.setAttribute('aria-pressed', c === btn ? 'true' : 'false'); });
        if (api) { api.onFilterChanged(); }
      });
      bar.appendChild(btn);
    });
    api = agGrid.createGrid(box, {
      theme: theme, styleNonce: box.getAttribute('data-nonce') || undefined,
      rowData: d.rows, domLayout: 'autoHeight', ensureDomOrder: true, suppressMovableColumns: true,
      pagination: d.rows.length > 20, paginationPageSize: 20, paginationPageSizeSelector: false,
      getRowId: function (p) { return p.data.id; },
      rowClassRules: {'risk-red': function (p) { return p.data.risk === 'red'; },
                      'risk-yellow': function (p) { return p.data.risk === 'yellow'; }},
      isExternalFilterPresent: function () { return only !== ''; },
      doesExternalFilterPass: function (n) { return n.data.risk === only; },
      defaultColDef: {sortable: true, filter: true, resizable: true, wrapText: true, autoHeight: true, flex: 1,
                      wrapHeaderText: true, autoHeaderHeight: true},
      columnDefs: [
        {field: 'risk', headerName: 'Risk', cellRenderer: risk, minWidth: 150, sort: 'desc',
         comparator: function (a, b, na, nb) {   // worst first; newest first inside a colour
           return ((RANK[a] || 0) - (RANK[b] || 0)) || (na.data.at || '').localeCompare(nb.data.at || ''); },
         filterValueGetter: function (p) { return p.data.risk_label; }},
        {field: 'when', headerName: 'Date', comparator: function (a, b, na, nb) {
          return (na.data.at || '').localeCompare(nb.data.at || ''); }, minWidth: 130},
        {field: 'side', headerName: 'Type', minWidth: 80, maxWidth: 100},
        {field: 'item', headerName: 'Item', flex: 1.5, minWidth: 130},
        {field: 'counterparty', headerName: 'Counterparty', flex: 2, minWidth: 180},
        {field: 'amount', headerName: 'Amount', type: 'rightAligned', filter: 'agNumberColumnFilter',
         valueFormatter: function (p) { return p.data.amount_text; }, minWidth: 100},
        {field: 'market', headerName: 'Market price', type: 'rightAligned', filter: 'agNumberColumnFilter',
         cellRenderer: market, minWidth: 115},
        {field: 'diff_pct', headerName: 'Difference %', type: 'rightAligned', filter: 'agNumberColumnFilter',
         cellRenderer: diff, minWidth: 110},
        {field: 'result', headerName: 'Flagged', cellRenderer: result, minWidth: 140},
        {field: 'why', headerName: 'Why', flex: 2.5, minWidth: 200, tooltipField: 'risk_why'},
        {field: 'choice', headerName: 'Your choice', minWidth: 120},
        {field: 'link', headerName: '', cellRenderer: why, sortable: false, filter: false, minWidth: 70, maxWidth: 80}
      ]
    });
    box.parentNode.insertBefore(bar, box);
    box.hidden = false; plain.hidden = true; tog.hidden = false;
    tog.addEventListener('click', function () {
      var simple = plain.hidden;
      plain.hidden = !simple; box.hidden = simple; bar.hidden = simple;
      tog.setAttribute('aria-pressed', simple ? 'true' : 'false');
      tog.lastChild.textContent = simple ? 'Show sortable grid' : 'Show simple table';
    });
  }).catch(function (err) { if (window.console) { console.warn('Grid not shown: ' + err); } });
})();
