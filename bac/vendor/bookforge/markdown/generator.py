from pathlib import PurePosixPath
import os
from bac.vendor.bookforge.models.page import Element, PageDocument


def cell_text(text):
    return text.replace('\\','\\\\').replace('|','\\|').replace('\r\n','\n').replace('\n','<br>')


def element_markdown(el: Element, asset_file=None, base_dir=''):
    blocks=[]
    if el.type == 'heading':
        title = el.text
        if el.label and not title.startswith(el.label):
            title = el.label + ' ' + title
        blocks.append('#' * min(el.level,6) + ' ' + title)
    elif el.type == 'equation':
        if el.latex:
            blocks.append('$$\n' + el.latex + '\n$$')
        elif el.text:
            blocks.append(el.text)
        else:
            blocks.append('[ILLEGIBLE EQUATION]')
    elif el.type == 'table':
        if el.text:
            blocks.append(el.text)
        width=max([len(el.headers)] + [len(r) for r in el.rows],default=0)
        complex_table = el.complex_table or bool(el.cells) or any(len(r)!=width for r in el.rows)
        if width and not complex_table:
            headers = el.headers or ['']*width
            lines=['| ' + ' | '.join(cell_text(x) for x in headers) + ' |',
                   '| ' + ' | '.join(['---']*width) + ' |']
            lines += ['| ' + ' | '.join(cell_text(x) for x in row) + ' |' for row in el.rows]
            blocks.append('\n'.join(lines))
        else:
            # Lossless fallback: original raster + exact cell values, no invented cells.
            if el.headers:
                blocks.append('Headers: ' + ' | '.join(cell_text(x) for x in el.headers))
            for i,row in enumerate(el.rows):
                blocks.append(f'Row {i}: ' + ' | '.join(cell_text(x) for x in row))
            for cell in el.cells:
                blocks.append(f'Cell ({cell.row},{cell.column}), span {cell.row_span}×{cell.column_span}: {cell.text}')
        blocks.extend(el.footnotes)
    elif el.type == 'toc':
        if el.text: blocks.append(el.text)
        for t in el.toc_entries:
            blocks.append('  '*(t.level-1) + '- ' + ((t.number+' ') if t.number else '') + t.title + (f' — {t.printed_page}' if t.printed_page else ''))
    elif el.text:
        blocks.append(el.text)
    if asset_file:
        rel=os.path.relpath(asset_file,base_dir or '.').replace(os.sep,'/')
        label=(el.caption or el.type).replace('[','\\[').replace(']','\\]').replace('\n',' ')
        blocks.append(f'![{label}]({rel})')
    if el.caption:
        blocks.append(el.caption)
    return '\n\n'.join(blocks)


def generate_markdown(doc: PageDocument, assets, revision_dir):
    by_id={a['id']:a['file'] for a in assets}
    blocks=[element_markdown(el,by_id.get(el.id),revision_dir) for el in sorted(doc.elements,key=lambda e:e.order)]
    text='\n\n'.join(b for b in blocks if b).strip()
    if doc.is_blank and not text:
        text='[BLANK PAGE]'
    return text+'\n' if text else ''
