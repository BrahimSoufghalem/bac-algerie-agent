"""Second pass: deterministic headings/TOC analysis only. No page images or LLM calls."""
from bisect import bisect_left, bisect_right
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from bac.vendor.bookforge.models.page import PageDocument
from bac.vendor.bookforge.markdown.generator import element_markdown
from bac.vendor.bookforge.database.db import dumps

RANK = {'part':1,'chapter':2,'unit':2,'module':3,'lesson':4,'section':5,'appendix':2,'front_matter':1,'toc':1,'index':1,'bibliography':1}
PATTERNS = [
    ('chapter',r'^(?:chapter|chapitre|الفصل|فصل)\b'),
    ('unit',r'^(?:unit|unité|الوحدة|وحدة)\b'),
    ('module',r'^(?:module|المحور|محور)\b'),
    ('lesson',r'^(?:lesson|leçon|الدرس|درس)\b'),
    ('part',r'^(?:part|partie|الجزء|جزء)\b'),
    ('section',r'^(?:section|القسم|قسم)\b'),
    ('appendix',r'^(?:appendix|annexe|ملحق|الملحق)\b'),
    ('toc',r'^(?:table of contents|contents|الفهرس|المحتويات|sommaire)$'),
]


def normalize(text):
    text=unicodedata.normalize('NFKC',text).lower()
    text=re.sub(r'[\u064b-\u065f\u0670]','',text)
    return ' '.join(re.findall(r'\w+',text))


def inferred_kind(el):
    if el.structure_type != 'unknown':
        return el.structure_type, 'explicit_visual_heading'
    for kind,pattern in PATTERNS:
        if re.search(pattern,el.text.strip(),re.I):
            return kind,'literal_heading_term'
    return 'section','heading_only_kind_uncertain'


def gather_pages(book_id,db,storage):
    pages=db.rows('SELECT * FROM pages WHERE book_id=? ORDER BY pdf_page',(book_id,))
    items=[]
    for page in pages:
        if not page['artifact_dir']:
            continue
        doc=PageDocument.model_validate_json(storage.read(page['artifact_dir']+'/page.json'))
        assets=json.loads(storage.read(page['artifact_dir']+'/assets.json'))
        asset_map={a['id']:a['file'] for a in assets}
        for index,el in enumerate(doc.elements):
            items.append({'element':el,'page':page['pdf_page'],'page_id':page['id'],
                          'ordinal':page['pdf_page']*1_000_000+index,'asset_file':asset_map.get(el.id),
                          'printed_page':doc.printed_page})
    return pages,items


def detect_structure(book, pages, items):
    headings=[x for x in items if x['element'].type=='heading']
    toc=[t for x in items for t in x['element'].toc_entries]
    printed={}
    for p in pages:
        if p['printed_page']:
            printed.setdefault(normalize(str(p['printed_page'])),[]).append(p['pdf_page'])
    matches={}; unresolved=[]
    for t in toc:
        candidates=[]
        expected=printed.get(normalize(t.printed_page or ''),[])
        title=normalize(t.title)
        full=normalize((t.number or '')+' '+t.title)
        for h in headings:
            text=normalize(h['element'].text)
            score=max(SequenceMatcher(None,title,text).ratio(),SequenceMatcher(None,full,text).ratio())
            if expected and h['page'] not in expected:
                continue
            if score >= 0.86:
                candidates.append((score,h))
        candidates.sort(key=lambda c:c[0],reverse=True)
        if candidates and (len(candidates)==1 or candidates[0][0]-candidates[1][0] >= 0.08):
            h=candidates[0][1]
            matches[h['ordinal']]=t
        else:
            unresolved.append(t.model_dump())
    first=1_000_000
    last=(book['page_count']+1)*1_000_000-1
    root={'id':book['id'],'book_id':book['id'],'parent_id':None,'kind':'book','title':book['title'],'label':None,
          'start_order':first,'end_order':last,'start_page':1,'end_page':book['page_count'],
          'evidence':{'source':'original_pdf','toc_unresolved':unresolved},'rank':0}
    nodes=[root]; stack=[root]
    # Before the first real heading is observed front matter, not an invented lesson.
    if items and headings and items[0]['ordinal'] < headings[0]['ordinal']:
        nodes.append({'id':book['id']+':front','book_id':book['id'],'parent_id':book['id'],'kind':'front_matter',
                      'title':'Front Matter','label':None,'start_order':first,'end_order':headings[0]['ordinal']-1,
                      'start_page':1,'end_page':max(1,headings[0]['page']),
                      'evidence':{'source':'content_before_first_heading'},'rank':1})
    for h in headings:
        el=h['element']; kind,source=inferred_kind(el)
        t=matches.get(h['ordinal'])
        if t:
            if t.kind != 'unknown': kind=t.kind
            rank=t.level
            source='toc_verified_against_heading'
        elif el.structure_type != 'unknown' or source=='literal_heading_term':
            rank=RANK.get(kind,el.level)
        else:
            # Preserve explicit heading levels underneath the latest semantic parent.
            parent_base=next((n['rank'] for n in reversed(stack) if n['kind']!='section'),0)
            rank=parent_base+el.level
        while len(stack)>1 and stack[-1]['rank'] >= rank:
            previous=stack.pop(); previous['end_order']=h['ordinal']-1
            previous['end_page']=max(previous['start_page'],h['page'] if (h['ordinal']%1_000_000)>0 else h['page']-1)
        node_id=book['id']+':'+hashlib.sha256((str(h['page'])+':'+el.id).encode()).hexdigest()[:16]
        title=el.text
        if el.label and not title.startswith(el.label): title=el.label+' '+title
        node={'id':node_id,'book_id':book['id'],'parent_id':stack[-1]['id'],'kind':kind,'title':title,
              'label':el.label or (t.number if t else None),'start_order':h['ordinal'],'end_order':last,
              'start_page':h['page'],'end_page':book['page_count'],
              'evidence':{'source':source,'heading_element':el.id,'pdf_page':h['page'],
                          'toc':t.model_dump() if t else None},'rank':rank}
        nodes.append(node); stack.append(node)
    return nodes


