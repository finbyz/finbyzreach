const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function library({ writable = true, readable = true } = {}) {
    const calls = [];
    const html = new Map();
    const values = new Map();
    const handlers = new Map();
    let styleCalls = 0;
    const root = {
        html(value) { html.set('root', value); return this; },
        on(event, selector, handler) { handlers.set(`${event} ${selector}`, handler); return this; },
        find(selector) { return {
            html(value) { html.set(selector, value); return this; },
            text() { return this; }, prop() { return this; }, on() { return this; }, toggle() { return this; },
            val(value) { if (value !== undefined) values.set(selector, value); return values.get(selector) || ''; },
        }; },
    };
    const frappe = {
        reach_segment_library: {}, provide() {},
        email_template_library: { ensure_styles() { styleCalls++; } },
        utils: { escape_html: value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'), icon: () => '' },
        model: { can_read: () => readable, can_create: () => writable, can_write: () => writable },
        ui: { Dialog: class { constructor() { this.fields_dict = {browser: {$wrapper: root}}; } show() {} } },
        msgprint() {}, show_alert() {},
        call: async options => {
            calls.push(JSON.parse(JSON.stringify(options)));
            return {message: options.args.doctype === 'Reach Segment Folder' ? [{name:'Swiss',folder_name:'Swiss'}] : [
                {name:'<unsafe "name">', audience_doctype:'Contact',segment_type:'Static',member_count:3},
            ]};
        },
        prompt(fields, action) { frappe.promptFields = fields; frappe.promptAction = action; },
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/segment_library.js'),'utf8'), {
        frappe, __: text => text, setTimeout, clearTimeout,
        $: node => ({ attr: name => node.attrs[name] }),
    });
    return {frappe, calls, html, handlers, styleCalls: () => styleCalls};
}

test('folder browser uses native permission-aware lists and bounded pages', async () => {
    const {frappe,calls,html} = library();
    const browser = frappe.reach_segment_library.open({audience_doctype:'Contact'});
    await browser.load();
    const segmentCall = calls.filter(call => call.args.doctype === 'Reach Segment').at(-1);
    assert.equal(segmentCall.method,'frappe.client.get_list');
    assert.equal(segmentCall.type,'GET');
    assert.equal(segmentCall.args.limit_page_length,51);
    assert.ok(segmentCall.args.filters.some(filter => JSON.stringify(filter) === JSON.stringify(['audience_doctype','=','Contact'])));
    assert.ok(html.get('.rs-library-body').includes('&lt;unsafe &quot;name&quot;&gt;'));
    assert.ok(!html.get('.rs-library-body').includes('<unsafe'));
    browser.page = 1;
    await browser.load();
    assert.equal(calls.at(-1).args.limit_start,50);
});

test('subfolder and Without Folder navigation use the correct persisted links', async () => {
    const {frappe,calls,html} = library();
    const browser = frappe.reach_segment_library.open();
    await browser.load();
    assert.ok(html.get('.rs-library-body').includes('Without Folder'));
    browser.path.push({name:'Swiss',label:'Swiss'});
    await browser.load();
    assert.deepEqual(calls.at(-2).args.filters,[['parent_reach_segment_folder','=','Swiss']]);
    assert.ok(calls.at(-1).args.filters.some(filter => JSON.stringify(filter) === JSON.stringify(['folder','=','Swiss'])));
    browser.path = [browser.path[0], {name:'',label:'Without Folder'}];
    const before = calls.length;
    await browser.load();
    assert.equal(calls.length,before+1);
    assert.ok(calls.at(-1).args.filters.some(filter => JSON.stringify(filter) === JSON.stringify(['folder','is','not set'])));
});

test('new subfolder uses native insert with the selected parent', async () => {
    const {frappe,calls} = library();
    frappe.reach_segment_library.new_folder('Swiss');
    await frappe.promptAction({folder_name:' Zurich ',parent:'Swiss'});
    assert.equal(calls.at(-1).method,'frappe.client.insert');
    assert.deepEqual(calls.at(-1).args.doc,{doctype:'Reach Segment Folder',folder_name:'Zurich',parent_reach_segment_folder:'Swiss'});
});

test('read-only library hides creation and move actions', async () => {
    const {frappe,html} = library({writable:false});
    const browser = frappe.reach_segment_library.open();
    await browser.load();
    assert.ok(!html.get('root').includes('rs-library-new-folder'));
    assert.ok(!html.get('.rs-library-body').includes('data-move'));
});

test('no-read user cannot open the library or fetch records', () => {
    const {frappe,calls} = library({readable:false});
    assert.equal(frappe.reach_segment_library.open(),undefined);
    assert.equal(calls.length,0);
});


test('segment explorer reuses template styles and switches list/grid without refetching', async () => {
    const {frappe,calls,html,styleCalls} = library();
    const browser = frappe.reach_segment_library.open();
    await browser.load();
    assert.equal(styleCalls(),1);
    assert.ok(html.get('root').includes('etl5-search-wrap'));
    assert.ok(html.get('.rs-library-body').includes('etl5-folder-card'));
    assert.ok(html.get('.rs-library-body').includes('is-list-view'));
    const requests = calls.length;
    browser.setView('grid');
    assert.ok(!html.get('.rs-library-body').includes('is-list-view'));
    assert.equal(calls.length,requests);
    browser.setView('list');
    assert.ok(html.get('.rs-library-body').includes('is-list-view'));
});

test('folder plus action creates a child under that folder without navigating', async () => {
    const {frappe,handlers} = library();
    const browser = frappe.reach_segment_library.open();
    await browser.load();
    let stopped = false;
    handlers.get('click [data-new-child]')({currentTarget:{attrs:{'data-new-child':'0'}},stopPropagation() { stopped = true; }});
    assert.equal(stopped,true);
    assert.equal(frappe.promptFields[1].default,'Swiss');
    assert.equal(browser.folder,'All Reach Segment Folders');
});
