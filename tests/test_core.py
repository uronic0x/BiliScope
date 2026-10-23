from __future__ import annotations
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from biliscope.runtime import ROOT,RUNTIME,inside,redact,remember_secret,path_report
from biliscope.domain import AppError,Mention,Evidence,parse_video,sample_times,validate_times,wbi_query,comment_payload
from biliscope.config import Settings
from biliscope.llm import Client,endpoint

class InputTests(unittest.TestCase):
    def test_video_url_and_parts(self):
        self.assertEqual(parse_video('BV1xx411c7mD'),('BV1xx411c7mD',1))
        self.assertEqual(parse_video('https://www.bilibili.com/video/BV1xx411c7mD/?p=3'),('BV1xx411c7mD',3))
        for value in ['http://www.bilibili.com/video/BV1xx411c7mD','https://bilibili.com.evil.test/video/BV1xx411c7mD',
          'https://user@www.bilibili.com/video/BV1xx411c7mD','file:///etc/passwd','https://www.bilibili.com:444/video/BV1xx411c7mD',
          'https://www.bilibili.com/video/BV1xx411c7mD?p=-1']:
            with self.assertRaises(AppError):parse_video(value)

    def test_frame_budget(self):
        self.assertEqual(sample_times(0,4),[])
        self.assertEqual(len(sample_times(120,4)),4)
        for values in [[float('nan')],[float('inf')],[True],[-1],[60],[1,2,3]]:
            with self.assertRaises(AppError):validate_times(values,60,2)
        self.assertEqual(validate_times([1,1],60,2),[1.0])

    def test_wbi_reference_vector(self):
        q=wbi_query({'foo':'114','bar':'514','zab':1919810},'7cd084941338484aae1ad9425b84077c','4932caff0ff746eab6f01bf08b70ac45',1702204169)
        self.assertEqual(q,'bar=514&foo=114&wts=1702204169&zab=1919810&w_rid=8f6f2b5b3d485fe1886cec6a0be8c5d4')

    def test_wbi_unicode_percent_encoding(self):
        q=wbi_query({'foo':'one one four','bar':'五一四'},'7cd084941338484aae1ad9425b84077c','4932caff0ff746eab6f01bf08b70ac45',1702204169)
        self.assertTrue(q.startswith('bar=%E4%BA%94%E4%B8%80%E5%9B%9B&foo=one%20one%20four&'))

    def test_comment_explicit_uid_mapping(self):
        form=comment_payload(42,'A grounded comment',[Mention('123','用户甲')],'secret',100,101)
        self.assertEqual(form['message'],'@用户甲 A grounded comment')
        self.assertEqual(json.loads(form['at_name_to_mid']),{'用户甲':123})
        self.assertEqual((form['root'],form['parent']),('100','101'))
        for mentions in [[Mention('1','A'),Mention('2','A')],[Mention('1','A'),Mention('1','B')]]:
            with self.assertRaises(AppError):comment_payload(1,'x',mentions,'s')
        with self.assertRaises(AppError):comment_payload(1,'x',[],'s',0,1)
        with self.assertRaises(AppError):comment_payload(1,'x'*1001,[],'s')

    def test_api_url_policy(self):
        for url in ['https://api.deepseek.com','http://127.0.0.1:9999/v1']:
            Settings(base_url=url).validate()
        for url in ['http://example.com','https://key@example.com','https://example.com?api_key=x']:
            with self.assertRaises(ValueError):Settings(base_url=url).validate()
        self.assertEqual(endpoint('https://example.test/v1/'),'https://example.test/v1/chat/completions')

