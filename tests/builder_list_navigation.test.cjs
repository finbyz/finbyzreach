const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../finbyzreach/public/js');

function environment() {
    const preferences = {};
    let failSave = false, messages = 0;
    const frappe = {
        builder_list_navigation: {}, listview_settings: {},
        email_template_builder: {}, provide() {},
        user: {has_role: () => true},
        app: {sidebar: {current_module: 'Marketing'}},
        router: {slug: value => value.toLowerCase().replaceAll(' ', '-')},
        get_user_settings: doctype => preferences[doctype] || {},
        model: {user_settings: {async save(doctype, key, value) {
            if (failSave) throw Error('Failed');
            preferences[doctype] = {...preferences[doctype], [key]: value};
        }}},
        msgprint() { messages++; },
    };
    const context = {frappe, __: value => value};
    vm.runInNewContext(fs.readFileSync(path.join(root, 'builder_list_navigation.js'), 'utf8'), context);
    return {frappe, context, preferences, fail() { failSave = true; }, messages: () => messages};
}

for (const [doctype, file, builder] of [
    ['Email Template', 'email_template_list.js', 'email-template-builder'],
    ['Email Template Master', 'email_template_master_list.js', 'email-template-builder'],
    ['Form', 'form_list.js', 'forms-pro-designer'],
    ['Automation Workflow', 'automation_workflow_list.js', 'automation-workflow-designer'],
]) {
    test(`${doctype}: builder defaults on; toggle persists off and restores normal form navigation`, async () => {
        const env = environment();
        vm.runInNewContext(fs.readFileSync(path.join(root, 'doctype_list_js', file), 'utf8'), env.context);
        const settings = env.frappe.listview_settings[doctype];
        const doc = {name: 'Document / 1'};
        assert.ok(settings.get_form_link(doc).startsWith(`/app/${builder}/Document%20%2F%201/`));
        let click, refreshes = 0, mounts = 0;
        const button = {text(value) { this.label = value; return this; }, attr() {return this;}, prop(key, value) { this[key] = value; return this; }};
        const list = {doctype, page: {add_inner_button(label, action) { click = action; mounts++; return button; }}, async refresh() { refreshes++; }};
        env.frappe.builder_list_navigation.mount(list);
        env.frappe.builder_list_navigation.mount(list);
        assert.equal(mounts, 1);
        assert.equal(button.label, 'Open in builder: On');
        await click();
        assert.equal(env.preferences[doctype].open_in_builder, false);
        assert.equal(button.label, 'Open in builder: Off');
        assert.equal(settings.get_form_link(doc), `/desk/${env.frappe.router.slug(doctype)}/Document%20%2F%201`);
        assert.equal(env.frappe.get_user_settings('Unrelated').open_in_builder, undefined);
        await click();
        assert.ok(settings.get_form_link(doc).startsWith(`/app/${builder}/`));
        assert.equal(refreshes, 2);
        env.fail();
        await click();
        assert.equal(button.disabled, false);
        assert.equal(button.label, 'Open in builder: On');
        assert.equal(env.messages(), 1);
    });
}
