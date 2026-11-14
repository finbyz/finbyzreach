// Keep the existing React application inside Desk so the workspace sidebar stays mounted.
frappe.pages["email-template-builder"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Email designer"), single_column: true});
	page.main.addClass("email-builder-desk");
	const frame = document.createElement("iframe");
	frame.className = "email-builder-desk-frame";
	frame.title = __("Visual email designer");
	page.main.append(frame);
	wrapper.email_builder = {page, frame};
	page.set_secondary_action(__("Close"), () => {
		frappe.set_route("List", wrapper.email_builder.doctype || "Email Template");
	});
	frame.addEventListener("load", () => {
		// The editor's Back button should navigate the outer Desk, never nest Desk in the frame.
		frame.contentDocument?.addEventListener("click", event => {
			if (!event.target.closest?.(".builder-back-button")) return;
			event.preventDefault();
			frappe.set_route("List", wrapper.email_builder.doctype);
		});
	});
};

frappe.pages["email-template-builder"].on_page_show = function (wrapper) {
	const route = frappe.get_route();
	const name = route[1];
	// A Page belongs to its own module; restore the launching workspace using the native sidebar API.
	const sidebar = route[3];
	if (sidebar && frappe.boot?.module_sidebars?.[sidebar]) frappe.app?.sidebar?.select_shell(sidebar);
	const doctype = route[2] === "Email Template Master" ? "Email Template Master" : "Email Template";
	if (!name) {
		frappe.set_route("List", doctype);
		return;
	}
	const builder = wrapper.email_builder;
	const key = JSON.stringify([doctype, name]);
	builder.page.set_title(name);
	builder.page.set_breadcrumbs([
		{label: doctype === "Email Template Master" ? __("Templates") : __("Emails"),
			href: doctype === "Email Template Master" ? "/app/email-template-master" : "/app/email-template"},
		{label: name, title: name},
	]);
	if (key === builder.key) return; // Keep unsaved work when returning from another Desk view.
	const open = () => {
		builder.key = key;
		builder.doctype = doctype;
		const params = new URLSearchParams({template: name, template_doctype: doctype});
		builder.frame.src = `/builder?${params.toString()}`;
	};
	if (builder.key && !builder.frame.contentWindow.dispatchEvent(new Event("beforeunload", {cancelable: true}))) {
		frappe.confirm(__("This email has unsaved changes. Open another email and discard those changes?"), open, () => {
			const [previousDoctype, previousName] = JSON.parse(builder.key);
			frappe.set_route("email-template-builder", previousName, previousDoctype, sidebar || "");
		});
	} else {
		open();
	}
};
