import {parseJSON} from '<WORKSPACE>/public/myraft-react/frontend/src/api.ts';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
const original = text => JSON.parse(text, (_key, value, context) => typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value) ? context.source : value);
const frame = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const safe = JSON.stringify(frame);
const unsafe = safe.replace('"x":0', '"x":9223372036854775807');
const results=[];
for (const [name,text] of [['safe',safe],['unsafe',unsafe]]) {
 assert.deepEqual(parseJSON(text), original(text));
 for(let warm=0;warm<30;warm++){parseJSON(text);original(text);}
 for(let round=0;round<3;round++){
  const row={name,round,iterations:250,bytes:text.length};
  for(const [label,fn] of round%2 ? [['after',parseJSON],['before',original]] : [['before',original],['after',parseJSON]]){
   const start=performance.now();
   for(let i=0;i<250;i++)fn(text);
   row[label+'_ms']=performance.now()-start;
  }
  results.push(row);
 }
}
fs.writeFileSync(process.argv[3],JSON.stringify({mode:'NODE24_MICROBENCH',results},null,2));
console.log(results);
