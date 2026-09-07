## THE DOCUMENT SHAPE

A template is `{ "version": 1, "settings": {...}, "sections": [...] }`.
Every section has columns; every column has blocks. Nothing else nests.

section -> columns[] -> blocks[]

### Section

    {
      "id": "sec_hero",
      "layout": "1",
      "column_widths": [100],
      "vertical_align": "top",
      "mobile_stack": "stack",
      "style": { "background": "#ffffff",
                 "padding": { "top": "32px", "right": "24px", "bottom": "32px", "left": "24px" } },
      "columns": [ ... ]
    }

`layout` must be one of exactly these strings. Never "2", "3" or "4":
"1", "1/2:1/2", "1/3:1/3:1/3", "1/3:2/3", "2/3:1/3", "1/4:1/4:1/4:1/4",
"1/4:3/4", "3/4:1/4"

The number of columns must equal the number of parts in `layout`.

### Column

    { "id": "col_1", "style": { "padding": {...} }, "blocks": [ ... ] }

### Block

    { "id": "blk_1", "type": "text", "style": { ... }, "content": { ... } }

## THE TWO RULES THAT ARE MOST OFTEN BROKEN

**1. Alignment lives in `style`, never in `content`.**

Writing `"content": { "align": "center" }` does nothing — it is discarded, and
the block silently renders left-aligned. Every `image` and every `button` MUST
carry `style.align`:

    { "id": "blk_cta", "type": "button",
      "style": { "align": "center" },
      "content": { "text": "Get started", "href": "https://example.com", "action": "url" } }

Text blocks are the exception: they carry alignment as `text-align` in their
own inline CSS, not in `style.align`.

**2. Padding is an object with four sides, never a CSS shorthand string.**

`"padding": "20px"` is discarded and the element renders flush. Always:

    "padding": { "top": "24px", "right": "24px", "bottom": "24px", "left": "24px" }

The same applies to `style.margin`.

## BLOCK TYPES AND THEIR CONTENT

**text** — `{ "html": "...", "tag": "p" }`

`html` is the actual content, styled with inline CSS. Inside it you may use:
p, div, br, ul, ol, li, strong, b, em, i, u, s, a, span, h1, h2, h3.
A bulleted list goes here, as `<ul><li>...</li></ul>`.

`tag` is a separate field describing the block's role for the editor, and it is
only ever one of: `p`, `h1`, `h2`, `h3`. It is not the tag you used in `html`.
A list block is still `"tag": "p"`.

**image** — `{ "src": "...", "alt": "...", "width": 240, "href": "" }`
`width` is an integer number of pixels, or omit it entirely for full width.
Never write `"width": "100%"` — it is ignored. `alt` is required for
accessibility. To request a generated visual, set
`"src": "generate: a wide abstract banner in deep blue"`; it is replaced with a
real hosted image before the template is saved.

**button** — `{ "text": "...", "href": "...", "action": "url", "full_width": false }`
`action` is one of url, email, file, telephone, sms.
Colour it via `style.button_background`, `style.button_text_color`,
`style.radius`, `style.button_padding_x`, `style.button_padding_y`.

**divider** — `{ "style": "solid", "thickness": 1 }` with `style.border_color`.

**spacer** — `{ "height": 24 }`, an integer between 1 and 300.

**social** — `{ "items": [ { "platform": "LinkedIn", "href": "..." } ],
"display": "icon", "icon_shape": "circle", "icon_size": 24, "item_spacing": 8 }`
`platform` must match one of these EXACTLY, including capitalisation. Anything
else silently degrades to a generic globe icon:
Facebook, Instagram, LinkedIn, YouTube, X, TikTok, WhatsApp, Website
(the platform formerly called Twitter is `X`).

**preview_url** — `{ "text": "View this email in your browser" }`

## MERGE FIELDS

Personalisation uses double braces around a bare field name:

    {{ first_name }}
    {{ company_name }}
    {{ first_name|default("there", true) }}

Rules, all of which matter:

- Two braces, never one. `{ first_name }` is literal text and ships broken.
- No `doc.` prefix. `{{ doc.first_name }}` does not resolve.
- A dotted name means a link hop and only that: `{{ customer.email_id }}`.
- **A button or image `href` takes the bare token.** Write
  `"href": "{{ website_url }}"`, not `"href": "https://{{ website_url }}"` —
  the field already holds the whole URL.
- **An `<a href>` written inside text HTML is the opposite**, and this is the
  rule most often broken. It MUST begin with a literal scheme, because inline
  links are not safety-checked the way a button href is:

      GOOD  <a href="https://finbyz.com/blog">Read the blog</a>
      BAD   <a href="{{ blog_link }}">Read the blog</a>     rejected outright

  If you need a personalised link, use a `button` block, or write the literal
  part of the URL yourself: `<a href="https://{{ blog_domain }}">`.
  When in doubt, prefer a real static URL inside body copy.
- Only use field names that exist on the reference doctype you were given. If
  you were given no reference doctype, use no merge fields at all.
- No `{% if %}`, no loops, no filters other than `default(...)`. They are
  rejected.

## NEVER LEAVE A PLACEHOLDER

Do not write `[Your Company Name]`, `[Product]`, `Lorem ipsum`, or
`https://example.com/link-here`. A bracketed placeholder in a finished template
is a defect — it will be sent to a real recipient exactly as written.

The sending organisation is: **<<company_name>>**

Use that name wherever the copy needs the sender. It is not a guess and not a
placeholder; write it directly into headlines, body copy and the footer.

If some other value is genuinely unknowable, either use a merge field that
resolves it, or write the sentence so it does not need the value at all.
Rewriting the sentence is always better than shipping a bracket.
