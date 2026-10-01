"""Synthetic scanned PDF + known transcription fixtures (not a real OCR benchmark)."""
from io import BytesIO
from pathlib import Path
import json
import sys
import pymupdf as fitz
from PIL import Image,ImageDraw,ImageFont,ImageFilter

W,H=1200,1700

def font(size,arabic=False):
    candidates=([Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/msttcore/arial.ttf'),Path('/usr/share/fonts/google-noto/NotoSansArabic-Regular.ttf'),Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf')]
                if arabic else [Path('/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf'),Path('/usr/share/fonts/msttcore/arial.ttf'),Path('/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')])
    for p in candidates:
        if p.exists(): return ImageFont.truetype(str(p),size)
    raise RuntimeError('Install fonts-noto-core and fonts-dejavu-core')


def golden_page(page,width,height):
    def element(id,type,order,bbox,**kwargs):
        box=[bbox[0]*width/W,bbox[1]*height/H,bbox[2]*width/W,bbox[3]*height/H] if bbox else None
        return {'id':id,'type':type,'order':order,'bbox':box,**kwargs}
    elements=[]
    if page==1:
        elements=[element('title','heading',0,[80,100,1100,210],text='مبادئ الحرارة / Principles of Heat',structure_type='front_matter'),
                  element('toc','toc',1,[100,350,1100,800],text='المحتويات / Contents',toc_entries=[
                      {'title':'Unit 1 · Heat','printed_page':'1','level':1,'kind':'unit'},
                      {'title':'الدرس 1 · الحرارة','printed_page':'1','level':2,'kind':'lesson'},
                      {'title':'Lesson 2 · Energy','printed_page':'2','level':2,'kind':'lesson'},
                      {'title':'Lesson 3 · Mixed Languages','printed_page':'3','level':2,'kind':'lesson'},
                      {'title':'Lesson 4 · Low Quality','printed_page':'4','level':2,'kind':'lesson'}])]
    elif page==2:
        elements=[element('unit','heading',0,[80,80,1120,155],text='Unit 1 · Heat',structure_type='unit'),
                  element('lesson','heading',1,[80,175,1120,275],text='الدرس 1 · الحرارة',structure_type='lesson'),
                  element('right','paragraph',2,[650,320,1120,540],text='الحرارة طاقة تنتقل من الجسم الساخن إلى الجسم البارد.\nدرجة الحرارة تقاس بوحدة كلفن.'),
                  element('left','paragraph',3,[80,320,550,540],text='هذا نص في العمود الأيسر.\nيُقرأ بعد العمود الأيمن.'),
                  element('fig1','figure',4,[100,600,500,900],caption='Figure 1: Original colored apparatus'),
                  element('fig2','diagram',5,[680,600,1080,900],caption='Figure 2: Original diagram'),
                  element('eq','equation',6,[150,1020,1050,1130],latex='PV = nRT'),
                  element('tbl','table',7,[100,1170,1100,1400],headers=['Parameter','Value'],rows=[['Temperature','25 °C'],['Pressure','1.2 MPa']],footnotes=['Values are illustrative.']),
                  element('footnote','footnote',8,[100,1500,1100,1600],text='حاشية: تُحفظ الصورة الأصلية والنص دون ترجمة.')]
    elif page==3:
        elements=[element('lesson','heading',0,[80,120,1120,240],text='Lesson 2 · Energy',structure_type='lesson'),
                  element('p','paragraph',1,[80,350,1120,600],text='Energy is conserved in an isolated system.\nThis full source paragraph must never be replaced by a summary.'),
                  element('eq','equation',2,[150,700,1050,840],latex='E = mc^2'),
                  element('footnote','footnote',3,[100,1480,1100,1580],text='Footnote: See Lesson 2 · Energy.',references=[{'target_text':'Lesson 2 · Energy','evidence':'See Lesson 2 · Energy.','relation':'references'}])]
    elif page==4:
        elements=[element('lesson','heading',0,[80,120,1120,240],text='Lesson 3 · Mixed Languages',structure_type='lesson'),
                  element('ar','paragraph',1,[80,340,1120,470],text='اللغة الأصلية محفوظة دون ترجمة.'),
                  element('en','paragraph',2,[80,520,1120,650],text='English: retain the exact source text.'),
                  element('fr','paragraph',3,[80,700,1120,830],text='Français : conserver le texte original.'),
                  element('complex','table',4,[100,950,1100,1250],complex_table=True,cells=[{'row':0,'column':0,'column_span':2,'text':'Merged / مدمج'}, {'row':1,'column':0,'text':'A'}, {'row':1,'column':1,'text':'10 kg'}])]
    else:
        elements=[element('lesson','heading',0,[80,120,1120,240],text='Lesson 4 · Low Quality',structure_type='lesson'),
                  element('p','paragraph',1,[100,430,1100,650],text='[ILLEGIBLE]',unreadable=True,confidence=0.2)]
    return {'schema_version':'1.0','pdf_page':page,'printed_page':None if page==1 else str(page-1),
            'width':width,'height':height,'coordinate_system':'pixels','languages':(['ar','en','fr'] if page==4 else ['ar','en'] if page<=2 else ['en']),
            'is_blank':False,'reading_order_confidence':0.97,'elements':elements}


