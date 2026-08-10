from __future__ import annotations

import html
import re

import frappe
from frappe import _
from frappe.utils import get_url, strip_html_tags

from .constants import DEFAULT_SETTINGS, LAYOUTS
from .sanitizer import sanitize_code_html, sanitize_rich_html
from .schema import validate_schema
from .tokens import compile_attribute, compile_tokens, compile_url, field_expression


SOCIAL_PLATFORMS = {
	"Facebook": {
		"label": "Facebook",
		"color": "#1877f2",
		"asset": "/assets/finbyzreach/email_builder/social/facebook.svg",
		"view_box": "0 0 320 512",
		"path": "M279.14 288l14.22-92.66h-88.91v-60.13c0-25.35 12.42-50.06 52.24-50.06H297V6.26S260.43 0 225.36 0C152.14 0 104.14 44.38 104.14 124.72v70.62H22.89V288h81.25v224h100.31V288z",
	},
	"Instagram": {
		"label": "Instagram",
		"color": "#e1306c",
		"asset": "/assets/finbyzreach/email_builder/social/instagram.svg",
		"view_box": "0 0 448 512",
		"path": "M224.1 141c-63.6 0-114.9 51.3-114.9 114.9S160.5 370.8 224.1 370.8 339 319.5 339 255.9 287.7 141 224.1 141zm0 189.6c-41.1 0-74.7-33.5-74.7-74.7s33.5-74.7 74.7-74.7 74.7 33.5 74.7 74.7-33.6 74.7-74.7 74.7zm146.4-194.3c0 14.9-12 26.8-26.8 26.8-14.9 0-26.8-12-26.8-26.8s12-26.8 26.8-26.8 26.8 12 26.8 26.8zm76.1 27.2c-1.7-35.9-9.9-67.7-36.2-93.9S352.4 35 316.5 33.3c-37-2.1-147.9-2.1-184.9 0-35.8 1.7-67.6 9.9-93.9 36.1S3.1 127.6 1.4 163.5c-2.1 37-2.1 147.9 0 184.9 1.7 35.9 9.9 67.7 36.2 93.9s58 34.5 93.9 36.2c37 2.1 147.9 2.1 184.9 0 35.9-1.7 67.7-9.9 93.9-36.2s34.5-58 36.2-93.9c2.1-37 2.1-147.8.1-184.9zM398.8 388c-7.8 19.6-22.9 34.7-42.6 42.6-29.5 11.7-99.5 9-132.1 9s-102.7 2.6-132.1-9c-19.6-7.8-34.7-22.9-42.6-42.6-11.7-29.5-9-99.5-9-132.1s-2.6-102.7 9-132.1c7.8-19.6 22.9-34.7 42.6-42.6 29.5-11.7 99.5-9 132.1-9s102.7-2.6 132.1 9c19.6 7.8 34.7 22.9 42.6 42.6 11.7 29.5 9 99.5 9 132.1s2.7 102.7-9 132.1z",
	},
	"LinkedIn": {
		"label": "LinkedIn",
		"color": "#0a66c2",
		"asset": "/assets/finbyzreach/email_builder/social/linkedin.svg",
		"view_box": "0 0 448 512",
		"path": "M100.28 448H7.4V148.9h92.88zM53.79 108.1C24.09 108.1 0 83.5 0 53.8A53.8 53.8 0 0 1 53.79 0c29.7 0 53.79 24.1 53.79 53.8 0 29.7-24.09 54.3-53.79 54.3zM447.9 448h-92.68V302.4c0-34.7-.7-79.2-48.29-79.2-48.3 0-55.69 37.7-55.69 76.7V448h-92.78V148.9h89.08v40.8h1.3c12.4-23.5 42.69-48.3 87.88-48.3 94 0 111.28 61.9 111.28 142.3V448z",
	},
	"YouTube": {
		"label": "YouTube",
		"color": "#ff0000",
		"asset": "/assets/finbyzreach/email_builder/social/youtube.svg",
		"view_box": "0 0 576 512",
		"path": "M549.7 124.1c-6.3-23.7-24.9-42.3-48.6-48.6C458.2 64 288 64 288 64S117.8 64 74.9 75.5c-23.7 6.3-42.3 24.9-48.6 48.6C14.8 167 14.8 256 14.8 256s0 89 11.5 131.9c6.3 23.7 24.9 42.3 48.6 48.6C117.8 448 288 448 288 448s170.2 0 213.1-11.5c23.7-6.3 42.3-24.9 48.6-48.6C561.2 345 561.2 256 561.2 256s0-89-11.5-131.9zM232 337.6V174.4L374.6 256 232 337.6z",
	},
	"X": {
		"label": "X",
		"color": "#111827",
		"asset": "/assets/finbyzreach/email_builder/social/x.svg",
		"view_box": "0 0 512 512",
		"path": "M389.2 48h70.6L305.6 224.2 487 464H345L233.7 318.6 106.5 464H35.8L200.7 275.5 26.8 48H172.4L272.9 180.9 389.2 48zM364.4 421.8h39.1L151.1 88h-42z",
	},
	"TikTok": {
		"label": "TikTok",
		"color": "#111827",
		"asset": "/assets/finbyzreach/email_builder/social/tiktok.svg",
		"view_box": "0 0 24 24",
		"path": "M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.05.86.14V9.4a6.32 6.32 0 0 0-.86-.06 6.34 6.34 0 1 0 6.34 6.34V8.75a8.16 8.16 0 0 0 4.77 1.53z",
	},
	"WhatsApp": {
		"label": "WhatsApp",
		"color": "#25d366",
		"asset": "/assets/finbyzreach/email_builder/social/whatsapp.svg",
		"view_box": "0 0 24 24",
		"path": "M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.39-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.92-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.07c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.63.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2.01-1.41.25-.69.25-1.29.17-1.41-.07-.13-.27-.2-.57-.35zM12.05 21.79h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88 9.89-9.88 2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 0 1 2.89 6.99c0 5.45-4.44 9.88-9.88 9.88zM20.46 3.49A11.82 11.82 0 0 0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.31-1.65a11.88 11.88 0 0 0 5.68 1.45h.01c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.16-3.49-8.42z",
	},
	"Website": {
		"label": "Website",
		"color": "#475569",
		"asset": "/assets/finbyzreach/email_builder/social/website.svg",
		"view_box": "0 0 24 24",
		"path": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.93 6h-3.04a15.54 15.54 0 0 0-1.1-3.02A8.04 8.04 0 0 1 18.93 8zM12 4.04c.83 1.2 1.48 2.53 1.88 3.96h-3.76A13.7 13.7 0 0 1 12 4.04zM4.26 14a8.2 8.2 0 0 1 0-4h3.43a16.8 16.8 0 0 0 0 4zm.81 2h3.04c.27 1.07.64 2.08 1.1 3.02A8.04 8.04 0 0 1 5.07 16zm3.04-8H5.07a8.04 8.04 0 0 1 4.14-3.02A15.54 15.54 0 0 0 8.11 8zM12 19.96A13.7 13.7 0 0 1 10.12 16h3.76A13.7 13.7 0 0 1 12 19.96zM14.31 14H9.69a14.7 14.7 0 0 1 0-4h4.62a14.7 14.7 0 0 1 0 4zm.48 5.02c.46-.94.83-1.95 1.1-3.02h3.04a8.04 8.04 0 0 1-4.14 3.02zM16.31 14a16.8 16.8 0 0 0 0-4h3.43a8.2 8.2 0 0 1 0 4z",
	},
}

