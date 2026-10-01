import hashlib
from pathlib import Path
import shutil
import time
from bac.vendor.bookforge.database.db import new_id
from bac.vendor.bookforge.pipeline.pdf import inspect_pdf


def register_pdf(path: Path, filename: str, db, storage, settings):
    size = path.stat().st_size
    if size > settings.max_upload_mb * 1024**2:
        raise ValueError('PDF exceeds upload size limit')
    with path.open('rb') as f:
        if b'%PDF-' not in f.read(1024):
            raise ValueError('File is not a PDF')
        f.seek(0)
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    existing = db.one('SELECT * FROM books WHERE sha256=?', (sha,))
    if existing:
        return existing, True
    info = inspect_pdf(path)
    if info['page_count'] > settings.max_pages:
        raise ValueError('PDF exceeds page count limit')
    book_id = new_id('book')
    source = f'uploads/{sha}.pdf'
    dest = storage.path(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.tmp.' + book_id)
    try:
        shutil.copyfile(path, temp)
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)
    filename = Path(filename.replace('\\', '/')).name[:255]
    title = info['title'] or Path(filename).stem
    with db.transaction() as c:
        existing = c.execute('SELECT * FROM books WHERE sha256=?', (sha,)).fetchone()
        if existing:
            return dict(existing), True
        c.execute('INSERT INTO books(id,filename,title,sha256,size,page_count,source_file,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  (book_id, filename, title, sha, size, info['page_count'], source, time.time()))
        c.executemany('INSERT INTO pages(id,book_id,pdf_page) VALUES(?,?,?)',
                      [(f'{book_id}:p{i:04d}', book_id, i) for i in range(1, info['page_count'] + 1)])
    db.event('Book uploaded', book_id)
    return db.one('SELECT * FROM books WHERE id=?', (book_id,)), False


def ensure_rendered(book, page, storage, settings):
    from PIL import Image
    from bac.vendor.bookforge.pipeline.pdf import render_pdf
    rel = f'library/{book["id"]}/pages/page_{page["pdf_page"]:04d}/original.png'
    path = storage.path(rel)
    if path.exists():
        try:
            with Image.open(path) as im:
                im.verify()
            return rel
        except Exception:
            pass
    render_pdf(storage.path(book['source_file']), page['pdf_page'], path, settings.page_dpi, settings.max_pixels)
    return rel
