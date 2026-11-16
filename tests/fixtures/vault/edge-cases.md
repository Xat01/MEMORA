---
title: "Edge Cases Test"
tags: [test, edge-cases, unicode, special-chars]
created: 2024-03-01
complex_object:
  nested: true
  array: [1, 2, 3]
  null_value:
---

# Edge Cases Test

Testing various edge cases for parsing.

## Unicode Content

中文内容测试
日本語のテスト
한국어 테스트
العربية
🎉 Emoji support 🎉

## Special Characters

| Character | Description |
|-----------|-------------|
| `&` | Ampersand |
| `<` | Less than |
| `>` | Greater than |
| `"` | Double quote |
| `'` | Single quote |
| `\` | Backslash |

## Malformed Markdown

Unclosed code block
```
This code block never closes

Heading without space#NoSpace
##Double hash no space
### Triple###NoSpace

Broken link [text](missing paren
Broken image ![alt](missing paren

Table without header
| cell1 | cell2 |
| cell3 | cell4 |

List without spacing
-Item 1
-Item 2

## Very Long Heading That Goes On And On And On And On And On And On And On And On And On And On And On

Paragraph with    excessive    whitespace    between    words.

Trailing spaces   
on lines   
   
   
Multiple blank lines above.

## Code with Special Content

```python
def problematic_function():
    # This has "quotes" and 'apostrophes'
    path = "C:\Users\name\file.txt"  # Windows path
    regex = r"\d+\.\d+"  # Raw string
    unicode_str = "Hello \u0041 World"
    return path, regex, unicode_str
```

```javascript
// JavaScript with template literals
const msg = `Hello ${name}`;
const path = `C:\\Users\\${user}\\file.txt`;
const regex = /\d+\.\d+/g;
```

## Nested Lists

1. First level
   - Second level
     - Third level
       - Fourth level
         - Fifth level
   - Back to second
2. Another first level
   1. Nested numbered
      1. Deep nested

## Blockquotes

> This is a blockquote
> with multiple lines
>
> > Nested blockquote
> > with more content
>
> Back to first level

## Horizontal Rules

---

***

___

## Footnotes

Here is a footnote reference[^1].

[^1]: This is the footnote content.

## Definition Lists

Term 1
: Definition 1

Term 2
: Definition 2a
: Definition 2b

## Task Lists

- [x] Completed task
- [ ] Pending task
- [ ] Another pending task
  - [x] Sub-task done
  - [ ] Sub-task pending