from bac.vendor.bookforge.models.page import Element, TocEntry
from bac.vendor.bookforge.library.structure import detect_structure
from bac.vendor.bookforge.markdown.generator import heading_title, element_markdown


def heading(page, text='الوحدة 01: المتابعة الزمنية لتحول كيميائي',
            kind='unit', label='01', y=20, index=0):
    return {'element': Element(id=f'h{page}_{index}', type='heading', order=index,
                              text=text, structure_type=kind, label=label,
                              bbox=[10, y, 950, y + 40]),
            'page': page, 'ordinal': page * 1_000_000 + index,
            'page_height': 1400}


def nodes(items):
    return detect_structure({'id': 'book', 'title': 'Source', 'page_count': 4},
                            [], items)


def test_running_unit_header_retains_one_original_unit_and_evidence():
    items = [heading(1), heading(1, 'First section', 'section', None, 400, 1),
             heading(2), heading(3),
             heading(3, 'Second section', 'section', None, 400, 1)]
    out = nodes(items)
    units = [n for n in out if n['kind'] == 'unit']
    assert len(units) == 1
    assert units[0]['title'] == items[0]['element'].text
    assert units[0]['start_page'] == 1 and units[0]['end_page'] == 4
    assert [r['pdf_page'] for r in units[0]['evidence']['repeated_running_headings']] == [2, 3]
    assert all(n['parent_id'] == units[0]['id'] for n in out if n['kind'] == 'section')
    assert len(items) == 5  # no original heading/content deleted


def test_different_unit_and_same_title_in_new_parent_are_not_merged():
    out = nodes([heading(1), heading(2, 'الوحدة 02: الطاقة', label='02'),
                 heading(3)])
    assert len([n for n in out if n['kind'] == 'unit']) == 3
    out = nodes([heading(1, 'Part A', 'part', None),
                 heading(1, 'Lesson 1', 'lesson', '1', 200, 1),
                 heading(2, 'Part B', 'part', None),
                 heading(2, 'Lesson 1', 'lesson', '1', 70, 1)])
    lessons = [n for n in out if n['kind'] == 'lesson']
    assert len(lessons) == 2 and lessons[0]['parent_id'] != lessons[1]['parent_id']


def test_no_position_evidence_midpage_and_samepage_remain_boundaries():
    for repeat in [heading(2, y=400), heading(1, index=1)]:
        assert len([n for n in nodes([heading(1), repeat]) if n['kind'] == 'unit']) == 2
    repeat = heading(2)
    repeat.pop('page_height')
    assert len([n for n in nodes([heading(1), repeat]) if n['kind'] == 'unit']) == 2
    assert len([n for n in nodes([heading(1, y=400), heading(2)])
                if n['kind'] == 'unit']) == 2
    first = heading(1)
    first['element'].bbox = None
    assert len([n for n in nodes([first, heading(2)]) if n['kind'] == 'unit']) == 2


def test_changed_label_and_explicit_toc_target_not_coalesced():
    assert len([n for n in nodes([heading(1), heading(2, label='02')])
                if n['kind'] == 'unit']) == 2
    first, repeat = heading(1), heading(2)
    first['element'].toc_entries = [
        TocEntry(title=repeat['element'].text, printed_page='2', kind='unit')]
    out = detect_structure({'id': 'book', 'title': 'Source', 'page_count': 4},
                           [{'printed_page': '1', 'pdf_page': 1},
                            {'printed_page': '2', 'pdf_page': 2}], [first, repeat])
    assert len([n for n in out if n['kind'] == 'unit']) == 2


def test_heading_label_once_without_partial_number_match():
    el = heading(1)['element']
    assert heading_title(el) == el.text
    assert element_markdown(el) == '# ' + el.text
    el.text = 'الوحدة 010: عنوان'
    assert heading_title(el) == '01 ' + el.text
    el.text = 'Title without a label'
    assert heading_title(el) == '01 ' + el.text