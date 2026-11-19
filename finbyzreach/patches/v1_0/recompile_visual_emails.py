"""Rebuild stored visual e-mails with the current compiler (EM-15 dark mode and Outlook markup, alt text).

The sent HTML is compiled when an e-mail is saved, so compiler fixes did not reach e-mails
nobody reopened. This is the same as opening and saving each visual e-mail once.
"""


def execute():
	from finbyzreach.email_template_builder.shared_sections import recompile_linked_templates

	recompile_linked_templates()
