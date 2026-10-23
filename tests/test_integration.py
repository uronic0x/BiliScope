from __future__ import annotations
import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from biliscope.runtime import ROOT,RUNTIME,inside
from biliscope.domain import Evidence,AppError
from biliscope.config import Settings


def make_clip():
    import av,numpy as np
    path=inside(RUNTIME/'tmp'/'fixture-colors.webm')
    with av.open(str(path),'w') as out:
        stream=out.add_stream('libvpx',rate=10);stream.width=160;stream.height=96;stream.pix_fmt='yuv420p'
        for i in range(60):
            image=np.zeros((96,160,3),dtype=np.uint8)
            image[:]=[(230,20,20),(20,230,20),(20,20,230)][i//20]
            for packet in stream.encode(av.VideoFrame.from_ndarray(image,format='rgb24')):out.mux(packet)
        for packet in stream.encode():out.mux(packet)
    return path

class NativeVideoTests(unittest.TestCase):
    def test_frame_time_and_pixels_from_real_encoded_video(self):
        from biliscope.browser import Browser
        import av
        path=make_clip()
        ev=Evidence('BV1xx411c7mD',1,1,2,'fixture','fixture',6,6)
        frame=Browser._decode_frame(path,ev,2.5)
        self.assertAlmostEqual(frame['actual_s'],2.5,places=1)
        with av.open(str(ROOT/frame['path'])) as container:
            mean=next(container.decode(video=0)).to_ndarray(format='rgb24').mean(axis=(0,1))
        self.assertGreater(mean[1],200)
        self.assertLess(mean[0],40)
        self.assertLess(mean[2],40)

class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_seek_and_decoded_pixels_without_network(self):
        try:
            from biliscope.browser_install import executable
            exe=executable()
        except AppError:self.skipTest('Run bootstrap.py to install Chromium')
        from patchright.async_api import async_playwright
        from biliscope.browser import Browser
        import av
        clip=make_clip().read_bytes()
        ev=Evidence('BV1xx411c7mD',1,1,2,'fixture','fixture',6,6)
        async with async_playwright() as p:
            # This CI container runs as root; sandbox is disabled ONLY in this
            # local-fixture test. The shipped Windows app enables the sandbox.
            try:
                context=await p.chromium.launch_persistent_context(
                str(inside(RUNTIME/'qa-browser-profile')),executable_path=str(exe),
                headless=True,chromium_sandbox=False,viewport={'width':800,'height':600},
                downloads_path=str(RUNTIME/'downloads'),
                args=['--disable-dev-shm-usage','--disable-background-networking','--disable-component-update',
                      '--disable-breakpad','--disable-crash-reporter',
                      '--crash-dumps-dir='+str(RUNTIME/'logs'/'qa-crashes')])
            except Exception as e:
                if 'Unable to resolve /proc/self/exe' in str(e):
                    self.skipTest('Host sandbox does not expose /proc/self/exe; real Chromium launch blocked')
                raise
            requests=[]
            async def serve(route):
                requests.append(route.request.url)
                if route.request.url.startswith('https://www.bilibili.com/fixture.webm'):
                    await route.fulfill(status=200,body=clip,content_type='video/webm')
                elif route.request.url.startswith('https://www.bilibili.com/video/'):
                    await route.fulfill(status=200,body='<html><video muted controls preload="auto" src="/fixture.webm" style="width:640px;height:384px"></video></html>',content_type='text/html')
                else:await route.abort()
            await context.route('**/*',serve)
            page=await context.new_page()
            await page.goto(ev.url)
            b=Browser();b.context=context;b.page=page
            try:
                frame=await b._browser_frame(ev,2.5)
                self.assertAlmostEqual(frame['actual_s'],2.5,places=1)
                with av.open(str(ROOT/frame['path'])) as container:
                    mean=next(container.decode(video=0)).to_ndarray(format='rgb24').mean(axis=(0,1))
                self.assertGreater(mean[1],200)
                self.assertLess(mean[0],45)
                self.assertTrue(all(u.startswith('https://www.bilibili.com/') for u in requests))
            finally:await context.close()

class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_frame_tools_have_valid_message_order_and_budget(self):
        from biliscope.service import Service
        from biliscope.browser import Browser
        from biliscope.llm import Client
        path=make_clip()
        ev=Evidence('BV1xx411c7mD',1,1,2,'fixture','fixture',6,6,
           transcript=[{'from':0,'to':6,'content':'A red screen turns green and then blue.'}],transcript_source='fixture')
        service=Service(lambda _:None)
        class FakeBrowser:
            async def load(self,*_):return ev
            async def comments(self,*_):return []
            async def frame(self,ev,t):return Browser._decode_frame(path,ev,t)
            def cleanup_media(self):pass
        service.browser=FakeBrowser()
        history=[]
        def complete(client,messages,tools=False,purpose='request'):
            history.append(json.loads(json.dumps(messages)))
            if len(history)==1:
                return {'role':'assistant','content':None,'tool_calls':[
                   {'id':'a','type':'function','function':{'name':'capture_frames','arguments':'{"seconds":[2.5]}'}},
                   {'id':'b','type':'function','function':{'name':'capture_frames','arguments':'{"seconds":[4.5]}'}}]}
            return {'role':'assistant','content':'The screen changes red → green → blue.'}
        try:
            with patch.object(Client,'complete',complete):
                result=await service.analyze('BV1xx411c7mD','What changes?',Settings(initial_frames=0,extra_frames=2,asr=False),'fixture-key')
            self.assertEqual(len(result.frames),2)
            self.assertEqual([m['role'] for m in history[1]],['system','user','user','assistant','tool','tool','user'])
            self.assertTrue(result.answer)
        finally:
            service.loop.call_soon_threadsafe(service.loop.stop)
            service.thread.join(timeout=3)

    async def test_refuses_title_only_analysis(self):
        from biliscope.service import Service
        service=Service(lambda _:None)
        class FakeBrowser:
            async def load(self,*_):return Evidence('BV1xx411c7mD',1,1,2,'Only a title','a',10,10)
            async def comments(self,*_):return []
            def cleanup_media(self):pass
        service.browser=FakeBrowser()
        try:
            with self.assertRaises(AppError) as error:
                await service.analyze('BV1xx411c7mD','summarize',Settings(vision=False,asr=False),'test-key')
            self.assertEqual(error.exception.code,'NO_VIDEO_EVIDENCE')
        finally:
            service.loop.call_soon_threadsafe(service.loop.stop);service.thread.join(timeout=3)
