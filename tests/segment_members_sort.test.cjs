const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function builder(isNew = false) {
    const frappe = {
        ui: { form: { on() {} } },
        datetime: { str_to_user: value => `user(${value})` },
        meta: {}, router: {}, utils: { escape_html: text => String(text) },
    };
    const context = { frappe, __: (text, args) => args ? text.replace(/\{(\d)\}/g, (_, i) => args[i]) : text, $: () => ({}) };
    const filename = path.join(__dirname, '../finbyzreach/finbyzreach/doctype/reach_segment/reach_segment.js');
    vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Builder = ReachSegmentBuilder;', context);
    const instance = Object.create(context.Builder.prototype);
    instance.frm = { is_new: () => isNew, doc: { creation: '2026-11-10 09:15:30.123456', owner: 'a@x.ch', modified: '2026-11-18 14:02:11.5', modified_by: 'b@x.ch' } };
    instance.loads = [];
    instance.load = reset => { instance.loads.push(reset); return Promise.resolve(); };
    return instance;
}

test('clicking a header sorts ascending, then descending, then clears, and reloads from page one', async () => {
    const instance = builder();
    await instance.sort('lead_name');
    assert.deepEqual([instance.sortBy, instance.sortOrder], ['lead_name', 'asc']);
    await instance.sort('lead_name');
    assert.deepEqual([instance.sortBy, instance.sortOrder], ['lead_name', 'desc']);
    await instance.sort('lead_name');
    assert.equal(instance.sortBy, null);
    await instance.sort('email_id');
    await instance.sort('lead_name');
    assert.deepEqual([instance.sortBy, instance.sortOrder], ['lead_name', 'asc'], 'a new column starts ascending');
    assert.ok(instance.loads.every(reset => reset === true));
});

test('the detail page shows the exact created and modified time with the person', () => {
    const text = builder().stamps();
    assert.match(text, /Created user\(2026-11-10 09:15:30\) by a@x\.ch/);
    assert.match(text, /Modified user\(2026-11-18 14:02:11\) by b@x\.ch/);
    assert.equal(builder(true).stamps(), '');
});
