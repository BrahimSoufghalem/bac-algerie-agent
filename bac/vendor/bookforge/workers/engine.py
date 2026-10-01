import asyncio
import json
import logging
import signal
import time
from PIL import Image
from bac.vendor.bookforge.core.config import Settings
from bac.vendor.bookforge.core.storage import LocalStorage
from bac.vendor.bookforge.core.secrets import SecretVault
from bac.vendor.bookforge.database.db import Database,dumps
from bac.vendor.bookforge.models.page import PageDocument
from bac.vendor.bookforge.library.uploads import ensure_rendered
from bac.vendor.bookforge.extraction.assets import extract_assets
from bac.vendor.bookforge.markdown.generator import generate_markdown
from bac.vendor.bookforge.library.structure import gather_pages,detect_structure,export_structure,explicit_relationships
from bac.vendor.bookforge.vision.provider import OpenAICompatibleProvider,ProviderError
from bac.vendor.bookforge.workers.queue import Queue,LeaseLost

log=logging.getLogger('bookforge.worker')


class Engine:
    def __init__(self,db,storage,settings,provider_factory=None):
        self.db,self.storage,self.settings=db,storage,settings
        self.queue=Queue(db,settings); self.vault=SecretVault(storage.root)
        self.provider_factory=provider_factory or self.make_provider
        self.stopping=asyncio.Event()

    def make_provider(self,config,key):
        return OpenAICompatibleProvider(key,config['base_url'],config['model'],self.settings,
                                        config.get('output_mode','json_object'),config.get('max_tokens',12000))

    async def heartbeat(self,job):
        while True:
            await asyncio.sleep(self.settings.lease_seconds/3)
            if not await asyncio.to_thread(self.queue.heartbeat,job): return

    async def wait_rate(self):
        slot=await asyncio.to_thread(self.queue.rate_slot)
        await asyncio.sleep(max(0,slot-time.time()))
        while True:
            state=await asyncio.to_thread(self.db.one,'SELECT cooldown_until FROM settings WHERE id=1')
            wait=state['cooldown_until']-time.time()
            if wait<=0: return
            await asyncio.sleep(wait)

    async def process_page(self,job):
        started=time.monotonic()
        page=self.db.one('SELECT * FROM pages WHERE id=?',(job['target_id'],))
        book=self.db.one('SELECT * FROM books WHERE id=?',(job['book_id'],))
        run=self.db.one('SELECT * FROM runs WHERE id=?',(book['run_id'],))
        config=json.loads(run['config_json'])
        self.db.event(f'Page {page["pdf_page"]} started',book['id'],page['id'])
        image_rel=await asyncio.to_thread(ensure_rendered,book,page,self.storage,self.settings)
        revision=f'library/{book["id"]}/pages/page_{page["pdf_page"]:04d}/revisions/{job["lease_token"]}'
        if job['raw_file'] and self.storage.path(job['raw_file']).exists():
            cached=json.loads(self.storage.read(job['raw_file']))
            doc=PageDocument.model_validate(cached['document']); usage=cached['usage']
        else:
            with Image.open(self.storage.path(image_rel)) as im: width,height=im.size
            provider=self.provider_factory(config,self.vault.decrypt(run['encrypted_key']))
            await self.wait_rate()
            # Re-check lease before making an external request.
            if not await asyncio.to_thread(self.queue.heartbeat,job): raise LeaseLost()
            doc,usage=await provider.extract(self.storage.path(image_rel),page['pdf_page'],width,height)
            raw_file=revision+'/vision_response.json'
            self.storage.write(raw_file,dumps({'document':doc.model_dump(),'usage':usage}).encode())
            self.queue.save_raw(job,raw_file)
            self.db.event('Vision request completed',book['id'],page['id'])
        cleaned,assets,issues=await asyncio.to_thread(extract_assets,doc,self.storage.path(image_rel),self.storage,revision,page['pdf_page'])
        for a in assets:
            a.update({'book_id':book['id'],'page_id':page['id'],'entity_id':page['id']+':'+a['id']})
        markdown=generate_markdown(cleaned,assets,revision)
        if not markdown.strip(): issues.append('EMPTY_MARKDOWN')
        for el in cleaned.elements:
            if el.type=='table' and not (el.rows or el.cells): issues.append('TABLE_TRANSCRIPTION_MISSING')
            if el.type=='equation' and not el.latex: issues.append('EQUATION_LATEX_MISSING')
        issues=list(dict.fromkeys(issues))
        self.storage.write(revision+'/page.json',dumps(cleaned.model_dump()).encode())
        self.storage.write(revision+'/page.md',markdown.encode())
        self.storage.write(revision+'/assets.json',dumps(assets).encode())
        self.storage.write(revision+'/quality.json',dumps({'issues':issues,'source_image':image_rel,'usage':usage,'pdf_page':page['pdf_page']}).encode())
        status='NEEDS_REVIEW' if issues else 'SUCCESS'
        asset_map={a['id']:a['file'] for a in assets}
        with self.db.transaction() as c:
            self.queue.assert_owned(c,job)
            c.execute('UPDATE pages SET status=?,printed_page=?,languages=?,quality=?,artifact_dir=?,elapsed=?,completed_at=?,error=NULL WHERE id=?',
                      (status,cleaned.printed_page,dumps(cleaned.languages),dumps(issues),revision,time.monotonic()-started,time.time(),page['id']))
            c.execute('DELETE FROM elements WHERE page_id=?',(page['id'],))
            c.execute('DELETE FROM search_fts WHERE page_id=?',(page['id'],))
            for index,el in enumerate(cleaned.elements):
                entity=page['id']+':'+el.id
                c.execute('INSERT INTO elements VALUES(?,?,?,?,?,?,?,?)',
                          (entity,book['id'],page['id'],el.id,el.type,page['pdf_page']*1_000_000+index,dumps(el.model_dump()),asset_map.get(el.id)))
                body='\n'.join([el.text,el.caption,el.latex,' '.join(el.headers)]+[' '.join(r) for r in el.rows]+[x.text for x in el.cells]+el.footnotes)
                c.execute('INSERT INTO search_fts VALUES(?,?,?,?,?,?)',(entity,book['id'],page['id'],el.type,el.text if el.type=='heading' else el.caption,body))
            c.execute('INSERT INTO search_fts VALUES(?,?,?,?,?,?)',(page['id'],book['id'],page['id'],'page',f'Page {page["pdf_page"]}',''))
            self.queue.finish(c,job)
        self.db.event(f'{len(assets)} visual crops saved; Markdown generated; Page {page["pdf_page"]} {status}',book['id'],page['id'])

    def process_structure(self,job):
        book=self.db.one('SELECT * FROM books WHERE id=?',(job['book_id'],))
        pages,items=gather_pages(book['id'],self.db,self.storage)
        nodes=detect_structure(book,pages,items)
        incomplete=any(p['status'] in ('FAILED','NEEDS_REVIEW') for p in pages)
        status='COMPLETED_WITH_ISSUES' if incomplete else 'COMPLETED'
        completed_at=time.time()
        book={**book,'status':status,'completed_at':completed_at}
        prefix=export_structure(book,pages,items,nodes,self.storage,job['lease_token'])
        relationships=explicit_relationships(nodes,items)
        with self.db.transaction() as c:
            self.queue.assert_owned(c,job)
            c.execute('DELETE FROM search_fts WHERE entity_id IN (SELECT id FROM nodes WHERE book_id=?)',(book['id'],))
            c.execute('DELETE FROM relationships WHERE source LIKE ?',(book['id']+'%',))
            c.execute('DELETE FROM nodes WHERE book_id=?',(book['id'],))
            for n in nodes:
                c.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (n['id'],n['book_id'],n['parent_id'],n['kind'],n['title'],n['label'],n['start_order'],n['end_order'],n['start_page'],n['end_page'],n['content_file'],n['metadata_file'],dumps(n['evidence'])))
                c.execute('INSERT INTO search_fts VALUES(?,?,?,?,?,?)',(n['id'],book['id'],'',n['kind'],n['title'],''))
            c.executemany('INSERT OR IGNORE INTO relationships VALUES(?,?,?,?)',relationships)
            c.execute('UPDATE books SET status=?,structure_dir=?,completed_at=? WHERE id=?',(status,prefix,completed_at,book['id']))
            self.queue.finish(c,job)
        self.db.event('Book structure and library index completed',book['id'])

    async def process(self,job):
        heartbeat=asyncio.create_task(self.heartbeat(job))
        try:
            if job['kind']=='page': await self.process_page(job)
            else: await asyncio.to_thread(self.process_structure,job)
        except asyncio.CancelledError:
            self.queue.release(job)
            raise
        except LeaseLost:
            log.warning('Discarded stale lease result')
        except ProviderError as exc:
            try: self.queue.fail(job,exc.code,exc.retryable,exc.retry_after)
            except LeaseLost: pass
        except Exception as exc:
            # Do not log payloads, provider URL, credentials or arbitrary remote exception text.
            code='LOCAL_'+type(exc).__name__
            try: self.queue.fail(job,code)
            except LeaseLost: pass
            log.error('Job failed (%s)',code)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat,return_exceptions=True)

    async def worker(self,slot):
        while not self.stopping.is_set():
            try:
                desired=self.db.one('SELECT workers FROM settings WHERE id=1')['workers']
                job=await asyncio.to_thread(self.queue.claim) if slot<desired else None
                if job:
                    await self.process(job)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error('Worker poll failed (%s); retrying',type(exc).__name__)
            try: await asyncio.wait_for(self.stopping.wait(),timeout=0.75)
            except asyncio.TimeoutError: pass

    async def report_alive(self):
        import uuid
        identity=uuid.uuid4().hex
        try:
            while not self.stopping.is_set():
                await asyncio.to_thread(self.db.execute,'INSERT OR REPLACE INTO engine_heartbeats VALUES(?,?)',(identity,time.time()))
                try: await asyncio.wait_for(self.stopping.wait(),timeout=5)
                except asyncio.TimeoutError: pass
        finally:
            self.db.execute('DELETE FROM engine_heartbeats WHERE id=?',(identity,))

    async def run(self):
        reporter=asyncio.create_task(self.report_alive())
        # Global database cap also applies if multiple engine processes are accidentally launched.
        tasks=[asyncio.create_task(self.worker(i)) for i in range(self.settings.worker_ceiling)]
        await self.stopping.wait()
        try: await asyncio.wait_for(asyncio.gather(*tasks),timeout=25)
        except asyncio.TimeoutError:
            for t in tasks: t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        await reporter


def main():
    settings=Settings.from_env(); storage=LocalStorage(settings.data_dir)
    db=Database(storage.root/'state.sqlite3',settings.max_workers)
    engine=Engine(db,storage,settings)
    logging.basicConfig(level=logging.INFO)
    async def run():
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,engine.stopping.set)
        await engine.run()
    asyncio.run(run())

if __name__=='__main__': main()
