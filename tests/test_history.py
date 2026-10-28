"""Own-only HTTP history, stub snapshot only; no Telegram network or real data."""
import json
from pathlib import Path
import secrets
import tempfile
from types import SimpleNamespace
import unittest

import httpx
from sefang.app import create_app
from sefang.auth import COOKIE
from sefang.config import Config
from sefang.grouping import PlaybackGroup
from sefang.tg.index import ChannelIndex


def row(mid,duration=120,available=True):
    return dict(channel_id=123,message_id=mid,title='Neutral demo '+str(mid),duration=duration,available=available)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='history-test-')
        root=Path(self.temp.name);ChannelIndex(root/'database/telegram/index.db')
        self.app=create_app(Config(root,root/'side',(123,),True))
        self.store=self.app.state.auth
        self.password=secrets.token_urlsafe(18)
        self.store.bootstrap('fixture_admin',self.password,2)
        self.store.create('fixture_alice',self.password,2097152,1)
        self.store.create('fixture_bob',self.password,2097152,1)
        self.people={}
        for name in ('fixture_admin','fixture_alice','fixture_bob'):
            token=self.store.login(name,self.password,name)
            person=self.store.authenticate(token)
            self.people[name]={'Cookie':COOKIE+'='+token,'Origin':'https://test','X-CSRF-Token':person.csrf}
        self.headers=self.people['fixture_alice']
        self.parts=(row(1),row(2,150));alias=row(11)
        self.group=PlaybackGroup('gtest','confirmed',(),self.parts,(1,2),((self.parts[0],alias),(self.parts[1],)))
        self.repo=self.app.state.repository
        self.repo.snapshot=lambda: SimpleNamespace(by_message={key:self.group for key in self.group.keys})
        self.repo.card=lambda group: {'title':'Neutral work','cover':'/unavailable'}
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://test')

    async def asyncTearDown(self):
        await self.client.aclose();self.repo.close();self.temp.cleanup()

    async def post(self,path,body,headers=None):
        return await self.client.post(path,json=body,headers=headers or self.headers)

    async def listing(self,headers=None,query=''):
        response=await self.client.get('/api/history'+query,headers=headers or self.headers)
        self.assertEqual(response.status_code,200)
        return response.json()

    async def context(self,mid=1,headers=None):
        response=await self.post('/api/history/context',{'channel_id':123,'message_id':mid},headers)
        self.assertEqual(200,response.status_code)
        return response.json()['context']

    def payload(self,key,mid=1,sequence=1,event='playing',**patch):
        return dict(context=key,channel_id=123,message_id=mid,sequence=sequence,event=event,position=12.5,duration=120.,**patch)

    async def test_unauthorized_csrf_json_and_private_storage(self):
        for method,path in [('GET','/api/history'),('HEAD','/api/history'),('POST','/api/history/context'),('POST','/api/history/clear')]:
            r=await self.client.request(method,path,json={} if method=='POST' else None)
            self.assertEqual(401,r.status_code);self.assertIn('no-store',r.headers['cache-control'])
        self.assertEqual(303,(await self.client.get('/history')).status_code)
        for path in ('/state/history/history.sqlite3','/assets/../state/history/history.sqlite3'):
            self.assertNotEqual(200,(await self.client.get(path,headers=self.headers)).status_code)
        self.assertEqual(403,(await self.post('/api/history/clear',{},dict(self.headers,Origin='https://evil'))).status_code)
        h={k:v for k,v in self.headers.items() if k!='X-CSRF-Token'}
        self.assertEqual(403,(await self.post('/api/history/clear',{},h)).status_code)
        self.assertEqual(415,(await self.client.post('/api/history/clear',headers=dict(self.headers,**{'Content-Type':'text/plain'}),content='{}')).status_code)
        self.assertEqual(422,(await self.post('/api/history/clear',{'account_id':99})).status_code)
        self.assertEqual(0o700,self.app.state.history.path.parent.stat().st_mode&0o777)
        self.assertEqual(0o600,self.app.state.history.path.stat().st_mode&0o777)

    async def test_context_no_viewing_and_first_playing_only(self):
        key=await self.context()
        self.assertEqual(0,(await self.listing())['total'])
        for event in ('pause','seeked','progress','ended','final'):
            self.assertEqual(409,(await self.post('/api/history/progress',self.payload(key,event=event))).status_code)
        self.assertEqual(200,(await self.post('/api/history/progress',self.payload(key))).status_code)
        self.assertEqual(1,(await self.listing())['total'])

    async def test_cross_account_admin_and_forged_fields(self):
        key=await self.context();await self.post('/api/history/progress',self.payload(key))
        ident=(await self.listing())['items'][0]['id']
        for name in ('fixture_bob','fixture_admin'):
            h=self.people[name]
            self.assertEqual(0,(await self.listing(h))['total'])
            self.assertEqual(404,(await self.client.get(f'/api/history/{ident}/resume',headers=h)).status_code)
            self.assertEqual(404,(await self.post(f'/api/history/{ident}/delete',{},h)).status_code)
            self.assertEqual(409,(await self.post('/api/history/progress',self.payload(key),h)).status_code)
            await self.post('/api/history/clear',{},h)
        for field in ('account_id','username','role','work_id'):
            body=self.payload(key);body[field]='other'
            self.assertEqual(422,(await self.post('/api/history/progress',body)).status_code)
        self.assertEqual(1,(await self.listing())['total'])

    async def test_validation_bad_positions_parts_and_alias(self):
        key=await self.context()
        for change in ({'position':-1},{'position':121.1},{'duration':0},{'duration':-1},{'duration':172801},{'position':'NaN'},{'position':'Infinity'},{'channel_id':124},{'message_id':888}):
            p=self.payload(key);p.update(change)
            self.assertIn((await self.post('/api/history/progress',p)).status_code,(404,422))
        p=self.payload(key);p['position']=float('nan')
        r=await self.client.post('/api/history/progress',content=json.dumps(p),headers=dict(self.headers,**{'Content-Type':'application/json'}))
        self.assertEqual(422,r.status_code)
        self.assertEqual(200,(await self.post('/api/history/progress',self.payload(key,mid=11))).status_code)
        self.assertEqual(1,(await self.listing())['total'])

    async def test_ordering_parts_and_safe_resume(self):
        key=await self.context()
        await self.post('/api/history/progress',self.payload(key))
        p=self.payload(key,mid=2,sequence=3);p.update(position=41.,duration=150.)
        await self.post('/api/history/progress',p)
        await self.post('/api/history/progress',self.payload(key,sequence=2,event='final'))
        listing=await self.listing();self.assertEqual(1,listing['total']);item=listing['items'][0]
        self.assertEqual(2,item['part_number']);self.assertEqual(41,item['position'])
        r=await self.client.get(f"/api/history/{item['id']}/resume",headers=self.headers)
        self.assertEqual(2,r.json()['message_id']);self.assertEqual(41,r.json()['position'])
        p.update(sequence=4,event='ended',position=150.)
        await self.post('/api/history/progress',p)
        r=await self.client.get(f"/api/history/{item['id']}/resume",headers=self.headers)
        self.assertEqual(0,r.json()['position']);self.assertIn('已看完',r.json()['note'])
        self.parts[1]['available']=False
        r=await self.client.get(f"/api/history/{item['id']}/resume",headers=self.headers)
        self.assertEqual(1,r.json()['message_id']);self.assertEqual(0,r.json()['position'])
        self.repo.snapshot=lambda:SimpleNamespace(by_message={})
        item=(await self.listing())['items'][0];self.assertFalse(item['available']);self.assertEqual(1,(await self.listing())['total'])
        self.assertEqual(404,(await self.client.get(f"/api/history/{item['id']}/resume",headers=self.headers)).status_code)
        self.assertEqual(200,(await self.post(f"/api/history/{item['id']}/delete",{})).status_code)

    async def test_delete_clear_barrier_persistent_and_new_playback(self):
        key=await self.context();await self.post('/api/history/progress',self.payload(key))
        ident=(await self.listing())['items'][0]['id']
        await self.post(f'/api/history/{ident}/delete',{})
        self.assertEqual(409,(await self.post('/api/history/progress',self.payload(key,sequence=10,event='final'))).status_code)
        self.assertEqual(0,(await self.listing())['total'])
        fresh=await self.context();await self.post('/api/history/progress',self.payload(fresh))
        self.assertEqual(1,(await self.listing())['total'])
        await self.post('/api/history/clear',{})
        self.assertEqual(409,(await self.post('/api/history/progress',self.payload(fresh,sequence=12,event='pause'))).status_code)
        self.assertEqual(0,(await self.listing())['total'])
        with self.app.state.history.db() as db:
            self.assertEqual(1,db.execute('SELECT count(*) FROM deletions').fetchone()[0]);self.assertEqual(1,db.execute('SELECT version FROM generations').fetchone()[0])

    async def test_retention_pagination_no_implicit_cap(self):
        with self.app.state.history.db() as db:
            for n in range(73):
                db.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(f'{n:032x}',2,'work'+str(n),123,1,123,1,1,120,0,'Neutral',n))
        a=await self.listing(query='?page=1&limit=24');b=await self.listing(query='?page=4&limit=24')
        self.assertEqual(73,a['total']);self.assertEqual(4,a['pages']);self.assertEqual(24,len(a['items']));self.assertEqual(1,len(b['items']))
        self.assertEqual(72,int(a['items'][0]['id'],16));self.assertEqual(0,int(b['items'][0]['id'],16))

    async def test_new_session_cannot_use_old_writer_and_restart_preserves_entries(self):
        key=await self.context();await self.post('/api/history/progress',self.payload(key))
        old=self.store.authenticate(self.headers['Cookie'].split('=',1)[1])
        self.store.logout(old.session)
        token=self.store.login('fixture_alice',self.password,'new-login')
        person=self.store.authenticate(token)
        headers={'Cookie':COOKIE+'='+token,'Origin':'https://test','X-CSRF-Token':person.csrf}
        self.assertEqual(409,(await self.post('/api/history/progress',self.payload(key,sequence=5),headers)).status_code)
        from sefang.history import HistoryStore
        restarted=HistoryStore(self.app.state.history.path)
        self.assertEqual(1,restarted.page(person.id,1,24)['total'])

    async def test_late_old_context_cannot_overwrite_newer_player_part(self):
        old=await self.context()
        new=await self.context()
        p=self.payload(new,mid=2);p.update(position=44.,duration=150.)
        self.assertEqual(200,(await self.post('/api/history/progress',p)).status_code)
        self.assertEqual(409,(await self.post('/api/history/progress',self.payload(old))).status_code)
        item=(await self.listing())['items'][0]
        self.assertEqual(2,item['part_number']);self.assertEqual(44,item['position'])
