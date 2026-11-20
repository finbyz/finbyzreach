const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
    const buttons = new Map(), requests = [];
    const filters = new Map([['name', ['Old']], ['custom_folder', 'News']]);
    const list = {
        start: 100, refreshes: 0,
        page: {add_inner_button(label, handler) { buttons.set(label, handler); }},
        refresh() { this.refreshes++; },
        filter_area: {
            async remove(field) { filters.delete(field); },
            async add(values) { for (const [, field, , names] of values) filters.set(field, Array.from(names)); list.refresh(); },
        },
    };
    const frappe = {
        listview_settings: {}, email_template_builder: {}, provide() {},
        user: {has_role: () => false}, reach_folder_sidebar: {setup() {}},
        builder_list_navigation: {setup() {}}, require() {},
        call(args) { return new Promise((resolve, reject) => requests.push({args, resolve, reject})); },
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/doctype_list_js/email_template_list.js'), 'utf8'), {frappe, __: x => x});
    frappe.listview_settings['Email Template'].onload(list);
    return {buttons, requests, filters, list};
}

test('each sending status applies its results from the first page and preserves folder filters', async () => {
    for (const status of ['Draft', 'Scheduled', 'Sending', 'Paused', 'Completed', 'Cancelled', 'Failed']) {
        const {buttons, requests, filters, list} = setup();
        const applied = buttons.get(status)();
        assert.equal(requests[0].args.args.status, status);
        assert.deepEqual(filters.get('name'), ['Old']);
        requests[0].resolve({message: ['Matching email']});
        await applied;
        assert.equal(list.start, 0);
        assert.deepEqual(filters.get('name'), ['Matching email']);
        assert.equal(filters.get('custom_folder'), 'News');
        assert.ok(list.refreshes > 0);
    }
});

test('a slower earlier status response cannot replace the latest selection', async () => {
    const {buttons, requests, filters} = setup();
    const first = buttons.get('Draft')();
    const second = buttons.get('Completed')();
    requests[1].resolve({message: ['Completed email']});
    await second;
    requests[0].resolve({message: ['Draft email']});
    await first;
    assert.deepEqual(filters.get('name'), ['Completed email']);
});

test('All e-mails cancels pending selections and resets pagination', async () => {
    const {buttons, requests, filters, list} = setup();
    const pending = buttons.get('Draft')();
    await buttons.get('All e-mails')();
    requests[0].resolve({message: ['Draft email']});
    await pending;
    assert.equal(filters.has('name'), false);
    assert.equal(filters.get('custom_folder'), 'News');
    assert.equal(list.start, 0);
});

test('empty results apply an empty-match filter', async () => {
    const {buttons, requests, filters} = setup();
    const pending = buttons.get('Failed')();
    requests[0].resolve({message: []});
    await pending;
    assert.deepEqual(filters.get('name'), ['__none__']);
});

test('a failed lookup retains the current results and pagination', async () => {
    const {buttons, requests, filters, list} = setup();
    const pending = buttons.get('Draft')();
    requests[0].reject(new Error('Server unavailable'));
    await assert.rejects(pending, /Server unavailable/);
    assert.deepEqual(filters.get('name'), ['Old']);
    assert.equal(list.start, 100);
});
