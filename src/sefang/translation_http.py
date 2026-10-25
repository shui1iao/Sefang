"""Two fixed public protocols. No request URLs, text or page tokens are logged."""
import asyncio
import json
import re
import time
import httpx

GOOGLE='https://translate.googleapis.com/translate_a/single'
BING_PAGE='https://www.bing.com/translator'
BING_POST='https://www.bing.com/ttranslatev3'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
class TranslationError(Exception):
 def __init__(self,reason):self.reason=reason;super().__init__(reason)
class Providers:
 def __init__(self,control,stop=None,transport=None,interval=1.0):
  self.control=control;self.stop=stop or asyncio.Event();self.interval=interval;self.last={};self.transport=transport
 async def _wait(self,provider):
  remaining=self.interval-(time.monotonic()-self.last.get(provider,0))
  if remaining>0:
   try:await asyncio.wait_for(self.stop.wait(),remaining)
   except TimeoutError:pass
  if self.stop.is_set():raise asyncio.CancelledError
  self.last[provider]=time.monotonic()
 async def _request(self,url,*,method='GET',params=None,data=None,referer=None,page=False):
  if url not in (GOOGLE,BING_PAGE,BING_POST):raise TranslationError('fixed_host_required')
  limit=2*1048576 if page else 1048576
  try:
   async with asyncio.timeout(12):
    async with httpx.AsyncClient(follow_redirects=False,timeout=httpx.Timeout(12,connect=4),transport=self.transport,headers={'User-Agent':UA}) as client:
     async with client.stream(method,url,params=params,data=data,headers={'Referer':referer} if referer else None) as response:
      if 300<=response.status_code<400:raise TranslationError('redirect_refused')
      if response.status_code!=200:raise TranslationError('http_'+str(response.status_code))
      try:declared=int(response.headers.get('Content-Length','0'))
      except ValueError:raise TranslationError('invalid_length') from None
      if declared>limit:raise TranslationError('response_too_large')
      chunks=[];size=0
      async for chunk in response.aiter_bytes():
       if self.stop.is_set():raise asyncio.CancelledError
       size+=len(chunk)
       if size>limit:raise TranslationError('response_too_large')
       chunks.append(chunk)
      return b''.join(chunks).decode('utf-8',errors='replace')
  except TranslationError:raise
  except (TimeoutError,httpx.TimeoutException):raise TranslationError('timeout') from None
  except (httpx.HTTPError,UnicodeError,ValueError):raise TranslationError('network_or_encoding') from None
 async def translate(self,provider,text,language):
  if time.time()<float(self.control.get(provider+'_until') or 0):raise TranslationError('cooldown')
  await self._wait(provider)
  try:
   if provider=='google':
    raw=await self._request(GOOGLE,params={'client':'gtx','sl':language,'tl':'zh-CN','dt':'t','q':text})
    try:data=json.loads(raw);result=''.join(p[0] for p in data[0] if isinstance(p,list) and isinstance(p[0],str))
    except (TypeError,KeyError,IndexError,ValueError):raise TranslationError('invalid_json') from None
   elif provider=='bing':
    raw=await self._request(BING_PAGE,page=True)
    ig=re.search(r'IG:"([^"]+)"',raw);iid=re.search(r'data-iid="([^"]+)"',raw);params=re.search(r'params_AbusePreventionHelper\s*=\s*(\[[^\]]+\])',raw)
    if not ig or not iid or not params:raise TranslationError('page_tokens_or_challenge')
    try:key,token,*_=json.loads(params[1])
    except (ValueError,TypeError):raise TranslationError('page_tokens_invalid') from None
    if not isinstance(key,int) or key<=0 or not isinstance(token,str) or not 0<len(token)<=4096:raise TranslationError('page_tokens_invalid')
    raw=await self._request(BING_POST,method='POST',params={'isVertical':'1','IG':ig[1],'IID':iid[1]},data={'fromLang':'auto-detect' if language=='auto' else language,'to':'zh-Hans','text':text,'key':str(key),'token':token},referer=BING_PAGE)
    try:data=json.loads(raw);result=next(p['text'] for p in data[0]['translations'] if p.get('to')=='zh-Hans')
    except (ValueError,TypeError,KeyError,IndexError,StopIteration):raise TranslationError('invalid_json') from None
   else:raise TranslationError('fixed_provider_required')
   if not isinstance(result,str) or not result.strip():raise TranslationError('empty_result')
   return result.strip()
  except TranslationError as error:
   if error.reason in ('http_429','http_403','page_tokens_or_challenge'):self.control.set(provider+'_until',str(time.time()+300))
   raise
