// Frappe reads a route that starts with "form" as its standard ["Form", doctype, name]
// spelling. Forms Pro names its DocType "Form", so the Forms list path is ["form"], and
// convert_from_standard_route called slug(undefined): every in-app click on "Forms" threw
// inside set_route and nothing opened (a full page load worked, since it skips set_route).
// A lowercase "form" whose next segment is not a DocType is already a Form DocType path.
(() => {
    const router = window.frappe?.router;
    if (!router || router.__form_doctype_guard) return;
    const original = router.convert_from_standard_route;
    router.convert_from_standard_route = function (route) {
        if (Array.isArray(route) && route[0] === "form" && this.routes?.form) {
            const next = route[1];
            const namesDoctype = typeof next === "string" && Boolean(this.routes[this.slug(next)]);
            if (!namesDoctype) return route;
        }
        return original.call(this, route);
    };
    router.__form_doctype_guard = true;
})();
