"""Real Go-backed A/B classroom acceptance in independent owned sessions.

The Go controller and node binaries must be built from the intended source.
The script preserves data/evidence and stops only the controller it created.
"""
import argparse, hashlib, json, os, re, socket, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from arithmetic_reference import verify_files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dashboard',type=Path,required=True);parser.add_argument('--node',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--counts',type=int,nargs='+',default=[11,100])
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1];result={'mode':'REAL','dashboard_sha256':hashlib.sha256(args.dashboard.read_bytes()).hexdigest(),'node_sha256':hashlib.sha256(args.node.read_bytes()).hexdigest(),'runs':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        try:
            for count in args.counts:
                for renderer in ['svg','flow']:
                    folder=root/f'{renderer}-{count}';folder.mkdir();record={'nodes':count,'renderer':renderer,'result':'FAIL','views':[]};result['runs'].append(record)
                    output=(folder/'controller.txt').open('wb');env=os.environ.copy();env['GOMAXPROCS']='1'
                    controller=subprocess.Popen([str(args.dashboard.resolve()),'-listen','127.0.0.1:0','-data-root',str(folder/'sessions'),'-node-bin',str(args.node.resolve()),'-source-dir',str(repo),'-python',sys.executable,'-allow-control'],stdout=output,stderr=subprocess.STDOUT,env=env)
                    session=None;states=None;ports=[];errors=[];pages=[]
                    try:
                        deadline=time.monotonic()+15
                        while True:
                            match=re.search(r'http://127.0.0.1:\d+',(folder/'controller.txt').read_text())
                            if match:url=match[0];break
                            if controller.poll() is not None or time.monotonic()>deadline:raise RuntimeError('controller did not start')
                            time.sleep(.05)
                        api=pw.request.new_context(base_url=url)
                        def frame():return api.get('/api/snapshot').json()
                        def until(predicate,timeout=90):
                            end=time.monotonic()+timeout
                            while time.monotonic()<end:
                                current=frame()
                                if predicate(current):return current
                                time.sleep(.1)
                            raise AssertionError('timeout: '+json.dumps(frame(),ensure_ascii=False)[:2000])
                        def ids(kind):return {o['id'] for o in frame()['operations'] if o['kind']==kind}
                        def completed(kind,before,timeout=90):
                            f=until(lambda f:any(o['kind']==kind and o['id'] not in before and o.get('ended_at') for o in f['operations']),timeout)
                            op=next(o for o in reversed(f['operations']) if o['kind']==kind and o['id'] not in before)
                            (folder/f'receipt-{kind}-{op["id"]}.json').write_text(json.dumps(op,ensure_ascii=False,indent=2))
                            assert op['state']=='succeeded',op
                            return op
                        page=browser.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce');pages.append(page);page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(url+f'/prototype/?renderer={renderer}');page.get_by_label('会话操作').click();page.locator('[data-act=enable_control]').click();page.get_by_test_id('confirm').click()
                        expect(page.locator('[data-act=create_session]')).to_be_enabled(timeout=15000);page.locator('[data-act=create_session]').click();page.locator('[name=nodes]').select_option(str(count));page.locator('[name=name]').fill(f'真实 {count} 节点 · {renderer}');page.get_by_test_id('confirm').click()
                        until(lambda f:len(f['snapshot']['nodes'] or [])==count and all(n['reachable'] for n in f['snapshot']['nodes']) and sum(n.get('status',{}).get('state')=='Leader' for n in f['snapshot']['nodes'] if n.get('status'))==1 and not f['busy'])
                        session=frame()['session'];ports=[int(n['addr'].rsplit(':',1)[1]) for n in session['config']['nodes']]
                        before=ids('generate');page.locator('[data-act=generate]').click();page.get_by_test_id('confirm').dblclick();op=completed('generate',before)
                        assert op['accepted'] is True and op['committed'] is True
                        assert len(ids('generate')-before)==1
                        until(lambda f:all(n.get('status') and n['status']['applied_commands']==2101 for n in f['snapshot']['nodes']))
                        before=ids('verify');page.locator('[data-act=verify]').first.click();completed('verify',before)
                        page.get_by_label('一致性证据',exact=True).click();before=ids('checkpoint');page.locator('[data-act=checkpoint]').click();completed('checkpoint',before);checkpoint=frame()['checkpoint'];record['checkpoint']=checkpoint
                        page.screenshot(path=str(folder/'evidence.png'));page.get_by_label('关闭证据').click()
                        for width,height in [(1440,900),(1920,1080),(390,844)]:
                            page.set_viewport_size({'width':width,'height':height});page.mouse.move(0,0)
                            page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n&&document.querySelectorAll("[data-relation]").length===n-1',arg=count)
                            page.wait_for_timeout(150);page.screenshot(path=str(folder/f'overview-{width}.png'))
                            stats=page.locator('[data-node]').evaluate_all('''ns=>({members:ns.length,hit:ns.filter(n=>{const r=n.getBoundingClientRect();return n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}).length})''')
                            assert stats['hit']==count,stats;record['views'].append({'viewport':[width,height],**stats})
                            page.get_by_label('搜索节点').fill(str(count));page.get_by_label('搜索节点').press('Enter');page.get_by_label(f'节点 {count} 详情').wait_for();page.screenshot(path=str(folder/f'focus-{width}.png'))
                            page.get_by_label('关闭节点详情').click();page.keyboard.press('Escape');page.get_by_label('返回全景').click()
                        page.set_viewport_size({'width':1440,'height':900});page.wait_for_timeout(100)
                        leader=next(n['id'] for n in frame()['snapshot']['nodes'] if n.get('status',{}).get('state')=='Leader');record['old_leader']=leader
                        page.locator(f'[data-node="{leader}"]').click();page.locator('[data-act=stop]').click();page.get_by_role('button',name='取消',exact=True).click()
                        assert all(n['reachable'] for n in frame()['snapshot']['nodes'])
                        before=ids('stop');page.locator('[data-act=stop]').click();begin=time.monotonic();page.get_by_test_id('confirm').click();completed('stop',before)
                        elected=until(lambda f:any(n.get('status') and n['status']['state']=='Leader' and n['id']!=leader for n in f['snapshot']['nodes']) and not f['busy'])
                        record['failover_seconds']=time.monotonic()-begin;record['new_leader']=next(n['id'] for n in elected['snapshot']['nodes'] if n.get('status') and n['status']['state']=='Leader' and n['id']!=leader)
                        page.screenshot(path=str(folder/'failover.png'))
                        before=ids('generate');page.locator('[data-act=generate]').click();page.locator('[name=count]').fill('3');page.locator('[name=seed]').fill('43');page.get_by_test_id('confirm').click();assert completed('generate',before)['committed'] is True
                        before=ids('restart');page.locator('[data-act=restart]').click();completed('restart',before)
                        until(lambda f:all(n.get('status') and n['status']['applied_commands']==2104 for n in f['snapshot']['nodes']))
                        page.get_by_label('一致性证据',exact=True).click();before=ids('verify_history');page.locator('[data-act=verify_history]').click();history=completed('verify_history',before)
                        assert all(n['target_index']==checkpoint['index'] and n['target_hash']==checkpoint['hash'] and n['target_x']==checkpoint['x'] for n in history['result']['nodes'])
                        assert frame()['checkpoint']==checkpoint
                        before=ids('verify');page.locator('[data-act=verify]').first.click();verification=completed('verify',before)
                        states=verification['result']['nodes'] if 'nodes' in verification.get('result',{}) else None
                        record['final_frame']=frame();record['history_preserved']=True
                        page.screenshot(path=str(folder/'restored-history.png'))
                        before=ids('export');page.locator('[data-act=export]').click();export=completed('export',before);body=api.get(export['result']['url']).body();assert hashlib.sha256(body).hexdigest()==export['result']['sha256'];(folder/'evidence.zip').write_bytes(body)
                        # Both renderers use the existing shared collector; subscriber count is varied, not poll frequency.
                        record['monitoring']=[]
                        previous=frame()['snapshot'];stable=0
                        for _ in range(15):
                            current=until(lambda f:f['snapshot']['seq']>previous['seq'])['snapshot']
                            stable=stable+1 if current['monitor_rpcs']-previous['monitor_rpcs']==count*(current['seq']-previous['seq']) else 0;previous=current
                            if stable>=2:break
                        assert stable>=2
                        for subscribers in [1,5,10]:
                            while len(pages)<subscribers:
                                tab=browser.new_page();tab.goto(url+f'/prototype/?renderer={renderer}');pages.append(tab)
                            first=frame()['snapshot'];last=until(lambda f:f['snapshot']['seq']>=first['seq']+3)['snapshot'];rounds=last['seq']-first['seq'];rpcs=last['monitor_rpcs']-first['monitor_rpcs']
                            assert rpcs==count*rounds,(rounds,rpcs)
                            record['monitoring'].append({'browsers':subscribers,'rounds':rounds,'monitor_rpcs':rpcs})
                        assert not errors,errors;record.update(result='PASS',page_errors=errors)
                    except Exception as error:
                        record['error']=f'{type(error).__name__}: {error}';raise
                    finally:
                        for page in pages:page.close()
                        controller.terminate()
                        try:controller.wait(timeout=20)
                        except subprocess.TimeoutExpired:controller.kill();controller.wait(timeout=5)
                        output.close();listening=[]
                        for port in ports:
                            with socket.socket() as sock:
                                sock.settimeout(.1)
                                if sock.connect_ex(('127.0.0.1',port))==0:listening.append(port)
                        record['remaining_listeners']=listening
                        if session and record.get('result')=='PASS':
                            # Summary snapshots omit full hashes. Obtain the complete verified states from the operation result.
                            if states:
                                arithmetic=verify_files(folder/'sessions'/session['id']/'data',states);record['arithmetic_nodes']=len(arithmetic)
                                (folder/'arithmetic-reference.json').write_text(json.dumps(arithmetic,ensure_ascii=False,indent=2))
                        (root/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                        assert not listening,listening
        finally:browser.close()
    print(json.dumps({'runs':[{k:r.get(k) for k in ['nodes','renderer','result','arithmetic_nodes','remaining_listeners']} for r in result['runs']]}))


if __name__=='__main__':main()
