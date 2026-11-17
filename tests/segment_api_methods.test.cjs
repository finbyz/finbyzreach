const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('record membership form actions send GET to the read-only endpoint', async () => {
    const forms = {};
    const calls = [];
    const frappe = {
        ui: { form: { on: (doctype, handlers) => { forms[doctype] = handlers; } } },
        model: { can_read: () => true, can_write: () => false },
        listview_settings: {}, realtime: { on: () => {} },
        call: options => { calls.push(options); return Promise.resolve({ message: [] }); }
    };
    const source = fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/segment_membership.js'), 'utf8');
    vm.runInNewContext(source, { frappe, __: text => text });
    for (const doctype of ['Lead', 'Contact', 'Customer']) {
        forms[doctype].refresh({ is_new: () => false, doc: {name:'TEST-RECORD'}, add_custom_button: () => {} });
    }
    await Promise.resolve();
    assert.equal(calls.length, 3);
    for (const call of calls) {
        assert.equal(call.method, 'finbyzreach.segments.record_segments');
        assert.equal(call.type, 'GET');
        assert.equal(call.args.name, 'TEST-RECORD');
    }
});

test('native list reload preserves onload and installs segment actions once', () => {
    let nativeLoads = 0;
    const actions = [];
    const menu = [];
    const frappe = {
        ui: { form: { on: () => {} } },
        model: { can_read: () => true, can_write: () => true },
        listview_settings: {}, realtime: { on: () => {} }
    };
    const context = { frappe, __: text => text };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/segment_membership.js'), 'utf8'), context);
    // Frappe loads the native DocType script after app_include_js.
    frappe.listview_settings.Contact = { onload() { nativeLoads++; }, hide_name_column: true };
    frappe.reach_segment_membership.setup_list('Contact');
    frappe.reach_segment_membership.setup_list('Contact');
    frappe.listview_settings.Contact.onload({page: {add_action_item(label) { actions.push(label); }, add_menu_item(label) { menu.push(label); }}});
    assert.equal(nativeLoads, 1);
    assert.deepEqual(menu, ['Filter by segment']);
    assert.equal(frappe.listview_settings.Contact.hide_name_column, true);
    assert.deepEqual(actions, ['Create segment from selection', 'Add to segment', 'Remove from segment']);
});

test('saved record forms offer Static add-to-segment, use POST and reload only memberships', async () => {
    const forms = {}, calls = [];
    let prompt, action, query;
    const frappe = {
        ui: {form: {on(doctype, handlers) {forms[doctype] = handlers;}}},
        model: {can_read: () => true, can_write: () => true},
        listview_settings: {}, realtime: {on() {}}, show_alert() {},
        prompt(field, callback) {query = field.get_query(); prompt = callback;},
        async call(options) { calls.push(options); return {message: {segments: []}}; },
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/segment_membership.js'), 'utf8'), {frappe, __: text => text});
    for (const doctype of ['Lead', 'Contact', 'Customer', 'Opportunity', 'Sales Order']) {
        calls.length = 0;
        const doc = {name: 'RECORD-1'};
        forms[doctype].refresh({is_new: () => false, doc, add_custom_button(label, callback) {if (label === 'Add to segment') action = callback;}});
        action();
        assert.equal(query.filters.audience_doctype, doctype);
        assert.equal(query.filters.segment_type, 'Static');
        assert.equal(query.filters.archived, 0);
        await prompt({segment: 'Chosen'});
        const mutation = calls.find(call => call.type === 'POST');
        assert.equal(mutation.method, 'finbyzreach.segments.change_segment_members');
        assert.equal(mutation.args.segment_name, 'Chosen');
        assert.equal(mutation.args.action, 'add');
        assert.deepEqual(JSON.parse(mutation.args.records), ['RECORD-1']);
        assert.equal(calls.filter(call => call.type === 'GET').length, 2);
    }
});
