const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = path.join(__dirname, '../finbyzreach');

for (const [doctype, file, active] of [
    ['Email Template', 'public/js/doctype_list_js/email_template_list.js', 'emails'],
    ['Email Template Master', 'public/js/doctype_list_js/email_template_master_list.js', 'templates'],
]) {
    test(`${doctype} waits for navigation assets when an existing Desk session lacks the helper`, () => {
        let callback, requested, mounted;
        const frappe = {
            listview_settings: {}, email_template_builder: {},
            provide() {}, user: {has_role: () => false},
            reach_folder_sidebar: {setup() {}},
            require(paths, ready) { requested = paths; callback = ready; },
        };
        vm.runInNewContext(fs.readFileSync(path.join(base, file), 'utf8'), {frappe, __: x => x});
        const page = {};
        const list = {page, _template_library_actions_added: true};
        assert.doesNotThrow(() => frappe.listview_settings[doctype].onload(list));
        assert.equal(mounted, undefined);
        assert.deepEqual(Array.from(requested), [
            '/assets/finbyzreach/css/email_workspace.css',
            '/assets/finbyzreach/js/email_workspace.js',
        ]);
        // Frappe's extension detection requires paths without query parameters.
        frappe.email_workspace = {mount(p, tab) { mounted = {p, tab}; }};
        callback();
        assert.equal(mounted.p, page);
        assert.equal(mounted.tab, active);
    });
}

test('statistics waits for navigation assets before mounting', () => {
    let callback, mounted;
    const page = {main: {addClass() {}}, set_primary_action() {}, set_title() {}};
    const frappe = {
        pages: {'email-campaign-report': {}},
        ui: {make_app_page: () => page},
        require(paths, ready) { callback = ready; },
    };
    const code = fs.readFileSync(path.join(base, 'finbyzreach/page/email_campaign_report/email_campaign_report.js'), 'utf8');
    const context = {frappe, __: x => x};
    vm.runInNewContext(code + '\nglobalThis.Report = EmailCampaignReport;', context);
    for (const method of ['render', 'makeControls', 'bind', 'applyRoute']) context.Report.prototype[method] = () => {};
    assert.doesNotThrow(() => new context.Report({}));
    frappe.email_workspace = {mount(p, tab) { mounted = {p, tab}; }};
    callback();
    assert.equal(mounted.p, page);
    assert.equal(mounted.tab, 'statistics');
});
