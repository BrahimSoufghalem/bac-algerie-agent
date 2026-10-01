"""Run PyMuPDF in isolated subprocesses, not concurrent threads."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid


def _limits():
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))


def inspect_pdf(path: Path):
    output = subprocess.run([sys.executable, '-m', 'bac.vendor.bookforge.pipeline.pdf', 'inspect', str(path)],
                            capture_output=True, timeout=35, check=True)
    return json.loads(output.stdout)


def render_pdf(path: Path, page: int, output: Path, dpi: int, max_pixels: int):
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'bac.vendor.bookforge.pipeline.pdf', 'render', str(path), str(page), str(output), str(dpi), str(max_pixels)],
                   capture_output=True, timeout=70, check=True)
    from PIL import Image
    with Image.open(output) as im:
        return im.size


def main():
    _limits()
    import pymupdf as fitz
    action, path = sys.argv[1:3]
    with fitz.open(path) as doc:
        if doc.needs_pass or doc.page_count == 0:
            raise ValueError('Encrypted or empty PDF')
        if action == 'inspect':
            print(json.dumps({'page_count': doc.page_count, 'title': (doc.metadata.get('title') or '')[:500]}))
        else:
            page, output, dpi, cap = sys.argv[3:]
            p = doc[int(page) - 1]
            scale = int(dpi) / 72
            expected = p.rect.width * p.rect.height * scale**2
            if expected > int(cap):
                scale *= math.sqrt(int(cap) / expected) * 0.99
            if p.rect.width <= 0 or p.rect.height <= 0:
                raise ValueError('Invalid page geometry')
            pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
            tmp = output + '.' + uuid.uuid4().hex + '.png'
            try:
                pix.save(tmp)
                os.replace(tmp, output)
            finally:
                Path(tmp).unlink(missing_ok=True)

if __name__ == '__main__':
    main()