def _social_platform(platform):
	return SOCIAL_PLATFORMS.get(platform or "Website", SOCIAL_PLATFORMS["Website"])


def _style(**values):
	return ";".join(f"{key.replace('_', '-')}:{value}" for key, value in values.items() if value not in (None, ""))


def _spacing(spacing):
	spacing = spacing or {}
	return " ".join(spacing.get(side, "0px") for side in ("top", "right", "bottom", "left"))


def _has_spacing(spacing):
	return any(value not in (None, "", "0", "0px") for value in (spacing or {}).values())


def _block_style(block, settings, include_border=True, include_width=True):
	style = block.get("style") or {}
	padding = _spacing(style.get("padding"))
	width = style.get("width") if include_width else None
	align = style.get("align")
	margin_left = "auto" if width and align in {"center", "right"} else None
	margin_right = "auto" if width and align == "center" else "0" if width and align == "right" else None
	values = {
		"background-color": style.get("background") or "transparent",
		"padding": padding,
		"color": style.get("color") or style.get("font_color") or settings["text_color"],
		"font-family": style.get("font_family") or settings["font_family"],
		"font-size": style.get("font_size") or settings["font_size"],
		"font-weight": style.get("font_weight"),
		"font-style": style.get("font_style"),
		"text-align": align,
		"line-height": style.get("line_height"),
		"text-decoration": style.get("text_decoration"),
		"width": width,
		"height": style.get("height"),
		"max-width": "100%" if width else None,
		"margin-left": margin_left,
		"margin-right": margin_right,
	}
	if include_border:
		values.update(
			{
				"border-width": style.get("border_width"),
				"border-color": style.get("border_color"),
				"border-style": style.get("border_style") if style.get("border_width") else None,
				"border-radius": style.get("radius"),
			}
		)
	return _style(**values)


