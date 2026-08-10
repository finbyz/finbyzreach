frappe.pages["email-template-builder"].on_page_load = function (wrapper) {
	if (wrapper.dataset.builderRedirecting) return;
	wrapper.dataset.builderRedirecting = "1";
	const template_name = frappe.get_route()[1];
	if (!template_name) {
		frappe.set_route("List", "Email Template");
		return;
	}
	window.location.replace(`/builder?template=${encodeURIComponent(template_name)}`);
};
