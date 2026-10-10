(function () {
  'use strict';
  var E = window.ChaseEngine;
  var $ = function (id) { return document.getElementById(id); };
  var NS = 'http://www.w3.org/2000/svg';
  var S = { api: null, index: null, model: null, calib: null, match: null, pts: [], swings: [], cur: 0, timer: null, geo: null };

  function el(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function overs(l) { return Math.floor(l / 6) + '.' + (l % 6); }
  function pct(p) { return Math.round(p * 100); }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function fetchJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(u + ' ' + r.status); return r.json(); }); }

  /* ---------- theme and tabs ---------- */
  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('chase-theme', t); } catch (e) {}
  }
  (function initTheme() {
    var t = null;
    try { t = localStorage.getItem('chase-theme'); } catch (e) {}
    if (t) document.documentElement.setAttribute('data-theme', t);
    $('theme').addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      setTheme(cur === 'dark' ? 'light' : 'dark');
    });
  })();

  var TABS = ['replay', 'quality', 'whatif', 'live', 'about'];
  function showTab(name, focus) {
    TABS.forEach(function (t) {
      var on = t === name;
      var b = $('t-' + t);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      $('v-' + t).hidden = !on;
      if (on && focus) b.focus();
    });
    if (name === 'replay') drawChart();
  }
  TABS.forEach(function (t, i) {
    $('t-' + t).addEventListener('click', function () { showTab(t); });
    $('t-' + t).addEventListener('keydown', function (e) {
      var n = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (n) { e.preventDefault(); showTab(TABS[(i + n + TABS.length) % TABS.length], true); }
    });
  });

  /* ---------- ball description ---------- */
  function evt(b) {
    if (!b) return { label: 'Start of innings', cls: '' };
    if (b[2]) return { label: 'Wicket', cls: 'w' };
    if (b[4] === 1) return { label: 'Wide', cls: '' };
    if (b[4] === 2) return { label: 'No ball', cls: '' };
    if (b[3] === 6) return { label: 'Six', cls: '' };
    if (b[3] === 4) return { label: 'Four', cls: '' };
    if (b[1] === 0) return { label: 'Dot ball', cls: '' };
    return { label: b[1] + (b[1] === 1 ? ' run' : ' runs'), cls: '' };
  }
  function stateText(p) {
    if (p.inn === 1) return p.bat + ' ' + p.runs + '/' + p.wkts + ' after ' + overs(p.legal) + ' overs';
    var need = p.target - p.runs, left = 120 - p.legal;
    if (need <= 0) return p.bat + ' ' + p.runs + '/' + p.wkts + ', target reached';
    return p.bat + ' ' + p.runs + '/' + p.wkts + ', need ' + need + ' off ' + left + (left === 1 ? ' ball' : ' balls');
  }

  /* ---------- team colours ---------- */
  // [light-theme primary, dark-theme primary, light-theme secondary, dark-theme secondary]
  var TEAM_COLOURS = {
    csk:  ['#d99a00', '#ffcb05', '#0b7bd1', '#4fb0ff'],  // Chennai Super Kings: yellow, blue
    mi:   ['#005db4', '#4a9bea', '#c99a2e', '#e8c060'],  // Mumbai Indians: blue, gold
    rcb:  ['#d3161c', '#ff5a52', '#b8892b', '#e5be5c'],  // Royal Challengers: red, black and gold
    kkr:  ['#4b2a83', '#a27be0', '#b8962e', '#e3c467'],  // Kolkata Knight Riders: purple, gold
    dc:   ['#1a56b0', '#5c97e6', '#e3202b', '#ff6b6f'],  // Delhi Capitals: blue, red
    pbks: ['#d71920', '#ff5656', '#7c828a', '#c4c9cf'],  // Punjab Kings: red, silver
    rr:   ['#e4007c', '#ff5cad', '#2a4ba8', '#6f8fea'],  // Rajasthan Royals: pink, royal blue
    srh:  ['#f26522', '#ff8a3d', '#2b2b2b', '#e8e1d6'],  // Sunrisers Hyderabad: orange, black
    gt:   ['#1c2b5e', '#6e8ae8', '#b58a33', '#e1b85a'],  // Gujarat Titans: navy, gold
    lsg:  ['#0a9aae', '#2fc8dc', '#e8731a', '#ff9a4d']   // Lucknow Super Giants: teal, orange
  };
  function teamKey(name) {
    var n = String(name || '').toLowerCase();
    if (/chennai/.test(n)) return 'csk';
    if (/mumbai/.test(n)) return 'mi';
    if (/bengal|bangalore|royal challengers/.test(n)) return 'rcb';
    if (/kolkata/.test(n)) return 'kkr';
    if (/delhi/.test(n)) return 'dc';
    if (/punjab/.test(n)) return 'pbks';
    if (/rajasthan/.test(n)) return 'rr';
    if (/sunrisers|hyderabad/.test(n)) return 'srh';
    if (/gujarat/.test(n)) return 'gt';
    if (/lucknow/.test(n)) return 'lsg';
    return null;
  }
  function hexRGB(h) { return [1, 3, 5].map(function (i) { return parseInt(h.substr(i, 2), 16); }); }
  function colourGap(x, y) {            // weighted RGB distance, close to how different two colours look
    var p = hexRGB(x), q = hexRGB(y), rm = (p[0] + q[0]) / 2, dr = p[0] - q[0], dg = p[1] - q[1], db = p[2] - q[2];
    return Math.sqrt((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db);
  }
  // Colours for a pair of teams in one theme (0 light, 1 dark). If both teams wear a similar
  // colour (two blues, two reds), one of them switches to its secondary colour. RCB, CSK, MI and RR
  // always keep their main colour, so the other team switches; if neither is protected, the second one does.
  var KEEP_MAIN = ['rcb', 'csk', 'mi', 'rr'];
  function pairColours(teams, theme) {
    var ka = teamKey(teams[0]), kb = teamKey(teams[1]);
    var a = ka ? TEAM_COLOURS[ka][theme] : null, b = kb ? TEAM_COLOURS[kb][theme] : null;
    if (a && b && colourGap(a, b) < 150) {
      var pa = KEEP_MAIN.indexOf(ka) >= 0, pb = KEEP_MAIN.indexOf(kb) >= 0;
      if (pa && pb) return [a, b];
      if (pb) a = TEAM_COLOURS[ka][theme + 2]; else b = TEAM_COLOURS[kb][theme + 2];
    }
    return [a, b];
  }
  function setTeamColours(el, teams) {
    var vars = ['--ta-l', '--ta-d', '--tb-l', '--tb-d'];
    var l = pairColours(teams, 0), d = pairColours(teams, 1), v = [l[0], d[0], l[1], d[1]];
    vars.forEach(function (name, i) { if (v[i]) el.style.setProperty(name, v[i]); else el.style.removeProperty(name); });
  }
  function teamColor(name) { return name === S.match.teams[0] ? 'var(--ta,var(--a))' : 'var(--tb,var(--b))'; }

  /* ---------- match loading ---------- */
  function swingsOf(pts) {
    var out = [];
    for (var i = 1; i < pts.length; i++) {
      if (pts[i].inn !== pts[i - 1].inn) continue;
      var d = pts[i].pA - pts[i - 1].pA;
      if (Math.abs(d) >= 0.05) out.push({ i: i, d: d });
    }
    out.sort(function (p, q) { return Math.abs(q.d) - Math.abs(p.d); });
    return out.slice(0, 12).sort(function (p, q) { return p.i - q.i; });
  }
  function useMatch(m, pts, swings, ball) {
    pause();
    S.match = m;
    setTeamColours($('v-replay'), m.teams);
    S.pts = pts;
    S.swings = swings;
    S.cur = Math.max(0, Math.min(ball || 0, S.pts.length - 1));
    $('match').value = m.id;
    $('scrub').max = S.pts.length - 1;
    buildChart();
    render();
    renderTurns();
  }
  function loadMatch(id, ball) {
    if (S.api !== null) {
      return fetchJSON(S.api + '/api/matches/' + id + '/timeline').then(function (j) {
        useMatch(j.match, j.points, j.swings.map(function (s) { return { i: s.i, d: s.delta }; }), ball);
      }).catch(function () { return goOffline().then(function () { return loadMatch(id, ball); }); });
    }
    return fetchJSON('data/matches/' + id + '.json').then(function (m) {
      var pts = E.timeline(S.model, m);
      useMatch(m, pts, swingsOf(pts), ball);
    });
  }
  function goOffline() {
    S.api = null;
    $('foot-src').textContent += ' The API could not be reached, so predictions are now computed in your browser.';
    return fetchJSON('data/model.json').then(function (j) { S.model = new E.Model(j); });
  }

  /* ---------- rendering ---------- */
  function render() {
    var p = S.pts[S.cur], m = S.match, a = m.teams[0], b = m.teams[1];
    $('scrub').value = S.cur;
    // scoreboard
    var first = m.innings[0].team, boxes = [];
    [a, b].forEach(function (t) {
      var pt = null, note = '';
      if (S.cur < S.pts.length && p.inn === 1) { if (t === first) pt = p; else note = 'Yet to bat'; }
      else if (t === first) { pt = lastOf(1); } else { pt = p; }
      var batting = p.bat === t;
      var sc = pt ? pt.runs + '/' + pt.wkts + '<small>(' + overs(pt.legal) + ')</small>' : '<span style="font-size:.6em;color:var(--muted)">' + note + '</span>';
      boxes.push('<div class="sb ' + (batting ? 'bat' : 'idle') + '"><div class="tn"><span class="dot" style="background:' + teamColor(t) + '"></span>' + esc(t) + '</div><div class="sc">' + sc + '</div></div>');
    });
    $('scoreboard').innerHTML = boxes.join('');
    // reading
    var pa = pct(p.pA), pb = 100 - pa;
    $('reading').innerHTML =
      '<div class="pr a"><div class="n">' + pa + '%</div><div class="l">' + esc(a) + ' to win</div></div>' +
      '<div class="pr b right"><div class="n">' + pb + '%</div><div class="l">' + esc(b) + ' to win</div></div>' +
      '<div class="bar" role="presentation"><i style="width:' + (p.pA * 100).toFixed(1) + '%"></i></div>';
    // now line
    var ev = evt(p.ball), prev = S.cur > 0 && S.pts[S.cur - 1].inn === p.inn ? S.pts[S.cur - 1] : null;
    var d = prev ? (p.pA - prev.pA) * 100 : 0;
    var line = '<span class="tag ' + ev.cls + '">' + ev.label + '</span>' + esc(stateText(p));
    if (prev && Math.abs(d) >= 0.5) line += ' <span style="color:var(--muted)">(' + esc(d > 0 ? a : b) + ' ' + (d > 0 ? '+' : '+') + Math.abs(d).toFixed(1) + ' points)</span>';
    if (S.cur === S.pts.length - 1) line += ' <b>' + esc(resultText(m)) + '</b>';
    $('now').innerHTML = line;
    $('chart-cap').textContent = a + ' win probability is ' + pa + ' percent. ' + stateText(p) + '.';
    updateCursor();
  }
  function lastOf(inn) { for (var i = S.pts.length - 1; i >= 0; i--) if (S.pts[i].inn === inn) return S.pts[i]; }
  function resultText(m) {
    var o = m.outcome || {};
    if (!o.winner) return 'No result';
    var by = o.by || {};
    return o.winner + ' win' + (by.runs ? ' by ' + by.runs + ' runs' : by.wickets !== undefined ? ' by ' + by.wickets + ' wickets' : '');
  }

  function renderTurns() {
    var ol = $('turns');
    ol.innerHTML = '';
    if (!S.swings.length) { ol.innerHTML = '<li class="empty">No single ball moved this match by 5 points or more.</li>'; return; }
    var m = S.match;
    S.swings.forEach(function (s) {
      var p = S.pts[s.i], ev = evt(p.ball), favoured = s.d > 0 ? m.teams[0] : m.teams[1];
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.innerHTML = '<span class="ov">' + (p.inn === 1 ? '1st ' : '2nd ') + overs(p.legal) + '</span>' +
        '<span class="tx"><b>' + ev.label + '</b>, ' + esc(favoured) + ' ' + 'gain ground<small>' + esc(stateText(p)) + '</small></span>' +
        '<span class="dl ' + (s.d > 0 ? 'a' : 'b') + '">' + Math.abs(s.d * 100).toFixed(1) + '</span>';
      btn.addEventListener('click', function () { pause(); S.cur = s.i; render(); window.scrollTo({ top: $('chart').getBoundingClientRect().top + scrollY - 90, behavior: 'smooth' }); });
      li.appendChild(btn);
      ol.appendChild(li);
    });
  }

  /* ---------- chart ---------- */
  function buildChart() {
    var svg = $('chart'), W = Math.max(280, Math.floor(svg.parentNode.clientWidth - 16)), H = W < 520 ? 230 : 320;
    if (!S.pts.length) return;
    var padL = 12, padR = 12, padT = 26, padB = 30, pw = W - padL - padR, ph = H - padT - padB, N = S.pts.length - 1;
    var geo = S.geo = { W: W, H: H, padL: padL, pw: pw, N: N, padT: padT, ph: ph };
    var x = function (i) { return padL + pw * i / N; }, y = function (p) { return padT + (1 - p) * ph; };
    geo.x = x; geo.y = y;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.aspectRatio = 'auto';
    svg.innerHTML = '';
    var defs = el('defs', {});
    var up = el('clipPath', { id: 'cUp' }); up.appendChild(el('rect', { x: 0, y: 0, width: W, height: y(.5) }));
    var lo = el('clipPath', { id: 'cLo' }); lo.appendChild(el('rect', { x: 0, y: y(.5), width: W, height: H }));
    var pr = el('clipPath', { id: 'cPr' }); geo.progRect = el('rect', { x: 0, y: 0, width: 0, height: H }); pr.appendChild(geo.progRect);
    defs.appendChild(up); defs.appendChild(lo); defs.appendChild(pr); svg.appendChild(defs);
    // grid
    [0, .25, .5, .75, 1].forEach(function (g) {
      svg.appendChild(el('line', { x1: padL, x2: W - padR, y1: y(g), y2: y(g), stroke: 'var(--line)', 'stroke-width': g === .5 ? 1.5 : 1, 'stroke-dasharray': g === .5 ? '' : '3 4' }));
    });
    var line = S.pts.map(function (p, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.pA).toFixed(1); }).join('');
    var area = line + 'L' + x(N).toFixed(1) + ' ' + y(.5) + 'L' + x(0).toFixed(1) + ' ' + y(.5) + 'Z';
    function layer(group, opacity) {
      group.appendChild(el('path', { d: area, fill: 'var(--ta,var(--a))', 'fill-opacity': opacity, 'clip-path': 'url(#cUp)' }));
      group.appendChild(el('path', { d: area, fill: 'var(--tb,var(--b))', 'fill-opacity': opacity, 'clip-path': 'url(#cLo)' }));
    }
    var ghost = el('g', {}); layer(ghost, .13); svg.appendChild(ghost);
    svg.appendChild(el('path', { d: line, fill: 'none', stroke: 'var(--muted)', 'stroke-opacity': .5, 'stroke-width': 1 }));
    var solid = el('g', { 'clip-path': 'url(#cPr)' }); layer(solid, .5);
    solid.appendChild(el('path', { d: line, fill: 'none', stroke: 'var(--ink)', 'stroke-width': 2, 'stroke-linejoin': 'round' }));
    svg.appendChild(solid);
    // innings break
    var brk = S.pts.findIndex(function (p) { return p.inn === 2; });
    svg.appendChild(el('line', { x1: x(brk - .5), x2: x(brk - .5), y1: padT - 8, y2: H - padB + 4, stroke: 'var(--muted)', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: x(brk - .5) - 6, y: padT - 12, 'text-anchor': 'end' }, '1st innings: ' + S.match.innings[0].team));
    svg.appendChild(el('text', { x: x(brk - .5) + 6, y: padT - 12 }, '2nd innings: ' + S.match.innings[1].team));
    // over ticks
    (W < 520 ? [60, 120] : [30, 60, 90, 120]).forEach(function (L) {
      [1, 2].forEach(function (inn) {
        var i = S.pts.findIndex(function (p) { return p.inn === inn && p.legal === L; });
        if (i < 0) return;
        svg.appendChild(el('line', { x1: x(i), x2: x(i), y1: H - padB, y2: H - padB + 4, stroke: 'var(--muted)' }));
        svg.appendChild(el('text', { x: x(i), y: H - 8, 'text-anchor': i === N ? 'end' : 'middle' }, 'over ' + L / 6));
      });
    });
    svg.appendChild(el('text', { x: padL + 2, y: y(1) + 12, class: 'tn', style: 'fill:var(--ta,var(--a))' }, S.match.teams[0]));
    svg.appendChild(el('text', { x: padL + 2, y: y(0) - 5, class: 'tn', style: 'fill:var(--tb,var(--b))' }, S.match.teams[1]));
    // swing markers
    S.swings.forEach(function (s) {
      svg.appendChild(el('circle', { cx: x(s.i), cy: y(S.pts[s.i].pA), r: 3.2, fill: 'var(--panel)', stroke: 'var(--ink)', 'stroke-width': 1.5 }));
    });
    geo.cursor = el('g', {});
    geo.cursor.appendChild(geo.cl = el('line', { y1: padT - 6, y2: H - padB, stroke: 'var(--ink)', 'stroke-width': 1 }));
    geo.cursor.appendChild(geo.cd = el('circle', { r: 5.5, fill: 'var(--ink)', stroke: 'var(--panel)', 'stroke-width': 2 }));
    svg.appendChild(geo.cursor);
    updateCursor();
  }
  function updateCursor() {
    var g = S.geo; if (!g || !g.cl) return;
    var xx = g.x(S.cur);
    g.progRect.setAttribute('width', xx);
    g.cl.setAttribute('x1', xx); g.cl.setAttribute('x2', xx);
    g.cd.setAttribute('cx', xx); g.cd.setAttribute('cy', g.y(S.pts[S.cur].pA));
  }
  function drawChart() { if (S.match && !$('v-replay').hidden) buildChart(); }
  (function () {
    var t; window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(drawChart, 120); });
    var svg = $('chart'), drag = false;
    function at(e) {
      var g = S.geo; if (!g) return;
      var r = svg.getBoundingClientRect(), xx = (e.clientX - r.left) / r.width * g.W;
      S.cur = Math.max(0, Math.min(g.N, Math.round((xx - g.padL) / g.pw * g.N)));
      render();
    }
    svg.addEventListener('pointerdown', function (e) { drag = true; pause(); svg.setPointerCapture(e.pointerId); at(e); });
    svg.addEventListener('pointermove', function (e) { if (drag) at(e); });
    svg.addEventListener('pointerup', function () { drag = false; syncHash(); });
  })();

  /* ---------- playback ---------- */
  function setPlayLabel(on) { $('play').textContent = on ? 'Pause' : (S.cur >= S.pts.length - 1 ? 'Replay' : 'Play'); $('play').setAttribute('aria-label', on ? 'Pause replay' : 'Play replay'); }
  function pause() { if (S.timer) { clearInterval(S.timer); S.timer = null; } setPlayLabel(false); syncHash(); }
  function play() {
    if (S.cur >= S.pts.length - 1) S.cur = 0;
    setPlayLabel(true);
    S.timer = setInterval(function () {
      if (S.cur >= S.pts.length - 1) { pause(); render(); return; }
      S.cur++; render();
    }, +$('speed').value);
  }
  $('play').addEventListener('click', function () { S.timer ? pause() : play(); });
  $('back').addEventListener('click', function () { pause(); S.cur = Math.max(0, S.cur - 1); render(); });
  $('fwd').addEventListener('click', function () { pause(); S.cur = Math.min(S.pts.length - 1, S.cur + 1); render(); });
  $('scrub').addEventListener('input', function () { pause(); S.cur = +this.value; render(); });
  $('speed').addEventListener('change', function () { if (S.timer) { pause(); play(); } });
  function syncHash() {
    if (!S.match) return;
    try { history.replaceState(null, '', '#m=' + S.match.id + '&b=' + S.cur); } catch (e) {}
  }

  /* ---------- picker ---------- */
  function fillPicker() {
    var sel = $('match');
    S.index.matches.forEach(function (m) {
      var o = document.createElement('option');
      o.value = m.id;
      o.textContent = m.date + '  ' + m.teams[0] + ' v ' + m.teams[1];
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () { loadMatch(sel.value, 0); });
    $('random').addEventListener('click', function () {
      var ms = S.index.matches, m = ms[Math.floor(Math.random() * ms.length)];
      loadMatch(m.id, 0);
    });
  }

  /* ---------- model quality ---------- */
  function f3(v) { return v.toFixed(3); }
  function renderQuality() {
    var c = S.calib, M = c.models, n = c.split;
    var chase = M.chase_calibrated, lr = M.logistic_baseline;
    var beats = chase.brier < lr.brier;
    $('q-lede').innerHTML = 'Tested on ' + n.test_matches + ' held-out matches (' + n.test_rows.toLocaleString() + ' ball states). ' +
      'On average Chase\'s probabilities are off by about ' + (chase.ece * 100).toFixed(1) + ' points from what actually happened (calibration error). ' +
      (beats ? 'It beats' : Math.abs(chase.brier - lr.brier) < 0.003 ? 'It is level with' : 'It does not beat') + ' a plain logistic-regression baseline on Brier score (' + f3(chase.brier) + ' against ' + f3(lr.brier) + ')' +
      (chase.ece < lr.ece ? ', but is better calibrated (' + (chase.ece * 100).toFixed(1) + ' against ' + (lr.ece * 100).toFixed(1) + ' points).' : '.') +
      (c.source === 'simulated' ? ' These are simulated matches, so the numbers show the evaluation machinery working, not cricket truth.' : '');
    var rows = [['Chase, calibrated', M.chase_calibrated, 1], ['Chase, before calibration', M.chase_uncalibrated], ['Logistic regression baseline', M.logistic_baseline], ['Pre-match prior only', M.prior_only]];
    var keys = ['brier', 'logloss', 'ece'], best = {};
    keys.forEach(function (k) { best[k] = Math.min.apply(null, rows.map(function (r) { return r[1][k]; })); });
    var h = '<tr><th>Model</th><th>Brier score</th><th>Log loss</th><th>Calibration error</th></tr>';
    rows.forEach(function (r) {
      h += '<tr' + (r[2] ? ' class="me"' : '') + '><td>' + r[0] + '</td>' + keys.map(function (k) { return '<td' + (r[1][k] === best[k] ? ' class="best"' : '') + '>' + f3(r[1][k]) + '</td>'; }).join('') + '</tr>';
    });
    $('q-table').innerHTML = h;
    // stages
    var sh = '<tr><th>Stage</th><th>Chase</th><th>Logistic</th><th>Prior only</th><th>States</th></tr>';
    Object.keys(c.by_stage).forEach(function (k) {
      var s = c.by_stage[k];
      sh += '<tr><td>' + k + '</td><td>' + f3(s.chase) + '</td><td>' + f3(s.logistic) + '</td><td>' + f3(s.prior) + '</td><td>' + s.n.toLocaleString() + '</td></tr>';
    });
    $('q-stage').innerHTML = sh;
    var mo = c.monotonicity;
    $('q-mono').textContent = 'More wickets must never help the batting side, and more runs or more balls in hand must never hurt it. On a sample of held-out states, breaches found: wickets ' +
      (mo.wkts.violation_rate * 100).toFixed(1) + '%, runs ' + (mo.runs.violation_rate * 100).toFixed(1) + '%, balls left ' + (mo.balls_left.violation_rate * 100).toFixed(1) + '%.';
    // reliability plot
    var svg = $("rel"), W = 360, P = 46, sz = W - P - 14;
    svg.innerHTML = '';
    var X = function (v) { return P + v * sz; }, Y = function (v) { return 14 + (1 - v) * sz; };
    [0, .25, .5, .75, 1].forEach(function (g) {
      svg.appendChild(el('line', { x1: X(0), x2: X(1), y1: Y(g), y2: Y(g), stroke: 'var(--line)' }));
      svg.appendChild(el('line', { x1: X(g), x2: X(g), y1: Y(0), y2: Y(1), stroke: 'var(--line)' }));
      svg.appendChild(el('text', { x: P - 6, y: Y(g) + 3, 'text-anchor': 'end' }, Math.round(g * 100) + '%'));
      svg.appendChild(el('text', { x: X(g), y: Y(0) + 14, 'text-anchor': 'middle' }, Math.round(g * 100) + '%'));
    });
    svg.appendChild(el('line', { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), stroke: 'var(--muted)', 'stroke-dasharray': '4 4' }));
    function curve(rel, color, dash) {
      var d = rel.map(function (b, i) { return (i ? 'L' : 'M') + X(b.pred).toFixed(1) + ' ' + Y(b.actual).toFixed(1); }).join('');
      svg.appendChild(el('path', { d: d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-dasharray': dash || '' }));
      return rel;
    }
    curve(M.logistic_baseline.reliability, 'var(--b)', '5 3');
    curve(M.chase_calibrated.reliability, 'var(--a)').forEach(function (b) {
      svg.appendChild(el('circle', { cx: X(b.pred), cy: Y(b.actual), r: 3.5, fill: 'var(--a)' }));
    });
    svg.appendChild(el('text', { x: P + 8, y: 30, style: 'fill:var(--a);font-weight:600' }, 'Chase (calibrated)'));
    svg.appendChild(el('text', { x: P + 8, y: 44, style: 'fill:var(--b);font-weight:600' }, 'Logistic baseline (dashed)'));
    svg.appendChild(el('text', { x: X(.5), y: W - 2, 'text-anchor': 'middle' }, 'Predicted probability'));
    svg.appendChild(el('text', { x: 10, y: Y(.5), transform: 'rotate(-90 10 ' + Y(.5) + ')', 'text-anchor': 'middle' }, 'Share actually won'));
  }

  /* ---------- what if ---------- */
  var wiTimer = null;
  function renderWhatIf() {
    var inn = +$('wi-inn').value, runs = +$('wi-runs').value || 0, wk = Math.min(10, +$('wi-wkts').value || 0),
      balls = Math.min(120, +$('wi-balls').value || 0), tgt = +$('wi-target').value || 1, edge = +$('wi-edge').value;
    $('wi-t-l').style.display = inn === 2 ? '' : 'none';
    $('wi-edge-v').textContent = edge === 0 ? 'Even match' : (edge > 0 ? 'Batting side ahead by ' : 'Batting side behind by ') + Math.abs(edge) + ' rating points';
    var s = inn === 2 ? 'Chasing ' + tgt + ': ' + runs + '/' + wk + ' after ' + overs(balls) + ' overs, needing ' + Math.max(0, tgt - runs) + ' off ' + (120 - balls) + '.' : 'Batting first: ' + runs + '/' + wk + ' after ' + overs(balls) + ' overs.';
    function show(p) {
      $('wi-out').innerHTML = '<div class="pr a"><div class="n">' + pct(p) + '%</div><div class="l">Batting side to win</div></div>' +
        '<div class="pr b right"><div class="n">' + (100 - pct(p)) + '%</div><div class="l">Bowling side to win</div></div>' +
        '<div class="bar" style="grid-column:1/-1"><i style="width:' + (p * 100).toFixed(1) + '%"></i></div><p class="sub" style="grid-column:1/-1;margin-top:10px">' + esc(s) + '</p>';
    }
    if (S.api !== null) {
      clearTimeout(wiTimer);
      wiTimer = setTimeout(function () {
        fetch(S.api + '/api/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ innings: inn, runs: runs, wickets: wk, balls_bowled: balls, target: inn === 2 ? tgt : null, rating_edge: edge }) })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function (j) { show(j.batting_win_probability); })
          .catch(function () { goOffline().then(renderWhatIf); });
      }, 120);
      return;
    }
    var pl = E.priorLogit(1500 + edge, 1500);
    show(S.model.predict(E.stateFeatures(inn, runs, wk, balls, inn === 2 ? tgt : null, pl)));
  }
  ['wi-inn', 'wi-runs', 'wi-wkts', 'wi-balls', 'wi-target', 'wi-edge'].forEach(function (id) { $(id).addEventListener('input', function () { if (S.model || S.api !== null) renderWhatIf(); }); });

  /* ---------- about ---------- */
  function renderAbout() {
    var sim = S.calib.source === 'simulated';
    $('about').innerHTML =
      '<p>Chase turns every ball of a T20 match into a win probability and says why it moved. The probability comes from a gradient-boosted tree model that runs in your browser, and the same model runs behind the Chase API.</p>' +
      '<h2>What the model sees</h2><ul><li>Runs, wickets and balls left at this point in the innings</li><li>When chasing: runs still needed and the required run rate</li><li>Nothing about the teams or players. A team-rating prior was tested and dropped because it did not improve held-out scores on IPL data.</li></ul>' +
      '<h2>How it is kept honest</h2><ul><li>It is trained on earlier matches, tuned on a later slice and scored on the latest matches, never mixed.</li><li>Rules are built in: more wickets cannot help the batting side, and more runs or balls cannot hurt it.</li><li>The Model quality tab publishes every score, including where Chase is not the best option.</li></ul>' +
      '<h2>Data</h2>' + (sim ?
        '<p>This build uses <b>simulated matches with fictional teams</b>, generated so the whole pipeline can run end to end. Nothing here is a real result. Running the pipeline on real <a href="https://cricsheet.org/downloads/">Cricsheet</a> ball-by-ball files replaces them.</p>' :
        '<p>Ball-by-ball data is from <a href="https://cricsheet.org/">Cricsheet</a>. Check its terms before reusing the derived files.</p>') +
      '<h2>Limits</h2><p>Probabilities are estimates, not predictions of what a given team will do. They ignore pitch, weather, team strength and who is at the crease, so a star batter walking in changes nothing until the scoreboard does. The held-out matches are the latest in the data, when IPL scoring was higher than in the training years, which hurts every model here. Chase is not for betting.</p>';
  }

  /* ---------- live scoring (API only) ---------- */
  var L = { sid: null, pts: [], log: [] };
  function livePost(path, body) {
    return fetch(S.api + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || r.status); return j; }); });
  }
  function liveRender() {
    var out = $('live-out');
    if (!L.sid) { out.innerHTML = ''; return; }
    var p = L.pts[L.pts.length - 1], a = L.teams[0], b = L.teams[1], pa = pct(p.pA);
    setTeamColours(out, L.teams);
    var spark = '';
    if (L.pts.length > 1) {
      var W = 600, H = 90, n = L.pts.length - 1;
      var d = L.pts.map(function (q, i) { return (i ? 'L' : 'M') + (i / n * W).toFixed(1) + ' ' + ((1 - q.pA) * H).toFixed(1); }).join('');
      spark = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" style="width:100%;height:90px;background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-top:12px" role="img" aria-label="Win probability so far"><line x1="0" x2="' + W + '" y1="' + H / 2 + '" y2="' + H / 2 + '" stroke="var(--line)"/><path d="' + d + '" fill="none" stroke="var(--ink)" stroke-width="2"/></svg>';
    }
    out.innerHTML = '<div class="reading" style="margin-top:6px"><div class="pr a"><div class="n">' + pa + '%</div><div class="l">' + esc(a) + ' to win</div></div>' +
      '<div class="pr b right"><div class="n">' + (100 - pa) + '%</div><div class="l">' + esc(b) + ' to win</div></div>' +
      '<div class="bar"><i style="width:' + (p.pA * 100).toFixed(1) + '%"></i></div></div>' + spark +
      '<p class="now">' + esc(stateText(p)) + '</p>' +
      '<ul class="turnlist">' + L.log.slice(-6).reverse().map(function (x) { return '<li class="empty" style="padding:8px 0;border-bottom:1px solid var(--line)">' + x + '</li>'; }).join('') + '</ul>';
  }
  function liveBall(body, label) {
    livePost('/api/live/' + L.sid + '/ball', body).then(function (ev) {
      L.pts.push(ev.point);
      var note = '<span class="tag ' + (body.wicket ? 'w' : '') + '">' + label + '</span>' + esc(stateText(ev.point));
      if (ev.swing) note += ' <b>' + esc(ev.swing.favours) + ' +' + Math.abs(ev.swing.delta * 100).toFixed(1) + ' points</b>';
      if (ev.innings_over) note += ' <b>Innings over: use "Start second innings".</b>';
      if (ev.finished) note += ' <b>Match finished.</b>';
      L.log.push(note);
      liveRender();
    }).catch(function (e) { L.log.push('<b>' + esc(e.message) + '</b>'); liveRender(); });
  }
  function initLive() {
    $('t-live').hidden = false;
    $('live-start').addEventListener('click', function () {
      var a = $('live-a').value.trim() || 'Team A', b = $('live-b').value.trim() || 'Team B';
      livePost('/api/live', { team_a: a, team_b: b, batting_first: $('live-first').value === 'b' ? b : a }).then(function (j) {
        L.sid = j.id; L.teams = j.teams; L.pts = [j.point]; L.log = [];
        $('live-pad').hidden = false; liveRender();
      }).catch(function (e) { $('live-out').innerHTML = '<p class="empty">' + esc(e.message) + '</p>'; });
    });
    [['0', { total_runs: 0 }, 'Dot'], ['1', { total_runs: 1, batter_runs: 1 }, '1 run'], ['2', { total_runs: 2, batter_runs: 2 }, '2 runs'],
      ['3', { total_runs: 3, batter_runs: 3 }, '3 runs'], ['4', { total_runs: 4, batter_runs: 4 }, 'Four'], ['6', { total_runs: 6, batter_runs: 6 }, 'Six'],
      ['Wicket', { total_runs: 0, wicket: true }, 'Wicket'], ['Wide', { total_runs: 1, extra: 1 }, 'Wide'], ['No ball', { total_runs: 1, extra: 2 }, 'No ball']
    ].forEach(function (d) {
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'ghost'; btn.textContent = d[0];
      btn.addEventListener('click', function () { if (L.sid) liveBall(d[1], d[2]); });
      $('live-btns').appendChild(btn);
    });
    $('live-inn').addEventListener('click', function () {
      livePost('/api/live/' + L.sid + '/innings').then(function (ev) { L.pts.push(ev.point); L.log.push('Second innings begins, target ' + ev.point.target); liveRender(); })
        .catch(function (e) { L.log.push('<b>' + esc(e.message) + '</b>'); liveRender(); });
    });
  }

  /* ---------- boot ---------- */
  function detectApi() {
    var cands = [];
    var cfg = (window.CHASE_CONFIG && window.CHASE_CONFIG.api) || '';
    if (cfg) cands.push(cfg.replace(/\/$/, ''));
    if (location.protocol.indexOf('http') === 0) cands.push('');
    function tryOne(i) {
      if (i >= cands.length) return Promise.resolve(null);
      var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null, t = ctl && setTimeout(function () { ctl.abort(); }, 4000);
      return fetch(cands[i] + '/health', { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function (j) { if (t) clearTimeout(t); return j && j.status === 'ok' ? cands[i] : tryOne(i + 1); })
        .catch(function () { if (t) clearTimeout(t); return tryOne(i + 1); });
    }
    return tryOne(0);
  }
  detectApi().then(function (base) {
    S.api = base;
    var api = base !== null;
    return Promise.all([
      api ? fetchJSON(base + '/api/matches') : fetchJSON('data/index.json'),
      api ? Promise.resolve(null) : fetchJSON('data/model.json'),
      api ? fetchJSON(base + '/api/calibration') : fetchJSON('data/calibration.json')
    ]);
  }).then(function (r) {
    S.index = r[0]; S.model = r[1] ? new E.Model(r[1]) : null; S.calib = r[2];
    var sim = S.calib.source === 'simulated';
    if (sim) {
      $('banner').hidden = false;
      $('banner').innerHTML = 'Demo data: these are simulated matches between fictional teams, so the numbers show how Chase works, not real results.';
    }
    $('foot-src').textContent = (sim ? 'Simulated data. Replace with Cricsheet ball-by-ball files by running the pipeline.' : 'Ball-by-ball data: Cricsheet (cricsheet.org).') +
      (S.api !== null ? ' Predictions are computed by the Chase API.' : ' Predictions are computed in your browser.');
    if (S.api !== null) initLive();
    fillPicker(); renderQuality(); renderWhatIf(); renderAbout();
    var h = (location.hash || '').match(/m=([^&]+)&b=(\d+)/), id = h && S.index.matches.some(function (m) { return m.id === h[1]; }) ? h[1] : S.index.matches[0].id;
    return loadMatch(id, h ? +h[2] : 0);
  }).catch(function (e) {
    $('main').insertAdjacentHTML('afterbegin', '<p class="empty">Could not load the data (' + esc(String(e.message)) + '). Serve this folder over http and reload.</p>');
  });
})();
