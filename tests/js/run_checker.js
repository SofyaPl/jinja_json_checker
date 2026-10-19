// Reads a JSON array of texts from the file given as argv[2], prints results as JSON.
const fs = require('fs');
const path = require('path');
const JJC = require(path.join(__dirname, '..', '..', 'extension', 'checker.js'));

const texts = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const results = texts.map(function (text) {
  const r = JJC.check(text);
  return {
    mode: r.mode,
    issues: r.issues.map(function (i) {
      return [i.severity, i.message, i.offset, i.length, i.source];
    }),
  };
});
process.stdout.write(JSON.stringify(results));
