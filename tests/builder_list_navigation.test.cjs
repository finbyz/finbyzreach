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
        // The toggle is a switch: its state is the "is-on" class and aria-checked.
        const button = {
            attrs: {}, classes: new Set(),
            html(value) { this.markup = value; return this; },
            addClass(name) { this.classes.add(name); return this; },
            toggleClass(name, on) { on ? this.classes.add(name) : this.classes.delete(name); return this; },
            attr(key, value) { this.attrs[key] = value; return this; },
            prop(key, value) { this[key] = value; return this; },
            get on() { return this.attrs['aria-checked'] === 'true' && this.classes.has('is-on'); },
        };
        const list = {doctype, page: {add_inner_button(label, action) { click = action; mounts++; return button; }}, async refresh() { refreshes++; }};
        env.frappe.builder_list_navigation.mount(list);
        env.frappe.builder_list_navigation.mount(list);
        assert.equal(mounts, 1);
        assert.ok(button.markup.includes('Open in builder'));
        assert.equal(button.attrs.role, 'switch');
        assert.equal(button.on, true);
        await click();
        assert.equal(env.preferences[doctype].open_in_builder, false);
        assert.equal(button.on, false);
        assert.equal(settings.get_form_link(doc), `/desk/${env.frappe.router.slug(doctype)}/Document%20%2F%201`);
        assert.equal(env.frappe.get_user_settings('Unrelated').open_in_builder, undefined);
        await click();
        assert.ok(settings.get_form_link(doc).startsWith(`/app/${builder}/`));
        assert.equal(refreshes, 2);
        env.fail();
        await click();
        assert.equal(button.disabled, false);
        assert.equal(button.on, true);
        assert.equal(env.messages(), 1);
    });
}

test('rows switch target immediately, before the preference save finishes', async () => {
    const env = environment();
    let finishSave;
    env.frappe.model.user_settings.save = () => new Promise(resolve => { finishSave = resolve; });
    vm.runInNewContext(fs.readFileSync(path.join(root, 'doctype_list_js', 'email_template_list.js'), 'utf8'), env.context);
    const settings = env.frappe.listview_settings['Email Template'];
    let click, renders = 0;
    const button = {attrs: {}, classes: new Set(), html() { return this; }, addClass() { return this; },
        toggleClass() { return this; }, attr(key, value) { this.attrs[key] = value; return this; }, prop() { return this; }};
    const list = {doctype: 'Email Template', data: [{name: 'TEST'}], render() { renders++; }, async refresh() {},
        page: {add_inner_button(label, action) { click = action; return button; }}};
    env.frappe.builder_list_navigation.mount(list);
    const saving = click();
    // The save has not finished, yet a click on a row must already follow the new choice.
    assert.equal(settings.get_form_link({name: 'TEST'}), '/desk/email-template/TEST');
    assert.equal(renders, 1);
    assert.equal(button.attrs['aria-checked'], 'false');
    finishSave();
    await saving;
});

test('Emails list adds duplicate and move actions', async () => {
    const env = environment();
    env.frappe.call = () => Promise.resolve({message: {}});
    env.frappe.reach_folder_sidebar = {setup() {}};
    env.frappe.require = () => {};
    vm.runInNewContext(fs.readFileSync(path.join(root, 'doctype_list_js', 'email_template_list.js'), 'utf8'), env.context);
    const settings = env.frappe.listview_settings['Email Template'];
    const actions = [];
    const chain = {html() { return chain; }, addClass() { return chain; }, toggleClass() { return chain; }, attr() { return chain; }, prop() { return chain; }};
    const list = {page: {add_action_item: label => actions.push(label), add_button() {}, add_inner_button() { return chain; }, set_primary_action() {}},
        get_checked_items: () => [], $result: {find: () => ({toArray: () => [], find: () => ({first: () => ({length: 0})})})}};
    settings.onload(list);
    assert.ok(actions.includes('Duplicate'));
    assert.ok(actions.includes('Move to folder…'));
});

test('Emails list fills the Status and Used in columns and leaves the row layout alone', async () => {
    const env = environment();
    const cells = {}, labels = {};
    const cell = name => (cells[name] = {content: '', tip: '', html(v) { this.content = v; return this; }, attr(k, v) { if (k === 'title') this.tip = v; return this; }});
    const row = {find(selector) {
        if (selector === '.list-row-checkbox') return {attr: () => 'TEST'};
        const field = /data-fieldname="([^"]+)"/.exec(selector);
        return cell(field[1]);
    }};
    const header = selector => {
        const field = /data-fieldname="([^"]+)"/.exec(selector)[1];
        return {find: () => ({first: () => ({length: 1, text: value => { labels[field] = value; }})})};
    };
    env.context.$ = value => value;
    env.frappe.call = () => Promise.resolve({message: {TEST: {status: 'In workflow', send_time: '2026-11-16 08:00:00', used_in: [{title: 'WF <A>'}, {title: 'WF B'}]}}});
    env.frappe.utils = {escape_html: value => String(value).replace(/</g, '&lt;')};
    env.frappe.datetime = {str_to_user: value => value};
    env.frappe.reach_folder_sidebar = {setup() {}};
    vm.runInNewContext(fs.readFileSync(path.join(root, 'doctype_list_js', 'email_template_list.js'), 'utf8'), env.context);
    const list = {$result: {find: selector => selector === '.list-row-container' ? {toArray: () => [row]} : selector.startsWith('.list-row-head') ? header(selector) : null}};
    env.frappe.listview_settings['Email Template'].refresh(list);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(labels.custom_builder_mode, 'Status');
    assert.equal(labels.response, 'Used in');
    assert.ok(cells.custom_builder_mode.content.includes('In workflow'));
    assert.ok(cells.response.content.includes('WF &lt;A&gt;') || cells.response.content.includes('WF &lt;A>'));
    assert.ok(cells.response.tip.includes('WF B'));
    assert.ok(cells.response.tip.includes('2026-11-16 08:00'));
});