def _section_style(section, settings):
	style = _block_style(section, settings)
	padding = (section.get("style") or {}).get("padding") or {}
	if not _has_spacing(padding) and settings.get("section_padding") not in (None, "", "0", "0px"):
		style = f'{style};padding:{settings["section_padding"]}'
	return style


def _margin_wrapper(block, inner):
	margin = (block.get("style") or {}).get("margin") or {}
	if not _has_spacing(margin):
		return inner
	return (
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
		f'<tr><td style="padding:{_spacing(margin)};">{inner}</td></tr></table>'
	)


def _condition_expression(condition):
	value = frappe.as_json(str(condition.get("value") or ""))
	field = field_expression(condition["fieldname"], "")
	op = condition["operator"]
	if op == "empty":
		return f"not ({field})"
	if op == "not_empty":
		return f"({field})"
	if op == "equals":
		return f"({field}) | string == {value}"
	if op == "not_equals":
		return f"({field}) | string != {value}"
	if op == "contains":
		return f"{value} in (({field}) | string)"
	return f"{value} not in (({field}) | string)"


def _conditions(visibility, inner, wrapper="div"):
	classes = []
	device = visibility.get("device")
	if device == "mobile":
		classes.append("etb-mobile-only")
	elif device == "desktop":
		classes.append("etb-desktop-only")
	class_attr = f' class="{" ".join(classes)}"' if classes else ""
	if wrapper is None and class_attr and inner.startswith("<tr"):
		inner = inner.replace("<tr", f"<tr{class_attr}", 1)
	elif wrapper is not None:
		inner = f"<{wrapper}{class_attr}>{inner}</{wrapper}>"
	conditions = visibility.get("conditions") or []
	if not conditions:
		return inner
	joiner = " and " if visibility.get("match", "all") == "all" else " or "
	expression = joiner.join(f"({_condition_expression(condition)})" for condition in conditions)
	return f"{{% if {expression} %}}{inner}{{% endif %}}"


def _absolute_file_url(value):
	value = str(value or "")
	if value.startswith("/"):
		return get_url(value)
	return value


RELATIVE_HTML_URL = re.compile(r'(\b(?:href|src)\s*=\s*")(/[^"\s]*)', re.IGNORECASE)


def _absolute_embedded_urls(value):
	return RELATIVE_HTML_URL.sub(lambda match: f'{match.group(1)}{get_url(match.group(2))}', str(value or ""))


def _image_css(content, block):
	style = block.get("style") or {}
	width = f'{int(content["width"])}px' if content.get("width") else "100%"
	height = f'{int(content["height"])}px' if content.get("height") and content.get("preserve_aspect_ratio") is False else "auto"
	align = style.get("align") or "left"
	return _style(
		display="block",
		width=width,
		max_width="100%",
		height=height,
		border="0",
		margin_left="auto" if align in {"center", "right"} else None,
		margin_right="auto" if align == "center" else "0" if align == "right" else None,
		border_radius=style.get("radius"),
	)


