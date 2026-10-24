import sys,json
from pathlib import Path
sys.path.insert(0,'scripts')
import phase234_performance as probe
probe.SETUP='frame=>{('+probe.SETUP+')(frame);window.__send=()=>{};}'
sys.argv=['probe','--url','http://127.0.0.1:18151','--output',sys.argv[1]]
try:
 probe.main()
except Exception as error:
 assert 'Commit KPI did not match update' in str(error), str(error)
 print('PASS: a no-op SSE update is rejected by the performance harness')
else:
 raise AssertionError('No-op SSE was incorrectly accepted')
