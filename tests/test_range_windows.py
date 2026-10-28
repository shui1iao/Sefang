"""Bounded Range overlap on unchanged stream path, isolated only. No TG owner."""
import asyncio,json,time,unittest
from types import SimpleNamespace
from fastapi import FastAPI,HTTPException
from sefang.access import PlaybackControl
from sefang.auth import Principal,COOKIE
from sefang.streaming import router
from test_auth_accounts import StreamTests

class Store:
    maximum=1
    def authenticate(self,token):return Principal(1,'isolated','user',None,self.maximum,'session','csrf')
class Owner:
    def __init__(self,stage):
        self.media_gate=asyncio.Semaphore(2);self.stage=stage;self.enter=asyncio.Event();self.release=asyncio.Event();self.locates=0;self.opens=0
    def allowed(self,c):return True
    async def locate(self,c,m):
        self.locates+=1
        if self.locates==1 and self.stage=='locate':self.enter.set();await self.release.wait()
        return {'size':1048576,'document_id':1,'mime':'video/mp4'},None
    async def slice_at(self,row,message,base):
        self.opens+=1
        if self.opens==1 and self.stage=='opening':self.enter.set();await self.release.wait()
        return b'x'*524288

async def request(app,key,ran,body_hold=None,method='GET'):
    result={'status':None,'bytes':0,'declared':0,'exception':None}
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'method':method,'scheme':'http','path':'/api/videos/1/1/stream','raw_path':b'/api/videos/1/1/stream','query_string':('playback='+key).encode(),'headers':[(b'host',b'isolated'),(b'cookie',b'__Host-sefang_session=isolated'),(b'range',ran.encode())],'server':('isolated',0),'client':('127.0.0.1',1),'root_path':'','http_version':'1.1'}
    queue=asyncio.Queue();queue.put_nowait({'type':'http.request','body':b'','more_body':False});held=False
    async def receive():return await queue.get()
    async def send(m):
        nonlocal held
        if m['type']=='http.response.start':result['status']=m['status'];result['declared']=int(dict(m['headers']).get(b'content-length',b'0'))
        if m['type']=='http.response.body':
            result['bytes']+=len(m.get('body',b''))
            if body_hold and not held:held=True;body_hold.enter.set();await body_hold.release.wait()
    try:await app(scope,receive,send)
    except BaseException as e:result['exception']=type(e).__name__
    return result

class WindowUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlap_locate_opening_body_max_one_window(self):
        evidence=[]
        for stage in ['locate','opening','body']:
            store=Store();ctl=PlaybackControl(store);p=store.authenticate('');key=ctl.create(p,{(1,1)});owner=Owner(stage)
            app=FastAPI();app.include_router(router);app.state.playbacks=ctl;app.state.telegram=owner;app.state.config=SimpleNamespace(channels={1})
            a=asyncio.create_task(request(app,key,'bytes=0-1048575' if stage=='body' else 'bytes=0-1',owner if stage=='body' else None))
            await asyncio.wait_for(owner.enter.wait(),2)
            b=asyncio.create_task(request(app,key,'bytes=524288-524289'));await asyncio.sleep(.02)
            self.assertEqual(1,len(ctl.active));owner.release.set();left,right=await asyncio.wait_for(asyncio.gather(a,b),2)
            for r in [left,right]:self.assertEqual(206,r['status']);self.assertEqual(r['declared'],r['bytes']);self.assertIsNone(r['exception'])
            self.assertFalse(ctl.active);self.assertEqual(2,owner.media_gate._value);evidence.append({'stage':stage,'first':left,'second':right})
        print(json.dumps({'repaired_overlap':evidence,'max_playbacks':1,'response_cap':2}))

    async def test_window_cap_release_order_close_and_oldest_survival(self):
        store=Store();ctl=PlaybackControl(store);person=store.authenticate('');key=ctl.create(person,{(1,1)})
        # Distinct tasks, held outside claim, so explicit close can cancel BOTH.
        ready=asyncio.Queue()
        async def hold(k):
            t=await ctl.claim(person,(1,1),k);await ready.put(t)
            try:await asyncio.Event().wait()
            finally:ctl.release(t)
        a=asyncio.create_task(hold(key));ta=await ready.get();b=asyncio.create_task(hold(key));tb=await ready.get()
        self.assertEqual([key],ctl.windows(person));self.assertEqual(2,len(ctl.active[key]))
        for k in [key,ctl.create(person,{(1,1)}),'']:
            with self.assertRaises(HTTPException) as e:await ctl.claim(person,(1,1),k)
            self.assertEqual(429,e.exception.status_code)
        a.cancel();await asyncio.gather(a,return_exceptions=True);self.assertEqual([key],ctl.windows(person));self.assertEqual([tb],ctl.active[key]);ctl.guard('',tb)
        ctl.close(key,person);await asyncio.gather(b,return_exceptions=True);self.assertFalse(ctl.active);self.assertTrue(ta.done.is_set() and tb.done.is_set())
        store.maximum=2;person=store.authenticate('');k1=ctl.create(person,{(1,1)});k2=ctl.create(person,{(1,1)})
        a=asyncio.create_task(hold(k1));await ready.get();b=asyncio.create_task(hold(k1));await ready.get();c=asyncio.create_task(hold(k2));tc=await ready.get()
        store.maximum=1
        for t in ctl.active[k1]:ctl.guard('',t)
        with self.assertRaises(HTTPException):ctl.guard('',tc)
        for t in [a,b,c]:t.cancel()
        await asyncio.gather(a,b,c,return_exceptions=True);self.assertFalse(ctl.active)

    async def test_head_416_errors_and_disconnect_cleanup(self):
        for stage in ['none','locate','opening','body']:
            ctl=PlaybackControl(Store());p=Store().authenticate('');key=ctl.create(p,{(1,1)});owner=Owner(stage)
            app=FastAPI();app.include_router(router);app.state.playbacks=ctl;app.state.telegram=owner;app.state.config=SimpleNamespace(channels={1})
            if stage=='none':
                r=await request(app,key,'bytes=9999999-');self.assertEqual(416,r['status']);self.assertFalse(ctl.active)
                r=await request(app,key,'bytes=0-1',method='HEAD');self.assertEqual(206,r['status']);self.assertFalse(ctl.active)
            else:
                t=asyncio.create_task(request(app,key,'bytes=0-1048575',owner if stage=='body' else None));await asyncio.wait_for(owner.enter.wait(),2);t.cancel();await asyncio.gather(t,return_exceptions=True)
            self.assertFalse(ctl.active);self.assertEqual(2,owner.media_gate._value)
        # HEAD is bodyless/not an active playback window, but supplied leases
        # still have to belong to this media/session before any owner read.
        ctl=PlaybackControl(Store());p=Store().authenticate('');key=ctl.create(p,{(1,2)});owner=Owner('none')
        app=FastAPI();app.include_router(router);app.state.playbacks=ctl;app.state.telegram=owner;app.state.config=SimpleNamespace(channels={1})
        r=await request(app,key,'bytes=0-1',method='HEAD');self.assertEqual(403,r['status']);self.assertEqual(0,owner.locates)
        async def broken(*args):raise RuntimeError('isolated failure')
        for stage in ['locate','slice_at']:
            ctl=PlaybackControl(Store());key=ctl.create(p,{(1,1)});owner=Owner('none');setattr(owner,stage,broken);app.state.playbacks=ctl;app.state.telegram=owner
            r=await request(app,key,'bytes=0-1');self.assertEqual(503,r['status']);self.assertFalse(ctl.active);self.assertEqual(2,owner.media_gate._value)