def _compile_block(block, settings, normalized=False):
	type_ = block["type"]
	content = block.get("content") or {}
	style = _block_style(block, settings, include_border=type_ != "button", include_width=type_ != "divider")
	inner = ""
	if type_ == "text":
		rich_html = content.get("html") if normalized else sanitize_rich_html(content.get("html"))
		sanitized = _absolute_embedded_urls(rich_html)
		inner = f'<div style="{style}">{compile_tokens(sanitized, "e")}</div>'
	elif type_ == "image":
		src = _absolute_file_url(content.get("src"))
		if not src:
			return ""
		align = (block.get("style") or {}).get("align", "left")
		attrs = [f'src="{compile_url(src)}"', f'alt="{compile_attribute(content.get("alt", ""))}"', 'border="0"']
		if content.get("width"):
			attrs.append(f'width="{int(content["width"])}"')
		if content.get("height") and content.get("preserve_aspect_ratio") is False:
			attrs.append(f'height="{int(content["height"])}"')
		image = f'<img {" ".join(attrs)} style="{_image_css(content, block)}">'
		if content.get("href"):
			image = f'<a href="{compile_url(_absolute_file_url(content["href"]))}" style="text-decoration:none;border:0;">{image}</a>'
		wrapper_style = style if "text-align:" in style else f"{style};text-align:{align}"
		inner = f'<div style="{wrapper_style}">{image}</div>'
	elif type_ == "button":
		block_style = block.get("style") or {}
		href = compile_url(_absolute_file_url(content.get("href") or "#"))
		background = block_style.get("button_background") or settings["button_background"]
		text_color = block_style.get("button_text_color") or settings["button_text_color"]
		button_style = _style(
			color=text_color,
			font_family=block_style.get("font_family") or settings["font_family"],
			font_size=block_style.get("font_size") or settings["font_size"],
			font_weight=block_style.get("font_weight") or "bold",
			font_style=block_style.get("font_style"),
			text_decoration=block_style.get("text_decoration") or "none",
			padding=f'{block_style.get("button_padding_y") or "12px"} {block_style.get("button_padding_x") or "22px"}',
			border_radius=block_style.get("radius") or settings["button_radius"],
			display="block",
			text_align="center",
		)
		fills_wrapper = content.get("full_width") or bool(block_style.get("width"))
		width_style = block_style.get("width") or ("100%" if content.get("full_width") else "")
		width = f' width="{html.escape(width_style, quote=True)}" style="width:{html.escape(width_style, quote=True)};max-width:100%;"' if fills_wrapper else ""
		align = block_style.get("align", "left")
		border = ""
		if block_style.get("border_color") and block_style.get("border_color") != "transparent":
			border = f'border:{block_style.get("border_width") or "1px"} {block_style.get("border_style") or "solid"} {block_style["border_color"]};'
		td_style = f'background-color:{background};border-radius:{block_style.get("radius") or settings["button_radius"]};{border}'
		label = compile_attribute(content.get("text", "Button"))
		inner = (
			f'<div style="{style}"><table role="presentation" align="{align}"{width} cellpadding="0" cellspacing="0" border="0">'
			f'<tr><td bgcolor="{html.escape(background, quote=True)}" style="{td_style}" align="center">'
			f'<a href="{href}" style="{button_style}">{label}</a></td></tr></table></div>'
		)
	elif type_ == "divider":
		block_style = block.get("style") or {}
		align = block_style.get("align") or "center"
		line = _style(
			border_top=f'{content.get("thickness", 1)}px {content.get("style", "solid")} {block_style.get("border_color", settings["link_color"])}',
			width=block_style.get("width") or "100%",
			margin_top="0",
			margin_bottom="0",
			margin_left="auto" if align in {"center", "right"} else "0",
			margin_right="auto" if align == "center" else "0" if align == "right" else "auto",
		)
		inner = f'<div style="{style}"><div style="{line}"></div></div>'
	elif type_ == "spacer":
		height = int(content.get("height", 24))
		inner = f'<div aria-hidden="true" style="height:{height}px;line-height:{height}px;font-size:1px;{style}">&nbsp;</div>'
	elif type_ == "social":
		items = []
		size = int(content.get("icon_size") or 20)
		display = content.get("display") if content.get("display") in {"icon", "text", "both"} else "icon"
		shape = content.get("icon_shape") if content.get("icon_shape") in {"square", "rounded", "circle"} else "circle"
		item_spacing = int(content.get("item_spacing") if content.get("item_spacing") is not None else 8)
		style_color = (block.get("style") or {}).get("color")
		text_color = (block.get("style") or {}).get("font_color") or settings["link_color"]
		radius = "50%" if shape == "circle" else f"{max(3, round(size * 0.22))}px" if shape == "rounded" else "0"
		inner_size = max(8, int(size * 0.56))
		inset = max(0, int((size - inner_size) / 2))
		social_items = content.get("items", [])
		for index, item in enumerate(social_items):
			meta = _social_platform(item.get("platform", "Website"))
			accessible = html.escape(str(item.get("label") or meta["label"]), quote=True)
			color = style_color or meta["color"]
			href = compile_url(_absolute_file_url(item.get("href") or "#"))
			label = compile_attribute(item.get("label") or meta["label"])
			icon = ""
			if display != "text":
				asset = html.escape(get_url(meta["asset"]), quote=True)
				img = f'<img src="{asset}" width="{inner_size}" height="{inner_size}" alt="" border="0" style="display:block;width:{inner_size}px;height:{inner_size}px;border:0;outline:none;text-decoration:none;margin:{inset}px auto 0 auto;" />'
				icon = f'<span style="display:inline-block;width:{size}px;height:{size}px;border-radius:{radius};background:{color};text-align:center;vertical-align:middle;line-height:{size}px;">{img}</span>'
			text = ""
			if display != "icon":
				text = f'<span style="display:inline-block;{"margin-left:6px;" if display == "both" else ""}color:{text_color};vertical-align:middle;">{label}</span>'
			margin = item_spacing if index < len(social_items) - 1 else 0
			items.append(
				f'<a href="{href}" aria-label="{accessible}" title="{accessible}" '
				f'style="display:inline-block;margin-right:{margin}px;color:{text_color};text-decoration:none;vertical-align:middle;">{icon}{text}</a>'
			)
		inner = f'<div style="{style}">{"".join(items)}</div>'
	elif type_ == "preview_url":
		label = compile_attribute(content.get("text"))
		inner = f'{{% if email_preview_url is defined and email_preview_url %}}<div style="{style}"><a href="{{{{ email_preview_url | email_builder_safe_url | e }}}}" style="color:{settings["link_color"]};">{label}</a></div>{{% endif %}}'
	elif type_ == "code":
		code_html = content.get("html", "") if normalized else sanitize_code_html(content.get("html", ""))
		sanitized = _absolute_embedded_urls(code_html)
		inner = f'<div style="{style}">{compile_tokens(sanitized, "e")}</div>'
	return _margin_wrapper(block, inner)


