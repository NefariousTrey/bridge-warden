/* Bridge Warden v6: the BW AG Grid agent's spending grid (AG Grid Community, MIT, self-hosted).
   Made by @Nefarious_Trey,
   with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
   Read-only. Progressive enhancement: if this file or AG Grid does not load, the charts and lists stay. No outside calls. */
(function () {
  var box = document.getElementById('bw-money-grid');
  if (!box || !window.agGrid) { return; }
  var COLOR = {bills: '#1D4ED8', subscriptions: '#7C3AED', gas: '#B45309', food: '#047857', other: '#475569'};
  fetch('/money-map.json', {credentials: 'same-origin', cache: 'no-store'}).then(function (r) {
    return r.ok ? r.json() : null;
  }).then(function (d) {
    if (!d || !d.rows || !d.rows.length) { return; }
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    var theme = agGrid.themeQuartz.withParams(dark ? {
      fontFamily: 'inherit', fontSize: 16, headerFontSize: 15, headerFontWeight: 700,
      foregroundColor: '#E5E7EB', textColor: '#E5E7EB', backgroundColor: '#1A2333',
      headerBackgroundColor: '#243042', headerTextColor: '#F3F4F6', accentColor: '#22D3EE',
      borderColor: '#334155', oddRowBackgroundColor: '#1E293B', rowHoverColor: '#0B2A33',
      spacing: 8, wrapperBorderRadius: 12, browserColorScheme: 'dark'
    } : {
      fontFamily: 'inherit', fontSize: 16, headerFontSize: 15, headerFontWeight: 700,
      foregroundColor: '#0B1220', textColor: '#0B1220', backgroundColor: '#FFFFFF',
      headerBackgroundColor: '#EEF0F3', headerTextColor: '#0B1220', accentColor: '#0E7490',
      borderColor: '#DCE1E8', oddRowBackgroundColor: '#FFFFFF', rowHoverColor: '#ECFEFF',
      spacing: 8, wrapperBorderRadius: 12, browserColorScheme: 'light'
    });
    function group(p) {
      var w = document.createElement('span');
      w.className = 'ag-group';
      var sw = document.createElement('i');
      sw.className = 'sw sw-' + (COLOR[p.data.group_key] ? p.data.group_key : 'other');
      w.appendChild(sw);
      w.appendChild(document.createTextNode(' ' + (p.value || '')));
      return w;
    }
    function money(p) {
      var v = Number(p.value || 0);
      return (v < 0 ? '-$' : '$') + Math.abs(v).toFixed(2);
    }
    function flag(p) {
      var s = document.createElement('span');
      if (p.value) { s.className = 'tag held'; s.textContent = p.value; s.title = p.value; }
      return s;
    }
    agGrid.createGrid(box, {
      theme: theme, styleNonce: box.getAttribute('data-nonce') || undefined,   // CSP: AG Grid's theme CSS uses the page nonce
      rowData: d.rows, domLayout: 'autoHeight', pagination: true, paginationPageSize: 20,
      paginationPageSizeSelector: [20, 50, 100], animateRows: false,
      defaultColDef: {sortable: true, filter: true, resizable: true, minWidth: 110},
      columnDefs: [
        {field: 'date', headerName: 'Date', sort: 'desc', width: 130},
        {field: 'merchant', headerName: 'Paid to', flex: 1, minWidth: 160},
        {field: 'group', headerName: 'Group', cellRenderer: group, width: 170},
        {field: 'amount', headerName: 'Amount', valueFormatter: money, type: 'rightAligned', width: 140},
        {field: 'kind', headerName: 'Kind', width: 120},
        {field: 'flags', headerName: 'What the agent saw', cellRenderer: flag, flex: 2, minWidth: 220}
      ]
    });
    box.hidden = false;
  }).catch(function () { /* keep the plain view */ });
})();
