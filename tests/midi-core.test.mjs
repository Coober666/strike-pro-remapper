import {test} from 'node:test';
import assert from 'node:assert/strict';
import {newSession, validateSession, summarize, compare, message, demoSession, exportCSV, report, MAX_EVENTS, MAX_DURATION} from '../web/midi-toolkit/core.js';
test('partial host captures retain their status across import and exports', () => {
  const value=demoSession(); value.captureStatus='partial';
  assert.equal(validateSession(value).captureStatus,'partial');
  assert.match(exportCSV(value),/"partial"/);
  assert.match(report(value),/Capture status: partial/);
  delete value.captureStatus; assert.equal(validateSession(value).captureStatus,'complete');
  value.captureStatus='unknown'; assert.throws(() => validateSession(value));
});
function fixture() {
  const s=newSession('Test', 'Drum input'); s.durationMs=1000;
  s.events=[{t:0,data:[0x99,38,20]},{t:10,data:[0x99,38,0]},{t:100,data:[0x99,38,100]},
    {t:110,data:[0x89,38,0]},{t:200,data:[0x98,38,80]},{t:300,data:[0xb9,4,30]},
    {t:400,data:[0xb9,4,120]},{t:500,data:[0xd9,22]}]; return s;
}
test('channel separation, zero velocity note-off and controller ranges', () => {
  const s=summarize(fixture());
  assert.equal(s.hits,3); assert.equal(s.count,8); assert.equal(s.notes.length,2);
  const n=s.notes.find(n => n.channel === 10);
  assert.equal(n.mean,60); assert.equal(n.std,40); assert.equal(n.minGapMs,100);
  assert.equal(s.notes.find(n => n.channel === 9).minGapMs,null);
  assert.deepEqual(s.controllers,[{channel:10,controller:4,count:2,min:30,max:120,last:120}]);
  assert.equal(s.histogram.reduce((a,b) => a+b),3);
  assert.equal(summarize(fixture(),50).hits,1);
});
test('only complete channel messages are accepted', () => {
  for (const bytes of [[0xf0,1,0xf7],[0xf8],[0xfe],[38,80],[0x90,38],[0x90,128,20],[0xc0,0,0],[0x90,38,NaN]]) assert.equal(message(bytes),null);
  assert.equal(message([0x90,38,0]).type,'Note off');
  assert.equal(message([0xcf,12]).channel,16);
});
test('JSON round trip retains events while stripping untrusted extra fields', () => {
  const s=fixture(); s.html='<script>ignored</script>';
  const clean=validateSession(JSON.parse(JSON.stringify(s)));
  assert.deepEqual(clean.events,s.events); assert.equal(clean.html,undefined);
  assert.equal(clean.synthetic,false);
});
test('invalid imports fail without silently sorting or dropping events', () => {
  for (const change of [s => s.version=2, s => s.durationMs=-1, s => s.durationMs=MAX_DURATION+1,
    s => s.events[1].t=-1, s => s.events[1].t=1001, s => s.events[1].data=[0xf0,0xf7],
    s => s.events=Array(MAX_EVENTS+1).fill(s.events[0]), s => s.name='x'.repeat(121),
    s => s.createdAt='not a date', s => delete s.synthetic]) {
    const s=fixture(); change(s); assert.throws(() => validateSession(s),/Invalid session/);
  }
});
test('comparison preserves unmatched notes and does not mix channels', () => {
  const a=fixture(), b=fixture(); b.events=b.events.filter(e => (e.data[0]&15) === 9);
  b.events[0].data[2]=40;
  const result=compare(a,b);
  assert.equal(result.find(r => r.key==='9:38').reference,null);
  assert.equal(result.find(r => r.key==='10:38').current.mean-result.find(r => r.key==='10:38').reference.mean,-10);
});
test('CSV quotes metadata and blocks spreadsheet formula prefixes', () => {
  const s=fixture(); s.source='=HYPERLINK("bad")'; const csv=exportCSV(s);
  assert.match(csv,/'=HYPERLINK\(""bad""\)/); assert.equal(csv.split('\r\n').length,s.events.length+1);
});
test('demo and report retain explicit measurement limits', () => {
  const s=validateSession(demoSession()); assert.equal(s.synthetic,true); assert.equal(summarize(s).hits,96);
  const text=report(s,fixture()); assert.match(text,/Synthetic demo/); assert.match(text,/cannot prove missed hits/); assert.match(text,/Comparison with/);
});
test('empty sessions do not produce NaN measurements', () => {
  const s=validateSession(newSession()); assert.deepEqual(summarize(s).notes,[]); assert.doesNotMatch(report(s),/NaN/);
});
test('repeated-note gaps cannot cross pause boundaries', () => {
  const s=fixture(); s.segments=[0,2];
  assert.equal(summarize(validateSession(s)).notes.find(n => n.channel===10).minGapMs,null);
  s.segments=[0,2,1]; assert.throws(() => validateSession(s),/pause boundaries/);
});