def _plain_block(block):
	content = block.get("content") or {}
	if block["type"] in {"text", "code"}:
		return compile_tokens(strip_html_tags(content.get("html") or ""), "email_builder_text").strip()
	if block["type"] == "image":
		return compile_tokens(content.get("alt") or "", "email_builder_text").strip()
	if block["type"] == "button":
		label = compile_tokens(content.get("text") or "Button", "email_builder_text")
		return f"{label} ({compile_url(_absolute_file_url(content.get('href') or '#'))})"
	if block["type"] == "social":
		return "\n".join(
			f"{item.get('label') or item['platform']}: {compile_url(_absolute_file_url(item.get('href') or '#'))}"
			for item in content.get("items", [])
		)
	if block["type"] == "preview_url":
		label = compile_tokens(content.get("text") or "View this email in your browser", "email_builder_text")
		return f'{{% if email_preview_url is defined and email_preview_url %}}{label}: {{{{ email_preview_url | email_builder_safe_url }}}}{{% endif %}}'
	return ""


def _hex_rgb(value):
	value = str(value or "")
	if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
		value = "#" + "".join(character * 2 for character in value[1:])
	if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
		return None
	return tuple(int(value[index : index + 2], 16) / 255 for index in (1, 3, 5))


def _contrast_ratio(foreground, background):
	colors = (_hex_rgb(foreground), _hex_rgb(background))
	if not all(colors):
		return None
	def luminance(rgb):
		channels = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in rgb]
		return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
	first, second = sorted((luminance(colors[0]), luminance(colors[1])), reverse=True)
	return (first + 0.05) / (second + 0.05)


def _validation_issues(schema, html_output):
	settings = schema["settings"]
	issues = []
	def warning(code, message, node_id=None):
		issues.append({"severity": "warning", "code": code, "node_id": node_id, "message": message})
	for section in schema["sections"]:
		column_widths = section.get("column_widths") or LAYOUTS[section["layout"]]
		for index, column in enumerate(section["columns"]):
			if settings["content_width"] * column_widths[index] / 100 < 170:
				warning("narrow_column", _("A column in section {0} may be too narrow on desktop.").format(section["id"]), section["id"])
			for block in column["blocks"]:
				content = block["content"]
				if block["type"] == "image":
					if not content.get("src"):
						warning("missing_image", _("Choose an image before sending."), block["id"])
					if not content.get("alt") and not content.get("decorative"):
						warning("missing_alt", _("Add image alt text or mark the image decorative."), block["id"])
				if block["type"] == "button" and not content.get("href"):
					warning("missing_button_url", _("Add a destination to the button before sending."), block["id"])
				if block["type"] == "social" and any(not item.get("href") for item in content.get("items", [])):
					warning("missing_social_url", _("One or more social links have no destination."), block["id"])
				if block["type"] == "button":
					style = block.get("style") or {}
					ratio = _contrast_ratio(style.get("button_text_color") or settings["button_text_color"], style.get("button_background") or settings["button_background"])
					if ratio is not None and ratio < 4.5:
						warning("button_contrast", _("Button text contrast is below 4.5:1."), block["id"])
	ratio = _contrast_ratio(settings["text_color"], settings["content_background"])
	if ratio is not None and ratio < 4.5:
		warning("text_contrast", _("Default text contrast is below 4.5:1."))
	if len(html_output.encode()) > 90_000:
		warning("html_size", _("Compiled HTML exceeds 90 KB and may be clipped by some email clients."))
	return issues


