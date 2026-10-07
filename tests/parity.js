const fs = require('fs'), path = require('path');
const E = require('../web/engine.js');
const root = path.join(__dirname, '..', 'web', 'data');
const model = new E.Model(JSON.parse(fs.readFileSync(path.join(root, 'model.json'))));
const py = JSON.parse(fs.readFileSync(process.argv[2]));
let worst = 0, n = 0;
for (const id of Object.keys(py)) {
  const m = JSON.parse(fs.readFileSync(path.join(root, 'matches', id + '.json')));
  const pts = E.timeline(model, m);
  if (pts.length !== py[id].length) { console.error('length mismatch', id, pts.length, py[id].length); process.exit(1); }
  pts.forEach((p, i) => {
    const pBat = p.bat === m.teams[0] ? p.pA : 1 - p.pA;
    worst = Math.max(worst, Math.abs(pBat - py[id][i])); n++;
  });
}
console.log('compared', n, 'ball states, max abs difference', worst.toExponential(2));
process.exit(worst < 1e-6 ? 0 : 1);
