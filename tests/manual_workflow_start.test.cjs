const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(route, listview) {
    const calls = [], dialogs = [], messages = [];
    let onChange;
    const frappe = {
        provide(name) { frappe.manual_workflow_start = frappe.manual_workflow_start || {}; },
        router: {on(event, callback) { onChange = callback; }},
        get_route: () => route,
        call: args => { calls.push(args); return Promise.resolve({message: args.method.endsWith('manual_start_workflows')
            ? [{name: 'AWF-1', title: 'Follow up'}] : {enrolled: 2, skipped: [], skipped_count: 0}}); },
        msgprint: value => messages.push(value),
        show_alert() {},
        utils: {escape_html: v => String(v), get_random: () => 'random-key'},
        ui: {Dialog: function (opts) { dialogs.push(opts); this.show = () => {}; this.hide = () => {}; this.get_primary_btn = () => ({prop() {}}); }},
    };
    const context = {frappe, __: (text, args) => args ? text.replace(/\{(\d)\}/g, (m, i) => args[i]) : text, window: {cur_list: listview},
        $: () => ({on() {}}), document: {}, setTimeout};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/manual_workflow_start.js'), 'utf8'), context);
    return {frappe, calls, dialogs, messages, trigger: () => onChange && onChange()};
}

function listview(doctype, selected) {
    const actions = [];
    return {doctype, page: {add_action_item: (label, action) => actions.push({label, action})}, get_checked_items: () => selected.map(name => ({name})), actions};
}

test('Lead list gets a Start workflow action once; other lists get none', async () => {
    const lead = listview('Lead', ['LEAD-1']);
    const env = load(['List', 'Lead'], lead);
    env.trigger(); env.trigger();
    assert.deepEqual(lead.actions.map(a => a.label), ['Start workflow…']);
    const item = listview('Item', []);
    const other = load(['List', 'Item'], item);
    other.trigger();
    assert.equal(item.actions.length, 0);
});

test('the action starts the selected records in the chosen workflow', async () => {
    const lead = listview('Lead', ['LEAD-1', 'LEAD-2']);
    const env = load(['List', 'Lead'], lead);
    env.trigger();
    lead.actions[0].action();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(env.dialogs.length, 1);
    await env.dialogs[0].primary_action({workflow: 'AWF-1'});
    const start = env.calls.find(c => c.method.endsWith('enroll_manual_records'));
    assert.equal(start.args.workflow_id, 'AWF-1');
    assert.deepEqual(JSON.parse(start.args.record_names), ['LEAD-1', 'LEAD-2']);
    assert.equal(start.args.idempotency_key, 'random-key');
});

test('nothing selected asks the user to select records', () => {
    const lead = listview('Lead', []);
    const env = load(['List', 'Lead'], lead);
    env.trigger();
    lead.actions[0].action();
    assert.equal(env.calls.length, 0);
    assert.equal(env.messages.length, 1);
});
