/* Chase engine: evaluates the exported gradient-boosted trees in the browser.
   Mirrors pipeline/features.py exactly; tests/parity.py and tests/parity.js check that. */
(function (root) {
  'use strict';
  var LN10_OVER_400 = Math.log(10) / 400;

  function priorLogit(eloBat, eloBowl) { return (eloBat - eloBowl) * LN10_OVER_400; }

  // inn: 1 or 2; target: runs to win (innings 2) or null
  function stateFeatures(inn, runs, wkts, legal, target, prior) {
    var ballsLeft = 120 - legal, runsNeeded = 0, rrr = 0;
    if (inn === 2 && target !== null && target !== undefined) {
      var need = target - runs;
      if (need <= 0) rrr = 0;
      else if (ballsLeft <= 0) rrr = 99;
      else rrr = need / ballsLeft * 6;
      runsNeeded = Math.max(need, 0);
    }
    var resource = ballsLeft * (10 - wkts) / 1200;
    return [inn, runs, wkts, ballsLeft, runsNeeded, rrr, resource, prior];
  }

  function evalTree(node, x) {
    while (typeof node !== 'number') node = x[node.f] <= node.t ? node.l : node.r;
    return node;
  }

  function sigmoid(z) { return 1 / (1 + Math.exp(-z)); }

  function Model(json) {
    this.trees = json.trees;
    this.a = json.platt.a;
    this.b = json.platt.b;
    this.source = json.source;
  }
  // Probability that the BATTING side wins, given a feature vector.
  Model.prototype.predict = function (x) {
    var raw = 0;
    for (var i = 0; i < this.trees.length; i++) raw += evalTree(this.trees[i], x);
    return sigmoid(this.a * raw + this.b);
  };

  // Build the full timeline of a match record. Returns arrays aligned with ball index, for team A (teams[0]).
  function timeline(model, match) {
    var A = match.teams[0], pts = [], target = null;
    var firstRuns = 0;
    match.innings[0].balls.forEach(function (b) { firstRuns += b[1]; });
    for (var k = 0; k < 2; k++) {
      var inn = match.innings[k], team = inn.team, other = team === A ? match.teams[1] : A;
      var pl = priorLogit(match.elo[team], match.elo[other]);
      var runs = 0, wkts = 0, legal = 0, tgt = k === 1 ? (inn.target || firstRuns + 1) : null;
      for (var i = 0; i <= inn.balls.length; i++) {
        if (i > 0) { var b = inn.balls[i - 1]; runs += b[1]; wkts += b[2]; legal += b[0]; }
        var pb = model.predict(stateFeatures(k + 1, runs, wkts, legal, tgt, pl));
        pts.push({ inn: k + 1, i: i, runs: runs, wkts: wkts, legal: legal, target: tgt, bat: team,
                   pA: team === A ? pb : 1 - pb, ball: i > 0 ? inn.balls[i - 1] : null });
      }
    }
    return pts;
  }

  var api = { stateFeatures: stateFeatures, priorLogit: priorLogit, Model: Model, timeline: timeline };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.ChaseEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