class WindowSocketTests(StreamTests):
    async def test_aggregate_rate_across_window_siblings_and_other_lease(self):
        ctl=self.app.state.playbacks;p=self.store.authenticate(self.token);k=ctl.create(p,{(123,1)});other=ctl.create(p,{(123,1)})
        start=time.monotonic();results=await asyncio.gather(*[self.net.get('/api/videos/123/1/stream?playback='+key,headers={'Range':'bytes=0-2097151'}) for key in [k,k,other]])
        elapsed=time.monotonic()-start
        self.assertEqual([206]*3,[r.status_code for r in results]);self.assertEqual(6291456,sum(len(r.content) for r in results));self.assertGreaterEqual(elapsed,2.9);self.assertLess(elapsed,5)
        self.assertFalse(ctl.active);self.assertEqual(2,self.owner.media_gate._value);print(json.dumps({'shared_rate_bytes':6291456,'seconds':elapsed,'windows':2,'responses':3,'global_gate':2}))

    async def test_all_sibling_responses_revoke_logout_disable_password_close(self):
        ctl=self.app.state.playbacks
        for mode in ['close','logout','disable','password']:
            if mode=='disable':self.store.update(2,{'enabled':True})
            # previous iterations revoke only their own session; obtain a fresh one.
            token=self.store.login('fixture_user',self.password,'isolated-'+mode);self.assertIsNotNone(token);self.net.headers['Cookie']=f'{COOKIE}={token}';p=self.store.authenticate(token);key=ctl.create(p,{(123,1)})
            self.owner.block=True;old=self.owner.locates
            tasks=[asyncio.create_task(self.net.get('/api/videos/123/1/stream?playback='+key)) for _ in range(2)]
            while self.owner.locates<old+2:await asyncio.sleep(.01)
            self.assertEqual(1,len(ctl.active));self.assertEqual(2,len(ctl.active[key]))
            if mode=='close':ctl.close(key,p)
            if mode=='logout':self.store.logout(p.session)
            if mode=='disable':self.store.update(2,{'enabled':False})
            if mode=='password':self.store.update(2,{'password':self.store_hash()})
            await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),1.5)
            self.assertFalse(ctl.active);self.assertEqual(2,self.owner.media_gate._value);self.owner.block=False
            if mode=='disable':self.store.update(2,{'enabled':True})

# Reuse fixture setup only; original 11 auth tests run separately once.
for name in dir(StreamTests):
    if name.startswith('test_'):setattr(WindowSocketTests,name,None)