class ContainmentTests(unittest.TestCase):
    def test_env_paths_and_tempfile(self):
        r=path_report()
        self.assertTrue(r['python_write_guard'])
        self.assertTrue(all(x['inside_project'] for x in r['paths'].values()))
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(Path(d).resolve().is_relative_to(ROOT))

    def test_outside_writes_and_symlinks_denied(self):
        outside=ROOT.parent/'outside-guard-probe.txt'
        self.assertFalse(outside.exists())
        with self.assertRaises(PermissionError):outside.write_text('blocked')
        self.assertFalse(outside.exists())
        with self.assertRaises(PermissionError):inside(ROOT/'..'/'escape.txt')
        with self.assertRaises(PermissionError):os.symlink(str(ROOT.parent),str(RUNTIME/'escape-link'))

    def test_redaction(self):
        remember_secret('secret-example-012345')
        text=redact('secret-example-012345 Bearer other-secret SESSDATA=cookievalue bili_jct=token https://x.test/a?token=signed')
        for value in ('secret-example-012345','other-secret','cookievalue','signed'):
            self.assertNotIn(value,text)

    def test_fresh_process_hostile_paths(self):
        env=os.environ.copy()
        for key in ('TMP','TEMP','TMPDIR','APPDATA','LOCALAPPDATA','PIP_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH'):
            env[key]=str(ROOT.parent/'must-not-write')
        cmd=[sys.executable,'-I','-B',str(ROOT/'main.py'),'--doctor']
        p=subprocess.run(cmd,cwd=ROOT.parent,env=env,capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        report=json.loads(p.stdout)
        self.assertTrue(all(x['inside_project'] for x in report['paths'].values()))
        self.assertFalse((ROOT.parent/'must-not-write').exists())

class ProviderTests(unittest.TestCase):
    def test_text_model_does_not_receive_images(self):
        ev=Evidence('BV1xx411c7mD',1,1,2,'t','a',60,60,transcript=[{'from':0,'to':5,'content':'fact'}])
        ev.frames=[{'path':'does-not-exist.png','actual_s':1,'requested_s':1}]
        messages=Client(Settings(vision=False),'key').messages(ev,'question')
        self.assertIsInstance(messages[-1]['content'],str)
        self.assertIn('fact',messages[-1]['content'])

    def test_http_payload_and_no_secret_error_echo(self):
        import io
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*_):self.close()
        client=Client(Settings(vision=False),'test-api-key')
        seen=[]
        def open_request(req,timeout):
            seen.append(json.loads(req.data))
            return Response(json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'ok','reasoning_content':'discard'}}]}).encode())
        with patch.object(client.opener,'open',side_effect=open_request):
            reply=client.complete([{'role':'user','content':'hello'}],tools=True)
        self.assertEqual(reply,{'role':'assistant','content':'ok'})
        self.assertEqual(seen[0]['tools'][0]['function']['name'],'capture_frames')
        self.assertNotIn('publish',json.dumps(seen[0]))
        self.assertNotIn('thinking',seen[0])
        self.assertNotIn('reasoning_effort',seen[0])

    def test_truncation_not_saved_as_complete(self):
        import io
        client=Client(Settings(),'test-api-key')
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*_):self.close()
        with patch.object(client.opener,'open',return_value=Response(b'{"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}')):
            with self.assertRaises(AppError) as error:client.complete([])
        self.assertEqual(error.exception.code,'API_TRUNCATED')

class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_level_reply_root_zero_is_normalized(self):
        from biliscope.browser import Browser
        browser=Browser()
        async def api(*_,**__):
            return {'replies':[{'rpid':100,'rpid_str':'100','root':0,'root_str':'0',
                 'member':{'mid':'2','uname':'User'},'content':{'message':'hello'}}]}
        browser.api=api
        ev=Evidence('BV1xx411c7mD',1,42,43,'title','author',30,30)
        comments=await browser.comments(ev)
        self.assertEqual(comments[0]['root'],'100')
        form=comment_payload(ev.aid,'reply',[],'test',int(comments[0]['root']),int(comments[0]['rpid']))
        self.assertEqual((form['root'],form['parent']),('100','100'))

    async def test_no_automatic_retry_after_unknown_publish(self):
        from biliscope.browser import Browser
        b=Browser()
        class Context:
            async def cookies(self,*_):return [{'name':'bili_jct','value':'csrf-test'}]
            class Request:
                calls=0
                async def post(self,*_,**kw):
                    self.calls+=1
                    raise TimeoutError()
            request=Request()
        b.context=Context()
        async def api(*_,**__):return {'isLogin':True}
        b.api=api
        ev=Evidence('BV1xx411c7mD',1,42,43,'title','author',30,30)
        with self.assertRaises(AppError) as error:await b.publish(ev,'comment',[])
        self.assertEqual(error.exception.code,'POST_UNKNOWN')
        with self.assertRaises(AppError) as error:await b.publish(ev,'comment',[])
        self.assertEqual(error.exception.code,'COMMENT_DUPLICATE')
        self.assertEqual(b.context.request.calls,1)

if __name__=='__main__':unittest.main()

class ArchiveTests(unittest.TestCase):
    def test_chromium_archive_rejects_traversal_and_links(self):
        import stat,zipfile
        from biliscope.browser_install import safe_extract
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=root/'bad.zip'
            for filename in ('../escape.txt','/absolute.txt','C:/absolute.txt'):
                with zipfile.ZipFile(archive,'w') as z:z.writestr(filename,'blocked')
                with self.assertRaises(AppError):safe_extract(archive,root/'out')
            with zipfile.ZipFile(archive,'w') as z:
                item=zipfile.ZipInfo('chrome-win/link')
                item.create_system=3;item.external_attr=(stat.S_IFLNK|0o777)<<16
                z.writestr(item,'../../outside')
            with self.assertRaises(AppError):safe_extract(archive,root/'out')
