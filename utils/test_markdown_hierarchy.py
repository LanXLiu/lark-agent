from utils.markdown_hierarchy import extract_sections, iter_leaf_sections


def test_extract_sections_builds_breadcrumb():
    text = """前言段落，正文。

# 客户档案
档案说明文字。

## 基础信息
- 客户：张三
- 客户：李四

## 联系信息
电话：123

# 附录
附录正文。
"""

    sections = extract_sections(text)
    titles = [(sec.level, sec.title, sec.breadcrumb_path) for sec in sections]

    assert (0, "", "") in titles
    assert (1, "客户档案", "客户档案") in titles
    assert (2, "基础信息", "客户档案 > 基础信息") in titles
    assert (2, "联系信息", "客户档案 > 联系信息") in titles
    assert (1, "附录", "附录") in titles


def test_iter_leaf_sections_skips_pure_container_titles():
    text = """# 客户档案

## 基础信息
- 客户：张三

## 联系信息
电话：123
"""

    sections = extract_sections(text)
    leaves = iter_leaf_sections(sections)

    leaf_titles = [sec.title for sec in leaves]
    assert "客户档案" not in leaf_titles
    assert "基础信息" in leaf_titles
    assert "联系信息" in leaf_titles


def test_iter_leaf_sections_keeps_intro_with_body():
    text = """# 客户档案
档案说明文字。

## 基础信息
- 客户：张三
"""

    sections = extract_sections(text)
    leaves = iter_leaf_sections(sections)
    titles = [sec.title for sec in leaves]

    assert "客户档案" in titles
    assert "基础信息" in titles