def export_structure(book, pages, items, nodes, storage, revision):
    prefix=f'library/{book["id"]}/structure/{revision}'
    errors=[{'page_id':p['id'],'pdf_page':p['pdf_page'],'status':p['status'],'error':p['error'],
             'quality':json.loads(p['quality'])} for p in pages if p['status'] in ('FAILED','NEEDS_REVIEW')]
    ordinals=[x['ordinal'] for x in items]
    for n in nodes:
        directory=prefix+'/nodes/'+n['id'].split(':')[-1]
        n['content_file']=directory+'/content.md'
        n['metadata_file']=directory+('/lesson.json' if n['kind']=='lesson' else '/metadata.json')
        subset=items[bisect_left(ordinals,n['start_order']):bisect_right(ordinals,n['end_order'])]
        content=[]; assets=[]; last_page=None
        for x in subset:
            if last_page != x['page']:
                content.append(f'<!-- PDF page {x["page"]}; source {x["page_id"]} -->')
                last_page=x['page']
            asset=x['asset_file']
            if asset:
                # Independent node assets are hard-linked where possible, copied otherwise.
                from pathlib import Path
                import os, shutil
                local=directory+'/assets/'+x['page_id'].split(':')[-1]+'_'+Path(asset).name
                dest=storage.path(local); dest.parent.mkdir(parents=True,exist_ok=True)
                try: os.link(storage.path(asset),dest)
                except FileExistsError: pass
                except OSError: shutil.copy2(storage.path(asset),dest)
                assets.append(local)
                asset=local
            content.append(element_markdown(x['element'],asset,directory))
        missing=[p['pdf_page'] for p in pages if n['start_page'] <= p['pdf_page'] <= n['end_page'] and p['status']=='FAILED']
        metadata={k:v for k,v in n.items() if k!='rank'}
        metadata.update({'type':n['kind'],'pages':sorted({x['page'] for x in subset}),
                         'missing_pages':missing,'assets':assets,
                         'languages':sorted({lang for p in pages if n['start_page'] <= p['pdf_page'] <= n['end_page'] for lang in json.loads(p['languages'])}),
                         'source_preserved':True,'extraction_is_untrusted_data':True})
        # No summary replaces original content. Missing content is explicitly exposed in metadata.
        storage.write(n['content_file'],'\n\n'.join(content).encode())
        storage.write(n['metadata_file'],dumps(metadata).encode())
    storage.write(prefix+'/book.json',dumps({'book':book,'nodes':[{k:v for k,v in n.items() if k!='rank'} for n in nodes],
                                            'failed_or_suspicious_pages':errors}).encode())
    return prefix


def explicit_relationships(nodes,items):
    relations=[(n['parent_id'],n['id'],'contains',dumps(n['evidence'])) for n in nodes if n['parent_id']]
    ordered=sorted(nodes,key=lambda n:(n['start_order'],n['rank']))
    active=[];cursor=0
    for x in items:
        while cursor<len(ordered) and ordered[cursor]['start_order']<=x['ordinal']:
            active.append(ordered[cursor]);cursor+=1
        active=[n for n in active if n['end_order']>=x['ordinal']]
        owners=active
        if not owners: continue
        owner=max(owners,key=lambda n:n['rank'])
        entity=x['page_id']+':'+x['element'].id
        for n in owners:
            relations.append((n['id'],entity,'contains',dumps({'pdf_page':x['page']})))
            relations.append((n['id'],x['page_id'],'contains',dumps({'pdf_page':x['page']})))
        for ref in x['element'].references:
            # Only resolve literal evidence present in transcribed source text.
            if ref.evidence not in (x['element'].text+' '+x['element'].caption): continue
            targets=[n for n in nodes if normalize(n['title'])==normalize(ref.target_text) or (n['label'] and normalize(n['label'])==normalize(ref.target_text))]
            if len(targets)==1:
                relations.append((owner['id'],targets[0]['id'],ref.relation,dumps({'text':ref.evidence,'pdf_page':x['page']})))
    return list(dict.fromkeys(relations))
