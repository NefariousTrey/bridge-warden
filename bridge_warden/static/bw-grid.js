/* Bridge Warden: sortable, filterable money-moves grid (AG Grid Community, MIT, self-hosted).
   Progressive enhancement: if this file or AG Grid does not load, the plain table stays. No outside calls. */
(function () {
  var box = document.getElementById('bw-grid');
  var plain = document.getElementById('bw-plain');
  var tog = document.getElementById('bw-grid-toggle');
  if (!box || !plain || !tog || !window.agGrid) { return; }
  fetch('/moves.json', {credentials: 'same-origin', cache: 'no-store'}).then(function (r) {
    return r.ok ? r.json() : null;
  }).then(function (d) {
    if (!d || !d.rows || !d.rows.length) { return; }
    var theme = agGrid.themeQuartz.withParams({
      fontFamily: 'inherit', fontSize: 18, headerFontSize: 17, headerFontWeight: 700,
      foregroundColor: '#0B1220', textColor: '#0B1220', backgroundColor: '#FFFFFF',
      headerBackgroundColor: '#EEF0F3', headerTextColor: '#0B1220', accentColor: '#0E7490',
      borderColor: '#DCE1E8', rowBorder: {color: '#DCE1E8'}, oddRowBackgroundColor: '#FFFFFF',
      rowHoverColor: '#ECFEFF', selectedRowBackgroundColor: '#ECFEFF', spacing: 9,
      wrapperBorderRadius: 12, browserColorScheme: 'light', focusShadow: {radius: 3, color: '#1D4ED8'}
    });
    function result(p) {
      var s = document.createElement('span');
      s.className = 'tag ' + (p.data.kind || 'gray');
      s.textContent = p.value || '';
      return s;
    }
    agGrid.createGrid(box, {
      theme: theme, styleNonce: box.getAttribute('data-nonce') || undefined,
      rowData: d.rows, domLayout: 'autoHeight', ensureDomOrder: true, suppressMovableColumns: true,
      pagination: d.rows.length > 20, paginationPageSize: 20, paginationPageSizeSelector: false,
      defaultColDef: {sortable: true, filter: true, resizable: true, wrapText: true, autoHeight: true, flex: 1},
      columnDefs: [
        {field: 'when', headerName: 'When', comparator: function (a, b, na, nb) {
          return (na.data.at || '').localeCompare(nb.data.at || ''); }, minWidth: 130},
        {field: 'what', headerName: 'What', flex: 2, minWidth: 170},
        {field: 'amount', headerName: 'Amount', type: 'rightAligned', filter: 'agNumberColumnFilter',
         valueFormatter: function (p) { return p.data.amount_text; }, minWidth: 140},
        {field: 'result', headerName: 'Result', cellRenderer: result, minWidth: 165},
        {field: 'why', headerName: 'Why', flex: 2, minWidth: 180}
      ]
    });
    box.hidden = false; plain.hidden = true; tog.hidden = false;
    tog.addEventListener('click', function () {
      var simple = plain.hidden;
      plain.hidden = !simple; box.hidden = simple;
      tog.setAttribute('aria-pressed', simple ? 'true' : 'false');
      tog.lastChild.textContent = simple ? 'Show sortable grid' : 'Show simple table';
    });
  }).catch(function (err) { if (window.console) { console.warn('Grid not shown: ' + err); } });
})();
