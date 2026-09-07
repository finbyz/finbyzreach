## DESIGN SYSTEM

Follow this like a house style. It is what separates a template that looks
designed from one that looks generated.

### Spacing

Use only these values: 0, 8, 16, 24, 32, 48, 64 px.

- Content sections: `padding` 32 top, 24 right, 32 bottom, 24 left.
  Horizontal insets are not optional — text touching the 600px edge is the
  single most obvious tell of an unfinished email.
- A hero image that should bleed edge-to-edge: 0 left and right, and only then.
- Between a heading and its body copy: 8 or 16.
- Between unrelated content groups: 32 or 48, via section padding.
- Prefer section padding over `spacer` blocks. Reach for a spacer only when
  you need space *inside* a column, between two blocks.

### Type

- h1 — 28–32px, line-height 1.25, weight 700
- h2 — 22–24px, line-height 1.3, weight 700
- h3 — 18px, line-height 1.4, weight 600
- body — 16px, line-height 1.6
- small print — 13–14px, line-height 1.5

Never go below 13px. Always set an explicit `line-height` on body copy; the
client default is too tight to read.

### Colour

- One accent colour, used for buttons and links only. Everything else is
  neutral. Two or more accents look like a ransom note.
- Body text at or near #1f2937 on white. Never lighter than #6b7280 for
  anything a reader must actually read.
- Button text must sit at 4.5:1 contrast or better against the button fill.
  White on a mid-tone accent is safe; white on yellow is not.
- Page background a soft neutral (#f4f5f7, #f0f4f8), content background white,
  so the 600px column reads as a card.

### Fonts

Email clients do not reliably load web fonts, so a stack whose first entry is
Montserrat or Inter renders as the fallback anyway. Use one of these directly:

    Arial, Helvetica, sans-serif
    Georgia, 'Times New Roman', serif
    'Helvetica Neue', Helvetica, Arial, sans-serif
    Tahoma, Verdana, Segoe, sans-serif

### Layout

- Content width 600. It is the only width that behaves everywhere.
- Multi-column sections are for genuinely parallel content — three features,
  two products. Never split a single line of prose across columns.
- At most 4 columns, and only for icons or very short labels. Three is the
  practical maximum for anything with a sentence in it.
- Every multi-column section keeps `mobile_stack: "stack"` so it collapses to
  one column on a phone.

### Structure

A strong template runs: header/logo, hero (image + headline + subhead), one
primary call to action, supporting content, a secondary call to action if it
earns its place, then footer with social links and an unsubscribe.

- Exactly one *primary* call to action. Repeating it lower down is fine;
  competing with it is not.
- Button labels say what happens: "Book a demo", "See your dashboard". Never
  "Click here".
- Every image needs `alt` text — a meaningful share of recipients block images,
  and the email must still make sense.
- The footer is small print: 13–14px, muted colour, and it must include an
  unsubscribe link for any marketing send.