def compile_schema(value, preheader="", normalized=False) -> dict:
	"""Compile either a raw schema or a trusted schema already normalized by validate_schema."""
	schema = value if normalized else validate_schema(value)
	settings = schema["settings"]
	width = settings["content_width"]
	body = []
	plain_sections = []
	css = (
		f'<style>.etb-content a{{color:{settings["link_color"]};text-decoration:{settings["link_decoration"]}}}'
		".etb-mobile-only{display:none!important;max-height:0!important;overflow:hidden!important;mso-hide:all!important}"
		".etb-desktop-only{display:block!important}tr.etb-desktop-only{display:table-row!important}"
		"@media only screen and (max-width:600px){.etb-desktop-only{display:none!important;max-height:0!important;overflow:hidden!important}"
		".etb-mobile-only{display:block!important;max-height:none!important;overflow:visible!important}tr.etb-mobile-only{display:table-row!important}"
		"table.etb-content{width:100%!important}.etb-stack .etb-column,.etb-stack-reverse .etb-column{display:block!important;width:100%!important;max-width:100%!important}"
		".etb-no-stack .etb-column{display:table-cell!important}.etb-stack-reverse>tbody>tr{display:flex!important;flex-direction:column-reverse!important;width:100%!important}}</style>"
	)
	for section in schema["sections"]:
		columns = []
		plain_columns = []
		vertical_align = section.get("vertical_align", "top")
		column_widths = section.get("column_widths") or LAYOUTS[section["layout"]]
		for index, column in enumerate(section["columns"]):
			width_percent = column_widths[index]
			blocks = "".join(
				_conditions(block["visibility"], _compile_block(block, settings, normalized=normalized))
				for block in column["blocks"]
			)
			plain_columns.append("\n\n".join(filter(None, (_plain_block(block) for block in column["blocks"]))))
			column_style = _block_style(column, settings)
			columns.append(f'<td class="etb-column" valign="{vertical_align}" width="{width_percent:.3f}%" style="width:{width_percent:.3f}%;vertical-align:{vertical_align};{column_style}">{blocks}</td>')
		stack_mode = section.get("mobile_stack") or "stack"
		stack_class = {"none": "etb-no-stack", "reverse": "etb-stack-reverse"}.get(stack_mode, "etb-stack")
		section_inner = f'<table role="presentation" class="etb-layout {stack_class}" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{"".join(columns)}</tr></table>'
		section_margin = (section.get("style") or {}).get("margin") or {}
		section_style = _section_style(section, settings)
		if _has_spacing(section_margin):
			section_inner = (
				'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
				f'<tr><td style="{section_style}">{section_inner}</td></tr></table>'
			)
			section_row = f'<tr><td style="padding:{_spacing(section_margin)};">{section_inner}</td></tr>'
		else:
			section_row = f'<tr><td style="{section_style}">{section_inner}</td></tr>'
		body.append(_conditions(section["visibility"], section_row, wrapper=None))
		plain_sections.append("\n\n".join(filter(None, plain_columns)))
	preheader_html = f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{compile_attribute(preheader)}</div>' if preheader else ""
	html_output = f'<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">{css}</head><body style="margin:0;padding:0;background-color:{settings["body_background"]};font-family:{settings["font_family"]};color:{settings["text_color"]};"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{settings["body_background"]};"><tr><td align="center">{preheader_html}<table role="presentation" class="etb-content" width="{width}" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:{width}px;background-color:{settings["content_background"]};">{"".join(body)}</table></td></tr></table></body></html>'
	issues = _validation_issues(schema, html_output)
	return {
		"html": html_output,
		"plain_text": "\n\n".join(filter(None, plain_sections)),
		"schema": schema,
		"issues": issues,
		"warnings": [issue["message"] for issue in issues if issue["severity"] == "warning"],
		"bytes": len(html_output.encode()),
	}
