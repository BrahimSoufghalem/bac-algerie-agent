from dataclasses import dataclass
from typing import Protocol
import re

@dataclass(frozen=True)
class SearchFilters:
    book_id:str|None=None
    kind:str|None=None
    page_id:str|None=None

class SearchBackend(Protocol):
    def search(self,query:str,filters:SearchFilters,limit:int=20,offset:int=0)->list[dict]: ...


class SQLiteBM25:
    def __init__(self,db): self.db=db
    def search(self,query,filters,limit=20,offset=0):
        terms=re.findall(r'\w+',query,flags=re.UNICODE)[:32]
        if not terms: return []
        expression=' AND '.join('"'+t.replace('"','""')+'"' for t in terms)
        sql="SELECT entity_id,book_id,page_id,kind,title,snippet(search_fts,5,'','','…',24) AS snippet,-bm25(search_fts,0,0,0,0,3,1) AS score FROM search_fts WHERE search_fts MATCH ?"
        params=[expression]
        for field in ('book_id','kind','page_id'):
            value=getattr(filters,field)
            if value is not None: sql+=' AND '+field+'=?';params.append(value)
        sql+=' ORDER BY score DESC,entity_id LIMIT ? OFFSET ?';params.extend([limit,offset])
        return self.db.rows(sql,params)


class SearchService:
    """Backend-independent vector plug-in; no compulsory vector database or embeddings API."""
    def __init__(self,lexical:SearchBackend,vector:SearchBackend|None=None):
        self.lexical,self.vector=lexical,vector
    def search(self,query,filters,limit=20,offset=0,mode='lexical'):
        if mode=='lexical': return self.lexical.search(query,filters,limit,offset)
        if mode not in ('vector','hybrid'): raise ValueError('Unknown search mode')
        if self.vector is None: raise ValueError('No vector backend configured; lexical BM25 is available')
        if mode=='vector': return self.vector.search(query,filters,limit,offset)
        scores={};items={}
        for backend in (self.lexical,self.vector):
            for rank,item in enumerate(backend.search(query,filters,min(1000,(limit+offset)*3),0),1):
                if any(getattr(filters,f) is not None and item.get(f)!=getattr(filters,f) for f in ('book_id','kind','page_id')): continue
                key=item['entity_id'];items[key]=item;scores[key]=scores.get(key,0)+1/(60+rank)
        ordered=sorted(items,key=lambda key:(-scores[key],key))[offset:offset+limit]
        return [{**items[key],'score':scores[key],'ranking':'reciprocal_rank_fusion'} for key in ordered]
