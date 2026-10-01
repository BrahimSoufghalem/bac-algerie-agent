import math
from PIL import Image, ImageStat
from bac.vendor.bookforge.models.page import PageDocument

VISUAL_TYPES = {'figure', 'image', 'diagram', 'table', 'equation', 'caption'}


def valid_bbox(box, width, height):
    return (box is not None and len(box) == 4 and all(math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)


def extract_assets(document: PageDocument, image, storage, revision_dir: str, pdf_page: int):
    """Never synthesizes visuals. Invalid boxes retain the original page and flag review."""
    doc = document.model_copy(deep=True)
    issues, assets = [], []
    with Image.open(image) as original:
        width, height = original.size
        if (doc.width, doc.height) != (width, height):
            issues.append('MODEL_IMAGE_DIMENSIONS_MISMATCH')
        if doc.pdf_page != pdf_page:
            issues.append('MODEL_PAGE_NUMBER_MISMATCH')
        doc.width, doc.height, doc.pdf_page = width, height, pdf_page
        if doc.is_blank and ImageStat.Stat(original.convert('L').resize((128,128))).stddev[0] > 16:
            issues.append('BLANK_PAGE_HAS_VISIBLE_CONTENT')
        seen, orders = set(), set()
        for index, el in enumerate(doc.elements):
            if el.id in seen:
                issues.append('DUPLICATE_ELEMENT_ID')
                el.id = f'{el.id}_{index}'
            seen.add(el.id)
            if el.order in orders:
                issues.append('AMBIGUOUS_READING_ORDER')
            orders.add(el.order)
            if el.unreadable or '[ILLEGIBLE]' in el.text or '[ILLEGIBLE]' in el.latex:
                issues.append('ILLEGIBLE_CONTENT')
            if el.confidence is not None and el.confidence < 0.65:
                issues.append('LOW_ELEMENT_CONFIDENCE')
            if el.bbox is not None and not valid_bbox(el.bbox, width, height):
                issues.append(f'INVALID_BBOX:{el.id}')
            if el.type in VISUAL_TYPES:
                if not valid_bbox(el.bbox, width, height):
                    issues.append(f'MISSING_VALID_VISUAL_BBOX:{el.id}')
                    continue
                x1,y1,x2,y2 = el.bbox
                pixel_box = (math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2))
                crop = original.crop(pixel_box)
                from io import BytesIO
                buf = BytesIO(); crop.save(buf,format='PNG')
                rel = f'{revision_dir}/assets/{el.type}_{el.id}.png'
                storage.write(rel,buf.getvalue())
                assets.append({'id':el.id,'type':el.type,'pdf_page':pdf_page,'file':rel,
                               'caption':el.caption or (el.text if el.type == 'caption' else ''),
                               'bbox':el.bbox,'pixel_crop_bbox':list(pixel_box)})
        if not doc.is_blank and not doc.elements:
            issues.append('NONBLANK_PAGE_EMPTY')
        if doc.reading_order_confidence is not None and doc.reading_order_confidence < 0.65:
            issues.append('LOW_READING_ORDER_CONFIDENCE')
        if not doc.is_blank and not any(e.text or e.latex or e.rows or e.cells for e in doc.elements) and not any(e.type in VISUAL_TYPES for e in doc.elements):
            issues.append('MISSING_TRANSCRIPTION')
    doc.elements.sort(key=lambda e:e.order)  # Stable on ties; never infer order by y.
    return doc, assets, list(dict.fromkeys(issues))
