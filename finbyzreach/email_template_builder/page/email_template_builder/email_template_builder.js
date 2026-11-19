// Keep the existing React application inside Desk so the workspace sidebar stays mounted.
frappe.pages["email-template-builder"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Email designer"), single_column: true});
	page.main.addClass("email-builder-desk");
	const frame = document.createElement("iframe");
	frame.className = "email-builder-desk-frame";
	frame.title = __("Visual email designer");
	page.main.append(frame);
	wrapper.email_builder = {page, frame};
	const backToList = () => {
		const builder = wrapper.email_builder;
		if (builder.listHref) frappe.set_route(builder.listHref);
		else frappe.set_route("List", builder.doctype || "Email Template");
	};
	page.set_secondary_action(__("Close"), backToList);
	frame.addEventListener("load", () => {
		syncThemeToFrame(frame);
		// The editor's Back button should navigate the outer Desk, never nest Desk in the frame.
		frame.contentDocument?.addEventListener("click", event => {
			if (!event.target.closest?.(".builder-back-button")) return;
			event.preventDefault();
			backToList();
		});
	});

	if (typeof document !== "undefined" && typeof MutationObserver !== "undefined" && !wrapper.theme_observer && document.documentElement) {
		const observer = new MutationObserver(() => {
			syncThemeToFrame(wrapper.email_builder?.frame);
		});
		observer.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme", "data-theme-mode"],
		});
		wrapper.theme_observer = observer;
	}

	if (typeof window !== "undefined" && window.matchMedia && !wrapper.media_listener) {
		const mq = window.matchMedia("(prefers-color-scheme: dark)");
		const handler = () => syncThemeToFrame(wrapper.email_builder?.frame);
		mq.addEventListener("change", handler);
		wrapper.media_listener = { mq, handler };
	}
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
	// Back links open the list inside the sidebar this builder was launched from.
	builder.listHref = listInSidebar(doctype === "Email Template Master" ? "email-template-master" : "email-template", sidebar);
	builder.page.set_breadcrumbs([
		{label: doctype === "Email Template Master" ? __("Templates") : __("Emails"), href: builder.listHref},
		{label: name, title: name},
	]);
	syncThemeToFrame(builder.frame);
	if (key === builder.key) return; // Keep unsaved work when returning from another Desk view.
	const open = () => {
		builder.key = key;
		builder.doctype = doctype;
		const currentTheme = getDeskTheme();
		const params = new URLSearchParams({template: name, template_doctype: doctype, theme: currentTheme});
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

function listInSidebar(slug, sidebar) {
	return sidebar && frappe.boot?.module_sidebars?.[sidebar]
		? `/desk/${frappe.router.shell_slug(sidebar)}/${slug}`
		: `/desk/${slug}`;
}

function getDeskTheme() {
	let theme = frappe.ui?.get_current_theme?.() ||
		(typeof document !== "undefined" && document.documentElement?.getAttribute?.("data-theme"));
	if (!theme) {
		const mode = typeof document !== "undefined" && document.documentElement?.getAttribute?.("data-theme-mode");
		if (mode === "dark" || mode === "light") {
			theme = mode;
		} else if (typeof window !== "undefined" && window.matchMedia) {
			theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
		}
	}
	return theme === "dark" ? "dark" : "light";
}

function syncThemeToFrame(frame) {
	if (!frame) return;
	const theme = getDeskTheme();
	const mode = (typeof document !== "undefined" && document.documentElement?.getAttribute?.("data-theme-mode")) || theme;

	try {
		const frameDoc = frame.contentDocument;
		if (frameDoc && frameDoc.documentElement) {
			frameDoc.documentElement.setAttribute("data-theme", theme);
			frameDoc.documentElement.setAttribute("data-theme-mode", mode);
			if (theme === "dark") {
				frameDoc.documentElement.classList.add("dark");
				frameDoc.body?.classList?.add("dark");
			} else {
				frameDoc.documentElement.classList.remove("dark");
				frameDoc.body?.classList?.remove("dark");
			}
		}
	} catch (e) {
		
	}

	try {
		frame.contentWindow?.postMessage({
			type: "frappe-theme-change",
			theme,
			theme_mode: mode,
		}, "*");
	} catch (e) {}
}