def make_fixture(output:Path):
    output.parent.mkdir(parents=True,exist_ok=True)
    with fitz.open() as pdf:
        for page in range(1,6):
            im=Image.new('RGB',(W,H),'white');draw=ImageDraw.Draw(im)
            doc=golden_page(page,W,H)
            for e in doc['elements']:
                x1,y1,x2,y2=[int(x) for x in e['bbox']]
                if e['type'] in ('figure','diagram'):
                    draw.rectangle((x1,y1,x2,y2),fill=('#d5e8f4' if e['type']=='figure' else '#f4ddbf'),outline='#223344',width=3)
                    draw.ellipse((x1+70,y1+70,x1+210,y1+210),fill='#5c92b5',outline='#223344',width=3)
                    draw.line((x1+200,y1+160,x2-30,y2-60),fill='#223344',width=8)
                    draw.text((x1,y2+12),e['caption'],font=font(22),fill='#222')
                elif e['type']=='table':
                    rows=[e['headers']]+e['rows'] if e.get('headers') else [['Merged / مدمج',''],['A','10 kg']]
                    rh=(y2-y1)//len(rows);cw=(x2-x1)//2
                    for r,row in enumerate(rows):
                        for c,text in enumerate(row):
                            xx=x1+c*cw;yy=y1+r*rh
                            draw.rectangle((xx,yy,xx+cw,yy+rh),outline='#333',width=2)
                            draw.text((xx+15,yy+10),text,font=font(30,arabic=any('\u0600'<=ch<='\u06ff' for ch in text)),fill='#222')
                else:
                    text=e.get('text','') or e.get('latex','').replace('^2','²')
                    if e['type']=='toc': text+='\n'+'\n'.join(t['title']+' .... '+(t['printed_page'] or '') for t in e['toc_entries'])
                    if '[ILLEGIBLE]' in text: text='Faint and blurred source text — not confidently legible.'
                    arabic=any('\u0600'<=ch<='\u06ff' for ch in text)
                    size=42 if e['type']=='heading' else 31 if e['type']!='footnote' else 25
                    kwargs={'direction':'rtl','anchor':'ra'} if arabic else {}
                    face=font(size,arabic)
                    wrapped=[]
                    for line in text.splitlines():
                        current=''
                        for word in line.split():
                            candidate=(current+' '+word).strip()
                            if current and draw.textlength(candidate,font=face) > x2-x1:
                                wrapped.append(current);current=word
                            else:current=candidate
                        wrapped.append(current)
                    draw.multiline_text((x2 if arabic else x1,y1),'\n'.join(wrapped),font=face,fill='#222',spacing=14,**kwargs)
            draw.text((W//2,H-60),str(page-1) if page>1 else 'i',font=font(26),fill='#666')
            if page==5:
                im=im.resize((300,425)).filter(ImageFilter.GaussianBlur(1.1)).resize((W,H))
            buf=BytesIO();im.save(buf,format='JPEG',quality=50 if page==5 else 95)
            p=pdf.new_page(width=600,height=850);p.insert_image(p.rect,stream=buf.getvalue())
        pdf.save(output)
    output.with_suffix('.golden.json').write_text(json.dumps([golden_page(p,W,H) for p in range(1,6)],ensure_ascii=False,indent=2))
    return output

if __name__=='__main__':
    path=make_fixture(Path(sys.argv[1] if len(sys.argv)>1 else 'tests/fixtures/scanned_book.pdf'))
    print(path)
