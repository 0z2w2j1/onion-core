# MkDocs 使用指南

本项目使用 **MkDocs + mkdocstrings** 自动生成 API Reference 文档。

## 📦 依赖安装

```bash
pip install mkdocs mkdocstrings[python] mkdocs-material
```

或者添加到 `pyproject.toml`：

```toml
[project.optional-dependencies]
docs = [
    "mkdocs>=1.6",
    "mkdocstrings[python]>=0.24",
    "mkdocs-material>=9.5",
]
```

---

## 🚀 快速开始

### 本地预览

```bash
mkdocs serve
```

访问 http://127.0.0.1:8000 查看文档网站。

---

### 构建静态站点

```bash
mkdocs build
```

生成的文件位于 `site/` 目录，可以直接部署到 GitHub Pages、Netlify 等。

---

### 严格模式构建（推荐用于 CI）

```bash
mkdocs build --strict
```

严格模式会将所有警告视为错误，确保文档质量。

---

## 📝 添加新的 API 文档

### 方法 1：手动创建

在 `docs/api/` 目录下创建 `.md` 文件，使用 mkdocstrings 语法：

```markdown
# My Module API Reference

::: onion_core.my_module.MyClass
    options:
      show_root_heading: true
      show_source: true
      members:
        - __init__
        - my_method
```

---

### 方法 2：使用批量生成脚本

编辑 `generate_api_docs.py`，添加新模块：

```python
modules = {
    "onion_core.new_module": "api/new_module.md",
    # ...
}
```

然后运行：

```bash
python generate_api_docs.py
```

---

## ⚙️ 配置说明

### mkdocs.yml 关键配置

#### 1. mkdocstrings 插件

```yaml
plugins:
  - mkdocstrings:
      handlers:
        python:
          paths: [.]  # 搜索路径
          options:
            show_source: true  # 显示源代码链接
            show_signature_annotations: true  # 显示类型注解
            docstring_style: google  # Google 风格文档字符串
```

#### 2. 主题配置

```yaml
theme:
  name: material
  features:
    - navigation.tabs  # 顶部导航标签
    - search.highlight  # 搜索高亮
    - content.code.copy  # 代码复制按钮
```

---

## 🎨 自定义样式

### 添加自定义 CSS

创建 `docs/stylesheets/extra.css`：

```css
/* 自定义样式 */
.md-typeset h1 {
  color: #3f51b5;
}
```

在 `mkdocs.yml` 中引用：

```yaml
extra_css:
  - stylesheets/extra.css
```

---

## 📊 部署到 GitHub Pages

### 方法 1：手动部署

```bash
mkdocs gh-deploy
```

---

### 方法 2：GitHub Actions 自动部署

创建 `.github/workflows/docs.yml`：

```yaml
name: Deploy Documentation

on:
  push:
    branches:
      - main
    paths:
      - 'docs/**'
      - 'onion_core/**'
      - 'mkdocs.yml'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install mkdocs mkdocstrings[python] mkdocs-material
      
      - name: Build documentation
        run: mkdocs build --strict
      
      - name: Deploy to GitHub Pages
        run: mkdocs gh-deploy --force
```

---

## 🔧 常见问题

### Q: 如何排除私有成员？

A: 在 `mkdocs.yml` 中配置过滤器：

```yaml
plugins:
  - mkdocstrings:
      handlers:
        python:
          options:
            filters:
              - "!^_"  # 排除以 _ 开头的成员
              - "^__init__$"  # 但包含 __init__
```

---

### Q: 如何显示继承的成员？

A: 启用 `inherited_members` 选项：

```yaml
options:
  inherited_members: true
```

---

### Q: 文档字符串格式不支持？

A: mkdocstrings 支持多种格式：

- `google`（默认）
- `sphinx`
- `numpy`

在 `mkdocs.yml` 中配置：

```yaml
options:
  docstring_style: google
```

---

### Q: 如何添加交叉引用？

A: 使用方括号语法：

```markdown
See [Pipeline](api/pipeline.md) for more details.

Or reference a class: [`onion_core.Pipeline`][]
```

---

## 📚 更多资源

- [MkDocs 官方文档](https://www.mkdocs.org/)
- [mkdocstrings 文档](https://mkdocstrings.github.io/)
- [Material for MkDocs 主题](https://squidfunk.github.io/mkdocs-material/)
- [Diátaxis 文档框架](https://diataxis.fr/)

---

## 🎯 最佳实践

1. ✅ **为所有公共 API 编写文档字符串**（Google 风格）
2. ✅ **使用类型注解**（mkdocstrings 会自动显示）
3. ✅ **添加示例代码**（在文档字符串的 Examples 部分）
4. ✅ **定期运行 `mkdocs build --strict`**（确保无警告）
5. ✅ **在 CI 中自动化构建和部署**

---

**Happy Documenting! 📖✨**
