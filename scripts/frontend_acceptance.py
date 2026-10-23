"""Real clusters and Chromium at three viewports; isolated evidence, no remote writes.
Requires prebuilt executables and optional Playwright. Run dashboard_e2e.py as well
for the managed-session classroom workflow and all six workspaces.
"""
import argparse,hashlib,json,os,re,socket,subprocess,time
from pathlib import Path
from playwright.sync_api import sync_playwright
import benchmark as b
from arithmetic_reference import verify_files


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dashboard',type=Path,required=True);p.add_argument('--node',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--nodes',type=int,nargs='+',default=[3,11,20,50,100])
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    b.EXE=a.node.resolve();exe=a.dashboard.resolve()
    result={'mode':'REAL','platform':os.name,'dashboard_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'node_sha256':hashlib.sha256(b.EXE.read_bytes()).hexdigest(),'runs':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        try:
            for count in a.nodes:
                folder=root/f'n{count}';c=b.Cluster(count,folder,90);controller=None;log=None
                record={'nodes':count,'result':'FAIL'};result['runs'].append(record)
                try:
                    for n in c.nodes:c.start(n['id'])
                    leader,_,_=c.wait();reply=c.generate(2101,42)
                    leader,states,_=c.wait(logs=True,commands=2101)
                    checkpoint=b.save_checkpoint(folder,states[0]);record['checkpoint']=checkpoint
                    log=(folder/'controller.txt').open('wb')
                    controller=subprocess.Popen([str(exe),'-listen','127.0.0.1:0','-config',str(c.config),'-data-root',str(folder/'console')],stdout=log,stderr=subprocess.STDOUT)
                    deadline=time.monotonic()+15
                    while True:
                        match=re.search(r'http://127.0.0.1:\d+',(folder/'controller.txt').read_text())
                        if match:url=match[0];break
                        if controller.poll() is not None or time.monotonic()>deadline:raise RuntimeError('controller did not start')
                        time.sleep(.05)
                    errors=[];views=[]
                    for width,height in [(1440,900),(1920,1080),(390,844)]:
                        context=browser.new_context(viewport={'width':width,'height':height},has_touch=width==390,reduced_motion='reduce')
                        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));page.goto(url)
                        page.wait_for_function('(n)=>document.querySelectorAll(".stage-node").length===n && document.querySelectorAll(".stage-node.center-slot.leader").length===1 && document.querySelectorAll(".stage-reported-edge").length===n-1',arg=count,timeout=30000)
                        seen=set();groups=[]
                        while True:
                            stats=page.locator('.stage-node:visible').evaluate_all("""ns=>({ids:ns.map(n=>Number(n.dataset.node)),visible:ns.filter(n=>{const r=n.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight}).length,blocked:ns.filter(n=>{const r=n.getBoundingClientRect();return !n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}).map(n=>n.dataset.node)})""")
                            assert stats['visible']==len(stats['ids']) and not stats['blocked'],stats
                            seen.update(stats['ids']);groups.append(stats)
                            nxt=page.locator('[aria-label="下一组"]')
                            if not nxt.is_visible() or nxt.is_disabled():break
                            nxt.click()
                        assert seen==set(range(1,count+1)),seen
                        prev=page.locator('[aria-label="上一组"]')
                        while prev.is_visible() and prev.is_enabled():prev.click()
                        stats={'visible_members_across_groups':len(seen),'groups':groups}
                        page.mouse.move(width-1,1);page.screenshot(path=str(folder/f'overview-{width}.png'))
                        page.locator('[aria-label="按可读大小聚焦节点"]').click()
                        assert page.locator('.stage-node.center-slot').bounding_box()['width']>=90
                        assert page.locator('.stage-orientation').is_visible()
                        page.screenshot(path=str(folder/f'focused-{width}.png'))
                        page.locator('.stage-orientation').click()
                        stats.update(viewport=[width,height]);views.append(stats);context.close()
                    context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce');page=context.new_page();page.goto(url)
                    page.wait_for_function('id=>document.querySelector(".stage-node.center-slot.leader")?.dataset.node===String(id)',arg=leader['id'])
                    before=page.locator('.stage-node').evaluate_all('ns=>Object.fromEntries(ns.map(n=>[n.dataset.node,[n.style.left,n.style.top]]))')
                    old=leader['id'];c.stop(old);new,_,_=c.wait();assert new['id']!=old and new['term']>leader['term']
                    page.wait_for_function('id=>document.querySelector(".stage-node.center-slot.leader")?.dataset.node===String(id)',arg=new['id'],timeout=30000)
                    after=page.locator('.stage-node').evaluate_all('ns=>Object.fromEntries(ns.map(n=>[n.dataset.node,[n.style.left,n.style.top]]))')
                    assert all(before[k]==after[k] for k in before if int(k) not in [old,new['id']]),'unrelated slots moved'
                    page.screenshot(path=str(folder/'failover.png'));c.generate(3,43);c.start(old)
                    _,states,_=c.wait(logs=True,target=checkpoint['index'],commands=2104,checkpoint=checkpoint)
                    page.wait_for_function('n=>document.querySelectorAll(".stage-node.follower").length===n-1',arg=count,timeout=30000)
                    page.screenshot(path=str(folder/'recovered.png'));context.close()
                    arithmetic=verify_files(folder/'data',states);(folder/'arithmetic-reference.json').write_text(json.dumps(arithmetic,indent=2))
                    assert not errors,errors
                    record.update(result='PASS',commands=2104,views=views,page_errors=errors,initial_leader=old,new_leader=new['id'],history_preserved=True)
                except Exception as error:
                    record['error']=f'{type(error).__name__}: {error}';raise
                finally:
                    if controller:
                        controller.terminate()
                        try:controller.wait(timeout=15)
                        except subprocess.TimeoutExpired:controller.kill();controller.wait(timeout=5)
                    if log:log.close()
                    c.close();record['owned_nodes_remaining']=len(c.processes)
                    listening=[]
                    for node in c.nodes:
                        host,port=node['addr'].rsplit(':',1)
                        with socket.socket() as probe:
                            probe.settimeout(.1)
                            if probe.connect_ex((host,int(port)))==0:listening.append(node['id'])
                    record['remaining_listeners']=listening
                    (root/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                    assert not c.processes and not listening
        finally:browser.close()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
