from wxfetch import jsvars


def test_decode_js_string():
    assert jsvars.decode_js_string(r"a\x0ab\x26c\u4e2d\'\"\\") == "a\nb&c中'\"\\"
    assert jsvars.decode_js_string(r"\ud83d\ude00") == "😀"
    assert jsvars.decode_js_string("plain") == "plain"


def test_find_js_var_shapes():
    page = """
      if (window.nickname === '') {}
      var nickname = htmlDecode("A\\x26amp;B");
      window.msg_title = window.title = '标题\\x0a第二行';
      var empty = '';
      var msg_desc = "desc with \\"quote\\"";
    """
    assert jsvars.find_js_var(page, ["nickname"]) == "A&B"
    assert jsvars.find_js_var(page, ["msg_title"]) == "标题\n第二行"
    assert jsvars.find_js_var(page, ["empty"]) is None
    assert jsvars.find_js_var(page, ["msg_desc"]) == 'desc with "quote"'
    assert jsvars.find_js_var(page, ["missing"]) is None


def test_find_number():
    assert jsvars.find_number('var ct = "1757583599";', ["ct"]) == 1757583599
    assert jsvars.find_number("window.ct = '1791215991' || '';", ["ct"]) == 1791215991
    assert jsvars.find_number("ori_create_time: '1791215991' * 1,", ["ori_create_time"]) == 1791215991
    assert jsvars.find_number("var select = 1234567890;", ["ct"]) is None


def test_extract_js_object_and_keys():
    page = "x; window.cgiDataNew = { a: '}{', nick_name: 'Hi\\x20there', inner: { b: 1 } }; y"
    obj = jsvars.extract_js_object(page, "window.cgiDataNew")
    assert obj.startswith("{") and obj.endswith("}")
    assert jsvars.find_obj_key(obj, ["nick_name"]) == "Hi there"


def test_top_level_items_ignores_nested():
    arr = "[ { cdn_url: 'A', watermark_info: { cdn_url: 'W' } }, { cdn_url: 'B' } ]"
    items = jsvars.top_level_items(arr)
    assert len(items) == 2
    assert "'A'" in items[0] and "'W'" not in items[0]


def test_render_line_breaks_and_lists():
    from wxfetch.render import render_html

    md, _ = render_html("<p>a<br>b<br><br>c</p>")
    assert md == "a  \nb\n\nc"
    txt, _ = render_html("<p>a<br>b</p>", plain=True)
    assert txt == "a\nb"
    md, _ = render_html("<ol><li>one<ul><li>x</li><li>y</li></ul></li><li>two</li></ol>")
    assert md == "1. one\n\n   - x\n   - y\n2. two"
    md, _ = render_html("<blockquote><p>q1<br>q2</p></blockquote>")
    assert md == "> q1  \n> q2"
    md, _ = render_html("<h2>t<br>u</h2><p><br></p><p>only</p>")
    assert md == "## t u\n\nonly"
